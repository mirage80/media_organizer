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

# --- Centralized Logging Setup ---
try {
    $logFile = Join-Path $scriptDirectory "..\Logs" -ChildPath $("Step_$step" + "_" + "$scriptName.log")
    Initialize-ChildScriptLogger -ChildLogFilePath $logFile
} catch {
    Write-Error "FATAL: Failed to initialize logger. Error: $_"
    exit 1
}

# Validate the parameters.
if (-not $unzippedDirectory) {
    New-Item -ItemType Directory -Path $unzippedDirectory -Force | Out-Null
}

# Get all zip files in the directory.
$zipFiles = Get-ChildItem -Path $zipDirectory -recurse -Filter "*.zip" -File

$currentItem = 0
$totalItems = $zipFiles.count
# Loop through each zip file and extract its contents.
foreach ($zipFile in $zipFiles) {
    # Extract the contents of the zip file to the temporary directory.
    $currentItem++
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message "extracting"
	& "$extractor" x -aos "$zipFile" "-o$unzippedDirectory" | Out-Null
} 