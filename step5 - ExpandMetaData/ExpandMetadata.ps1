param(
    [Parameter(Mandatory=$true)]
    [string]$unzippedDirectory,
    [Parameter(Mandatory=$true)]
    [string]$ExifToolPath,
    [Parameter(Mandatory=$true)]
    [string]$ffprobe,
    [Parameter(Mandatory=$true)]
    [string]$step
)

# --- Path Setup ---
$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

# Outputs Directory
$OutputDirectory = Join-Path $scriptDirectory "..\Outputs"
$metaPath = Join-Path $OutputDirectory "Consolidate_Meta_Results.json"

# Utils Directory
$UtilDirectory = Join-Path $scriptDirectory "..\Utils"
$UtilFile = Join-Path $UtilDirectory "Utils.psm1"
$MediaToolsFile = Join-Path $UtilDirectory 'MediaTools.psm1'
Import-Module $UtilFile -Force
Import-Module $MediaToolsFile -Force

# --- Logging Setup ---
$logDirectory = Join-Path $scriptDirectory "..\Logs"
$Logger = Initialize-ScriptLogger -LogDirectory $logDirectory -ScriptName $scriptName -Step $step
$Log = $Logger.Logger
$childLogFilePath = $Logger.LogFilePath

# Inject logger for module functions
Set-UtilsLogger -Logger $Log
Set-MediaToolsLogger -Logger $Log

& $Log "INFO" "--- Script Started: $scriptName ---"

# Getting the console log level from environment variable or defaulting to INFO
$consoleLogLevel = $logLevelMap[$env:DEDUPLICATOR_CONSOLE_LOG_LEVEL.ToUpper()]
$fileLogLevel    = $logLevelMap[$env:DEDUPLICATOR_FILE_LOG_LEVEL.ToUpper()]

$initialData = @{}
if (Test-Path $metaPath) {
    try {
        # Load the file content and convert from JSON into a hashtable.
        $initialData = Get-Content $metaPath -Raw | ConvertFrom-Json -AsHashtable -Depth 100
    } catch {
        & $Log "CRITICAL" "Failed to parse JSON at $metaPath : $($_.Exception.Message)"
        exit 1
    }
}

# Create a thread-safe ConcurrentDictionary with the desired string comparer.
# This uses an unambiguous constructor that is guaranteed to exist.
$jsonData = [System.Collections.Concurrent.ConcurrentDictionary[string, object]]::new([System.StringComparer]::OrdinalIgnoreCase)

# Populate the dictionary from the initial data. This two-step process is more robust
# than relying on constructor overload resolution, which can be ambiguous in PowerShell.
if ($null -ne $initialData) {
    foreach ($key in $initialData.Keys) {
        $jsonData.TryAdd($key, $initialData[$key]) | Out-Null
    }
}

# Use a synchronized hashtable as a shared, thread-safe object for the progress counter.
$progressData = [hashtable]::Synchronized(@{ Counter = 0 })

# A single lock object to be shared by all threads for synchronized logging.
$logLock = [System.Object]::new()

# --- Gather Media Files and Prepare for Multithreading ---
$mediaFiles = Get-ChildItem -Path $unzippedDirectory -Recurse -File
& $Log "INFO" "Discovered $($mediaFiles.Count) media files under $unzippedDirectory"
$total      = $mediaFiles.Count

# A thread-safe queue to hold the file paths for processing.
$fileQueue = [System.Collections.Concurrent.ConcurrentQueue[string]]::new()
$mediaFiles | ForEach-Object { $fileQueue.Enqueue($_.FullName) }

# --- Configure Runspaces ---
$maxThreads = [Math]::Max(1, [Environment]::ProcessorCount - 1)
# Suppress the output from the logger by piping to Out-Null instead of assigning to the automatic variable $_.
& $Log "INFO" "Initializing runspace pool with $maxThreads threads." | Out-Null

# Ensure the necessary assembly is loaded to find the SessionStateVariableEntry type.
Add-Type -AssemblyName System.Management.Automation

# Use InitialSessionState to reliably share variables and modules with threads.
$initialSessionState = [System.Management.Automation.Runspaces.InitialSessionState]::CreateDefault()
$initialSessionState.ImportPSModule(@($UtilFile, $MediaToolsFile))
$initialSessionState.Variables.Add((New-Object System.Management.Automation.Runspaces.SessionStateVariableEntry('jsonData', $jsonData, 'Shared results dictionary')))
$initialSessionState.Variables.Add((New-Object System.Management.Automation.Runspaces.SessionStateVariableEntry('progressData', $progressData, 'Shared progress data')))
$initialSessionState.Variables.Add((New-Object System.Management.Automation.Runspaces.SessionStateVariableEntry('logLock', $logLock, 'Shared log lock object')))
$initialSessionState.Variables.Add((New-Object System.Management.Automation.Runspaces.SessionStateVariableEntry('childLogFilePath', $childLogFilePath, 'Log file path')))
$initialSessionState.Variables.Add((New-Object System.Management.Automation.Runspaces.SessionStateVariableEntry('consoleLogLevel', $consoleLogLevel, 'Console log level')))
$initialSessionState.Variables.Add((New-Object System.Management.Automation.Runspaces.SessionStateVariableEntry('fileLogLevel', $fileLogLevel, 'File log level')))
$initialSessionState.Variables.Add((New-Object System.Management.Automation.Runspaces.SessionStateVariableEntry('logLevelMap', $logLevelMap, 'Log level map')))
$initialSessionState.Variables.Add((New-Object System.Management.Automation.Runspaces.SessionStateVariableEntry('fileQueue', $fileQueue, 'Shared file queue')))

<# Use the correct overload to create the pool with the shared session state. #>
$runspacePool = [RunspaceFactory]::CreateRunspacePool(1, $maxThreads, $initialSessionState, $host)
$runspacePool.Open()

# Store custom objects containing both the PowerShell instance and its async result.
$runningJobs = @()

$threadScript = {
    param(
        [System.Collections.Concurrent.ConcurrentDictionary[string, object]]$jsonData,
        [hashtable]$progressData,
        [System.Object]$logLock,
        [string]$childLogFilePath,
        [int]$consoleLogLevel,
        [int]$fileLogLevel,
        [hashtable]$logLevelMap,
        [string]$UtilFile,
        [string]$MediaToolsFile,
        [System.Collections.Concurrent.ConcurrentQueue[string]]$fileQueue
    )
    Import-Module $UtilFile -Force
    Import-Module $MediaToolsFile -Force

    $Log = {
        param([string]$Level, [string]$Message)
        Write-Log -Level $Level -Message $Message `
            -LogFilePath $childLogFilePath `
            -ConsoleLogLevel $consoleLogLevel `
            -FileLogLevel $fileLogLevel `
            -LogLevelMap $logLevelMap `
            -LockObject $logLock

    }

    Set-UtilsLogger -Logger $Log
    Set-MediaToolsLogger -Logger $Log
    & $Log "DEBUG" "Runspace thread started."
    $filePath = $null
    while ($fileQueue.TryDequeue([ref]$filePath)) {
        if (-not $filePath) {
            & $Log "WARNING" "Received null or empty file path, skipping."
            continue
        }

        # Ensure the file path is normalized to match the keys in the JSON data.
       try {
            # Standardize the path to match the keys in the JSON data (which use '/')
            $normalizedPath = ConvertTo-StandardPath -Path $filePath

            & $Log "INFO" "Runspace thread started processing file: $normalizedPath"
            if (-not (Test-Path $normalizedPath)) {
                & $Log "WARNING" "Skipping missing file: $normalizedPath"
                continue
            }
            $file = Get-Item -LiteralPath $normalizedPath
            # Correctly call Test-IsVideo with a FileInfo object.
            $isVideo = Test-IsVideo -File $file

            $timestamp_from_filename = Get-FilenameTimestamp -File $file
            $geotag_from_filename    = Get-FilenameGeotag   -File $file
            $timestamp_from_exif     = Get-ExifTimestamp    -File $file
            $geotag_from_exif        = Get-ExifGeotag       -File $file

            if ($isVideo) {
                $timestamp_from_ffprobe = Get-FFprobeTimestamp -File $file
                $geotag_from_ffprobe    = Get-FFprobeGeotag    -File $file
                $rotation_from_ffprobe  = Get-FfprobeRotation  -File $file
            } else {
                $timestamp_from_ffprobe = $null
                $geotag_from_ffprobe    = $null
                $rotation_from_ffprobe  = $null
            }

            # Ensure the node for this path exists before adding properties.
            if (-not $jsonData.ContainsKey($normalizedPath)) {
                $jsonData[$normalizedPath] = New-DefaultMetadataObject -filepath $normalizedPath
            }

            $jsonData[$normalizedPath].exif += @{ timestamp = $timestamp_from_exif; geotag = $geotag_from_exif }
            $jsonData[$normalizedPath].ffprobe += @{ timestamp = $timestamp_from_ffprobe; geotag = $geotag_from_ffprobe; rotation = $rotation_from_ffprobe }
            $jsonData[$normalizedPath].filename += @{ timestamp = $timestamp_from_filename; geotag = $geotag_from_filename }

            # Increment the shared progress counter.
            # A simple integer cannot be passed by reference to Interlocked.Increment.
            # We must use a lock on a shared object to safely increment the counter from multiple threads.
            $lockTaken = $false
            try {
                [System.Threading.Monitor]::Enter($progressData.SyncRoot, [ref]$lockTaken)
                if ($lockTaken) { $progressData.Counter++ }
            }
            finally {
                if ($lockTaken) { [System.Threading.Monitor]::Exit($progressData.SyncRoot) }
           }
        } catch {
            & $Log "ERROR" "Failed to enrich metadata for '$normalizedPath': $($_.Exception.Message)"
        }
            & $Log "INFO" "Runspace thread ended processing file: $normalizedPath"
    }
    & $Log "DEBUG" "Runspace thread finished."
}

for ($i = 0; $i -lt $maxThreads; $i++) {
    $powershell = [PowerShell]::Create()
    $powershell.RunspacePool = $runspacePool
    $null = $powershell.AddScript($threadScript).
        AddArgument($jsonData).
        AddArgument($progressData).
        AddArgument($logLock).
        AddArgument($childLogFilePath).
        AddArgument($consoleLogLevel).
        AddArgument($fileLogLevel).
        AddArgument($logLevelMap).
        AddArgument($UtilFile).
        AddArgument($MediaToolsFile).
        AddArgument($fileQueue)

    $asyncResult = $powershell.BeginInvoke()
    $null = $runningJobs += [PSCustomObject]@{
        Instance = $powershell
        Result   = $asyncResult
    }
}

# --- Monitor Progress and Wait for All Threads ---
while (($runningJobs | Where-Object { -not $_.Result.IsCompleted }).Count -gt 0) {
    # Reading the value from the synchronized hashtable is thread-safe.
    $completed = $progressData.Counter
    $percent = if ($total -gt 0) { [int](($completed / $total) * 100) } else { 100 }
    Update-GraphicalProgressBar -SubTaskPercent $percent -SubTaskMessage "Processed $completed of $total files..."
    Start-Sleep -Milliseconds 100
}

# Final progress bar update
Update-GraphicalProgressBar -SubTaskPercent 100 -SubTaskMessage "Processed $total of $total files. Finalizing..."

# Clean up jobs
# Call EndInvoke on the PowerShell instance, not the result object, to properly handle exceptions and output.
foreach ($job in $runningJobs) {
    $job.Instance.EndInvoke($job.Result)
    $job.Instance.Dispose()
}
$runspacePool.Close()
$runspacePool.Dispose()

# --- Save Final JSON ---
try {
    Write-JsonAtomic -Data $jsonData -Path $metaPath
    & $Log "INFO" "Successfully updated consolidated metadata with EXIF/ffprobe/filename data."
} catch {
    & $Log "CRITICAL" "Failed to write consolidated metadata: $($_.Exception.Message)"
    exit 1
}

& $Log "INFO" "--- Script Finished: $scriptName ---"
