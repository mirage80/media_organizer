# Define the script directory
$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent

# Setup logging
$logDir = Join-Path $scriptDirectory "..\Logs"
$logFilePath = Join-Path $logDir "orphaned_json_cleanup.log"

if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$logLevelMap = @{
    "DEBUG"    = 0
    "INFO"     = 1
    "WARNING"  = 2
    "ERROR"    = 3
}
$env:DEDUPLICATOR_CONSOLE_LOG_LEVEL = $env:DEDUPLICATOR_CONSOLE_LOG_LEVEL ?? "INFO"
$env:DEDUPLICATOR_FILE_LOG_LEVEL    = $env:DEDUPLICATOR_FILE_LOG_LEVEL    ?? "DEBUG"
$consoleLogLevel = $logLevelMap[$env:DEDUPLICATOR_CONSOLE_LOG_LEVEL.ToUpper()]
$fileLogLevel = $logLevelMap[$env:DEDUPLICATOR_FILE_LOG_LEVEL.ToUpper()]

function Log {
    param (
        [string]$Level,
        [string]$Message
    )
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $formatted = "$timestamp - $Level - $Message"
    $levelIndex = $logLevelMap[$Level.ToUpper()]

    if ($levelIndex -ge $consoleLogLevel) {
        Write-Host $formatted
    }
    if ($levelIndex -ge $fileLogLevel) {
        Add-Content -Path $logFilePath -Value $formatted -Encoding UTF8
    }
}

# Validate input directory
if (-not (Test-Path -Path $unzipedDirectory -PathType Container)) {
    Log "ERROR" "Invalid input directory: $unzipedDirectory"
    exit 1
}

# Define output file for orphaned .json files
$outputFile = Join-Path -Path $scriptDirectory -ChildPath 'orphaned_json_files.txt'
Log "INFO" "Output will be saved to: $outputFile"

# Initialize collection
$orphanedJsonFiles = @()

# Get all .json files in target directory
$jsonFiles = Get-ChildItem -Path $unzipedDirectory -Recurse -Filter "*.json" -File
$totalItems = $jsonFiles.Count
$currentItem = 0

Log "INFO" "Scanning $totalItems .json files for orphaned entries..."

foreach ($jsonFile in $jsonFiles) {
    $currentItem++
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message "Scanning for Orphaned JSON"

    $sourceFileName = $jsonFile.BaseName
    $sourcePath = Join-Path -Path $jsonFile.DirectoryName -ChildPath $sourceFileName

    if (-not (Test-Path $sourcePath)) {
        $orphanedJsonFiles += $jsonFile.FullName
        Log "DEBUG" "Orphaned JSON detected: $($jsonFile.FullName)"
    }
}

# Write results
$orphanedJsonFiles | Out-File -FilePath $outputFile -Encoding UTF8
Log "INFO" "Found $($orphanedJsonFiles.Count) orphaned JSON files."
Log "INFO" "Wrote orphaned JSON list to '$outputFile'"
