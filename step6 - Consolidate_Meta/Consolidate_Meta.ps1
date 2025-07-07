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

# --- Module Imports ---
$UtilDirectory = Join-Path $scriptDirectory "..\Utils"
$UtilFile = Join-Path $UtilDirectory "Utils.psm1"
Import-Module $UtilFile -Force

$MediaToolsFile = Join-Path $UtilDirectory 'MediaTools.psm1'
Import-Module $MediaToolsFile -Force

# --- Logging Setup ---
$childLogFilePath = Join-Path "$scriptDirectory\..\Logs" -ChildPath ("Step_$step" + "_" + "$scriptName.log")
$logLevelMap = $env:LOG_LEVEL_MAP_JSON | ConvertFrom-Json -AsHashtable
$consoleLogLevel = $logLevelMap[$env:DEDUPLICATOR_CONSOLE_LOG_LEVEL.ToUpper()]
$fileLogLevel    = $logLevelMap["WARNING"]
$Log = {
    param([string]$Level, [string]$Message)
    Write-Log -Level $Level -Message $Message -LogFilePath $childLogFilePath -ConsoleLogLevel $consoleLogLevel -FileLogLevel $fileLogLevel -LogLevelMap $logLevelMap
}

& $Log "INFO" "--- Script Started: $scriptName ---"
Set-UtilsLogger -Logger $Log
Set-MediaToolsLogger -Logger $Log

$OutputDirectory = Join-Path $scriptDirectory "..\Outputs"
$metaPath = Join-Path $OutputDirectory "Consolidate_Meta_Results.json"

if (-not (Test-Path $metaPath)) {
    & $Log "CRITICAL" "Consolidated metadata file not found: $metaPath"
    exit 1
}

try {
    $jsonData = Get-Content $metaPath -Raw | ConvertFrom-Json -Depth 10
} catch {
    & $Log "CRITICAL" "Failed to parse JSON: $($_.Exception.Message)"
    exit 1
}

$total = $jsonData.Count
$current = 0

foreach ($path in $jsonData.PSObject.Properties.Name) {
    $current++
    Show-ProgressBar -Current $current -Total $total -Message "Step $step : Merging best metadata for $(Split-Path $path -Leaf)"

    if (-not (Test-Path $path)) {
        & $Log "WARNING" "Skipping missing file: $path"
        continue
    }

    try {
        $file = Get-Item $path
        $merged = Merge-FileMetadata -File $file
        $jsonData[$path].ConsolidatedTimestamp = $merged.ConsolidatedTimestamp
        $jsonData[$path].ConsolidatedGeotag    = $merged.ConsolidatedGeotag
    } catch {
        & $Log "ERROR" "Failed to consolidate metadata for '$path': $($_.Exception.Message)"
    }
}

try {
    Write-JsonAtomic -Data $jsonData -Path $metaPath
    & $Log "INFO" "Successfully updated consolidated metadata with final chosen fields."
} catch {
    & $Log "CRITICAL" "Failed to write JSON: $($_.Exception.Message)"
    exit 1
}

& $Log "INFO" "--- Script Finished: $scriptName ---"
