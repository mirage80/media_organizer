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

# --- Paths ---
$UtilDirectory = Join-Path $scriptDirectory "..\Utils"
$UtilFile = Join-Path $UtilDirectory "Utils.psm1"
$MediaToolsFile = Join-Path $UtilDirectory "MediaTools.psm1"
$OutputDirectory = Join-Path $scriptDirectory "..\Outputs"
$metaPath = Join-Path $OutputDirectory "Consolidate_Meta_Results.json"

# --- Import Modules ---
Import-Module $UtilFile -Force
Import-Module $MediaToolsFile -Force

# --- Logging Setup ---
$childLogFilePath = Join-Path "$scriptDirectory\..\Logs" -ChildPath ("Step_$step" + "_" + "$scriptName.log")
$logLevelMap = $env:LOG_LEVEL_MAP_JSON | ConvertFrom-Json -AsHashtable
$consoleLogLevel = $logLevelMap[$env:DEDUPLICATOR_CONSOLE_LOG_LEVEL.ToUpper()]
$fileLogLevel    = $logLevelMap[$env:DEDUPLICATOR_FILE_LOG_LEVEL.ToUpper()]
$Log = {
    param([string]$Level, [string]$Message)
    Write-Log -Level $Level -Message $Message -LogFilePath $childLogFilePath -ConsoleLogLevel $consoleLogLevel -FileLogLevel $fileLogLevel -LogLevelMap $logLevelMap
}

# Inject Logger
Set-UtilsLogger -Logger $Log
Set-MediaToolsLogger -Logger $Log

& $Log "INFO" "--- Script Started: $scriptName ---"

# --- Load existing JSON ---
if (-not (Test-Path $metaPath)) {
    & $Log "CRITICAL" "Consolidated metadata file not found: $metaPath"
    exit 1
}

try {
    $jsonData = Get-Content $metaPath -Raw | ConvertFrom-Json -Depth 10
} catch {
    & $Log "CRITICAL" "Failed to parse JSON at $metaPath : $($_.Exception.Message)"
    exit 1
}

$allPaths = $jsonData.PSObject.Properties.Name
$total = $allPaths.Count
$current = 0

foreach ($path in $allPaths) {
    $current++
    Show-ProgressBar -Current $current -Total $total -Message "Step $step : Enriching metadata for file $(Split-Path $path -Leaf)"

    if (-not (Test-Path $path)) {
        & $Log "WARNING" "Skipping missing file: $path"
        continue
    }

    try {
        $file = Get-Item $path

        # Correcting function calls to match definitions in MediaTools.psm1
        $timestamp_from_filename = Parse_DateTimeFromFilename -FilePath $file
        $timestamp_from_exif     = Get_Exif_Timestamp -File $file

        # NOTE: The following functions are not defined in the provided MediaTools.psm1 and will cause errors.
        # You will need to implement them or remove these lines.
        # $timestamp_from_ffprobe  = Get-TimestampFromFFprobe -File $file
        $timestamp_from_ffprobe = $null # Placeholder

        # $geotag_from_filename = Get-GeotagFromFilename -File $file
        $geotag_from_filename = $null # Placeholder
        $geotag_from_exif     = Get_Exif_Geotag -File $file
        # $geotag_from_ffprobe  = Get-GeotagFromFFprobe -File $file
        $geotag_from_ffprobe = $null # Placeholder

        $jsonData[$path].timestamp_from_filename = $timestamp_from_filename
        $jsonData[$path].timestamp_from_exif     = $timestamp_from_exif
        $jsonData[$path].timestamp_from_ffprobe  = $timestamp_from_ffprobe

        $jsonData[$path].geotag_from_filename = $geotag_from_filename
        $jsonData[$path].geotag_from_exif     = $geotag_from_exif
        $jsonData[$path].geotag_from_ffprobe  = $geotag_from_ffprobe
    } catch {
        & $Log "ERROR" "Failed to enrich metadata for '$path': $($_.Exception.Message)"
    }
}

# --- Write Final JSON ---
try {
    Write-JsonAtomic -Data $jsonData -Path $metaPath
    & $Log "INFO" "Successfully updated consolidated metadata with EXIF/ffprobe/filename data."
} catch {
    & $Log "CRITICAL" "Failed to write consolidated metadata: $($_.Exception.Message)"
    exit 1
}

& $Log "INFO" "--- Script Finished: $scriptName ---"
