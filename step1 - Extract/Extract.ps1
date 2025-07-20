param(
    [Parameter(Mandatory=$true)]
    [string]$unzippedDirectory,
    [Parameter(Mandatory=$true)]
    [string]$zippedDirectory,
    [Parameter(Mandatory=$true)]
    [string]$extractor,
    [Parameter(Mandatory=$true)]
    [string]$step
)

# --- Path Setup ---
$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

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

# Inject logger for module functions
Set-UtilsLogger -Logger $Log
Set-MediaToolsLogger -Logger $Log

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

if ($unzippedDirectory -like '* *') {
    & $Log "CRITICAL" "The configured output directory path for extraction ('$unzippedDirectory') contains spaces. This is not supported. Please use a path without spaces."
    Stop-GraphicalProgressBar
    exit 1
}

# Get all zip files in the directory.
$zipFiles = Get-ChildItem -Path $zippedDirectory -recurse -Filter "*.zip" -File

if ($null -eq $zipFiles -or $zipFiles.Count -eq 0) {
    & $Log "INFO" "No .zip files found in '$zippedDirectory'. Nothing to extract."
ee3e6800-8f13-410f-864f-68b59ba97c43    exit 0 # Exit gracefully
}

$currentItem = 0
$totalItems = $zipFiles.count
# Loop through each zip file and extract its contents.
foreach ($zipFile in $zipFiles) {
    $currentItem++
    $percent = if ($totalItems -gt 0) { [int](($currentItem / $totalItems) * 100) } else { 100 }

    Update-GraphicalProgressBar -SubTaskPercent $percent -SubTaskMessage  "Extracting: $($zipFile.Name)"
    try {
        # 7-Zip Arguments:
        #   x: Extract with full paths
        #   -aos: Skip Over Existing files (prevents re-extracting everything on a re-run)
        #   -o: Set Output directory (no space between -o and path)
        #   -bsp1: Redirect progress output to stdout for capture
        $7zipArgs = "x", "-aos", $zipFile.FullName, "-o$unzippedDirectory", "-bsp1"
        
        # Execute 7-Zip and capture all output (stdout and stderr)
        $output = & $extractor $7zipArgs 2>&1
        if ($LASTEXITCODE -ne 0) { throw "7-Zip failed with exit code $LASTEXITCODE. Output: $($output -join [System.Environment]::NewLine)" }
        & $Log "DEBUG" "Successfully extracted $($zipFile.FullName)"
    } catch {
        & $Log "ERROR" "Failed to extract '$($zipFile.FullName)'. Error: $_"
    }
} 