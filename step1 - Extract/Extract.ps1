param(
    [Parameter(Mandatory=$true)]
    [string]$unzippedDirectory,
    [string]$zippedDirectory,
    [string]$extractor,
    [string]$step
)

$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

#Utils Dirctory
$UtilDirectory = Join-Path $scriptDirectory "..\Utils"
$UtilFile = Join-Path $UtilDirectory "Utils.psm1"
Import-Module $UtilFile -Force

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

# 4. Write initial log message to ensure file creation
& $Log "INFO" "--- Script Started: $scriptName ---"

# --- Robust Parameter Validation ---
if (-not (Test-Path -Path $unzippedDirectory -PathType Container)) {
    & $Log "INFO" "Output directory '$unzippedDirectory' does not exist. Creating it."
    try {
        New-Item -ItemType Directory -Path $unzippedDirectory -Force -ErrorAction Stop | Out-Null
    } catch {
        & $Log "CRITICAL" "Failed to create output directory '$unzippedDirectory'. Error: $_. Aborting."
        exit 1
    }
}

if (-not (Test-Path -Path $zippedDirectory -PathType Container)) {
    & $Log "CRITICAL" "Input directory with zip files '$zippedDirectory' does not exist. Aborting."
    exit 1
}

if (-not (Test-Path -Path $extractor -PathType Leaf)) {
    & $Log "CRITICAL" "7-Zip executable not found at '$extractor'. Aborting."
    exit 1
}

# Get all zip files in the directory.
$zipFiles = Get-ChildItem -Path $zippedDirectory -recurse -Filter "*.zip" -File

if ($null -eq $zipFiles -or $zipFiles.Count -eq 0) {
    & $Log "INFO" "No .zip files found in '$zippedDirectory'. Nothing to extract."
    exit 0 # Exit gracefully
}

$currentItem = 0
$totalItems = $zipFiles.count
# Loop through each zip file and extract its contents.
foreach ($zipFile in $zipFiles) {
    $currentItem++
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message "Extracting: $($zipFile.Name)"
    try {
        # Use -bsp1 to redirect progress output, and 2>&1 to capture stderr
        $output = & "$extractor" x -aos "$zipFile" "-o$unzippedDirectory" -bsp1 2>&1
        if ($LASTEXITCODE -ne 0) { throw "7-Zip failed with exit code $LASTEXITCODE. Output: $($output -join "`n")" }
        & $Log "DEBUG" "Successfully extracted $($zipFile.FullName)"
    } catch {
        & $Log "ERROR" "Failed to extract '$($zipFile.FullName)'. Error: $_"
    }
} 