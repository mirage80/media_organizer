param(
    [Parameter(Mandatory=$true)]
    [string]$unzippedDirectory,
    [string]$ExifToolPath,
    [Parameter(Mandatory = $true)] [string]$step
)

$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

# Outputs Directory
$OutputDirectory = Join-Path $scriptDirectory "..\Outputs"
$metaPath = Join-Path $OutputDirectory "Consolidate_Meta_Results.json"

# Utils Directory
$UtilDirectory = Join-Path $scriptDirectory "..\Utils"
$UtilFile = Join-Path $UtilDirectory "Utils.psm1"
Import-Module $UtilFile -Force

# --- Logging Setup for this script ---
# 1. Define the log file path
$MediaToolsFile = Join-Path $UtilDirectory 'MediaTools.psm1'
Import-Module $MediaToolsFile -Force

# --- Logging Setup for this script ---
# 1. Define the log file path
$childLogFilePath = Join-Path "$scriptDirectory\..\Logs" -ChildPath $("Step_$step" + "_" + "$scriptName.log")

# 2. Get logging configuration from environment variables
$logLevelMap = $env:LOG_LEVEL_MAP_JSON | ConvertFrom-Json -AsHashtable
$consoleLogLevel = $logLevelMap[$env:DEDUPLICATOR_CONSOLE_LOG_LEVEL.ToUpper()]
$fileLogLevel    = $logLevelMap[$env:DEDUPLICATOR_FILE_LOG_LEVEL.ToUpper()]

# 3. Create a local, pre-configured logger for this script
$Log = {
    param([string]$Level, [string]$Message)
    Write-Log -Level $Level -Message $Message -LogFilePath $childLogFilePath -ConsoleLogLevel $consoleLogLevel -FileLogLevel $fileLogLevel -LogLevelMap $logLevelMap
}

& $Log "INFO" "--- Script Started: $scriptName ---"

# Inject logger for module functions
Set-UtilsLogger -Logger $Log
Set-MediaToolsLogger -Logger $Log

# 4. Write initial log message to ensure file creation
& $Log "INFO" "--- Script Started: $scriptName ---"

# --- Load the consolidated metadata file which is our source of truth ---
if (-not (Test-Path $metaPath)) {
    & $Log "CRITICAL" "Consolidated metadata file not found at '$metaPath'. This script must run after 'Consolidate_Meta'."
    exit 1
}

try {
    $metadata = Get-Content $metaPath -Raw | ConvertFrom-Json
} catch {
    & $Log "CRITICAL" "Failed to parse JSON at '$metaPath': $($_.Exception.Message)"
    exit 1
}

$allPaths = $metadata.PSObject.Properties.Name
$totalItems = $allPaths.Count

if ($totalItems -eq 0) {
    & $Log "INFO" "No files found in metadata file to categorize."
    exit 0
}

& $Log "INFO" "Found $totalItems files to process."

# --- Setup Destination and Parallel Processing ---
$dstRoot = Join-Path -Path $OutputDirectory -ChildPath "Categorized_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
New-Item -Path $dstRoot -ItemType Directory -Force | Out-Null
& $Log "INFO" "Created destination root directory: $dstRoot"

$runspacePool = [runspacefactory]::CreateRunspacePool(1, [System.Environment]::ProcessorCount)
$runspacePool.Open()
$jobs = @()

# --- Main Loop ---
foreach ($filePath in $allPaths) {
    $fileData = $metadata.$filePath

    $job = [powershell]::Create().AddScript({
        param($currentFilePath, $currentFileData, $destinationRoot, $originalRoot, $logScriptBlock)

        # Inject the logger into this thread
        $Log = $logScriptBlock

        if (-not (Test-Path $currentFilePath)) {
            & $Log "WARNING" "File from metadata not found on disk, cannot categorize: $currentFilePath"
            return
        }

        # Determine category from the pre-consolidated data
        $hasTime = $null -ne $currentFileData.ConsolidatedTimestamp
        $hasGeo = $null -ne $currentFileData.ConsolidatedGeotag

        $category = "no_time_no_geo" # Default
        if ($hasTime -and $hasGeo) { $category = "with_time_with_geo" }
        elseif ($hasTime) { $category = "with_time_no_geo" }
        elseif ($hasGeo) { $category = "no_time_with_geo" }

        # Construct destination path, preserving relative structure
        $relativePath = $currentFilePath -replace [regex]::Escape($originalRoot), ""
        $relativePath = $relativePath.TrimStart("\/")
        
        $finalDir = Join-Path -Path $destinationRoot -ChildPath $category
        $destinationPath = Join-Path -Path $finalDir -ChildPath $relativePath

        try {
            # Ensure destination directory exists. -Force makes this thread-safe enough.
            New-Item -Path (Split-Path -Path $destinationPath -Parent) -ItemType Directory -Force -ErrorAction Stop | Out-Null
            
            # Move the file
            Move-Item -Path $currentFilePath -Destination $destinationPath -Force -ErrorAction Stop
        } catch {
            & $Log "ERROR" "Failed to move '$currentFilePath' to '$destinationPath'. Error: $($_.Exception.Message)"
        }
    }).AddParameters(@{
        currentFilePath = $filePath
        currentFileData = $fileData
        destinationRoot = $dstRoot
        originalRoot = $unzippedDirectory
        logScriptBlock = $Log
    })
    $job.RunspacePool = $runspacePool
    $jobs += $job.BeginInvoke()
}

# --- Wait for jobs and show progress ---
while ($jobs.IsCompleted -contains $false) {
    $completedCount = ($jobs | Where-Object { $_.IsCompleted }).Count
   Show-GraphicalProgressBar -Current $completedCount -Total $totalItems -Message "Categorizing Files"
    Start-Sleep -Milliseconds 200
}

# --- Finalize and Clean up ---
Show-ProgressBar -Current $totalItems -Total $totalItems -Message "Categorizing Files"
$jobs | ForEach-Object { $_.EndInvoke() } # Collect any exceptions
$runspacePool.Close()
$runspacePool.Dispose()

& $Log "INFO" "Categorization complete."