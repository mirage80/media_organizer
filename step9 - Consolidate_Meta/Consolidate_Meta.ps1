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

# Load existing JSON (or create new)
$jsonData = @{}
if (Test-Path $metaPath) {
    try {
        # ConvertFrom-Json creates a PSCustomObject. To use methods like .ContainsKey(),
        # we must convert it into a true Hashtable. This is the most compatible way.
        $jsonObject = Get-Content $metaPath -Raw | ConvertFrom-Json -Depth 10
        foreach($property in $jsonObject.PSObject.Properties) {
            $jsonData.Add($property.Name, $property.Value)
        }
    } catch {
        & $Log "CRITICAL" "Failed to parse existing JSON at $metaPath : $($_.Exception.Message)"
        exit 1
    }
}

# Enumerate all media files (images/videos)
$mediaFiles = Get-ChildItem -Path $unzippedDirectory -Recurse -File

$total = $mediaFiles.Count
$current = 0

foreach ($file in $mediaFiles) {
    $current++
    $percent = if ($total -gt 0) { [int](($current / $total) * 100) } else { 100 }
    Update-GraphicalProgressBar -SubTaskPercent $percent -SubTaskMessage "Enriching metadata for file $(Split-Path $file.FullName -Leaf)"

    $path = $file.FullName

    if (-not (Test-Path $path)) {
        & $Log "WARNING" "Skipping missing file: $path"
        continue
    }

    if (-not $jsonData.ContainsKey($path)) {
        $jsonData[$path] = @{}
    }

    try {
        $timestamp_from_filename = Get-FilenameTimestamp -File $file
        $timestamp_from_exif     = Get-ExifTimestamp -File $file
        $timestamp_from_ffprobe  = Get-FFprobeTimestamp -File $file

        $geotag_from_filename    = Get-FilenameGeotag -File $file
        $geotag_from_exif        = Get-ExifGeotag -File $file
        $geotag_from_ffprobe     = Get-FFprobeGeotag -File $file

        $jsonData[$path].timestamp_from_filename = $timestamp_from_filename
        $jsonData[$path].timestamp_from_exif     = $timestamp_from_exif
        $jsonData[$path].timestamp_from_ffprobe  = $timestamp_from_ffprobe

        $jsonData[$path].geotag_from_filename    = $geotag_from_filename
        $jsonData[$path].geotag_from_exif        = $geotag_from_exif
        $jsonData[$path].geotag_from_ffprobe     = $geotag_from_ffprobe
    } catch {
        & $Log "ERROR" "Failed to enrich metadata for '$path': $($_.Exception.Message)"
    }
}

# Save final JSON
try {
    Write-JsonAtomic -Data $jsonData -Path $metaPath
    & $Log "INFO" "Successfully updated consolidated metadata."
} catch {
    & $Log "CRITICAL" "Failed to write consolidated metadata: $($_.Exception.Message)"
    exit 1
}

& $Log "INFO" "--- Script Finished: $scriptName ---"
