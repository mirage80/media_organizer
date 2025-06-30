param(
    [Parameter(Mandatory=$true)]
    [string]$unzippedDirectory,
    [string]$step
)

$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

#Utils Dirctory
$UtilDirectory = Join-Path $scriptDirectory "..\Utils"
$UtilFile = Join-Path $UtilDirectory "Utils.psm1"
Import-Module $UtilFile -Force

# Define the log directory path once
$logDir = Join-Path $scriptDirectory "..\Logs"

# --- Centralized Logging Setup ---
try {
    $logFile = Join-Path $logDir -ChildPath $("Step_$step" + "_" + "$scriptName.log")
    Initialize-ChildScriptLogger -ChildLogFilePath $logFile
} catch {
    Write-Error "FATAL: Failed to initialize logger. Error: $_"
    exit 1
}

# Validate input directory
if (-not (Test-Path -Path $unzippedDirectory -PathType Container)) {
    Log "ERROR" "Invalid input directory: $unzippedDirectory"
    exit 1
}

# Define output file for orphaned .json files
$outputFile = Join-Path -Path $logDir -ChildPath 'Step4_orphaned_json_files.txt'
Log "INFO" "Output will be saved to: $outputFile"

# Initialize collection
$orphanedJsonFiles = @()

# Get all .json files in target directory
$jsonFiles = Get-ChildItem -Path $unzippedDirectory -Recurse -Filter "*.json" -File
$totalItems = $jsonFiles.Count
$currentItem = 0

Log "INFO" "Scanning $totalItems .json files for orphaned entries..."

foreach ($jsonFile in $jsonFiles) {
    $currentItem++
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message "OrphanJson"

    $sourceFileName = $jsonFile.BaseName
    $sourcePath = Join-Path -Path $jsonFile.DirectoryName -ChildPath $sourceFileName

    if (-not (Test-Path $sourcePath)) {
        $orphanedJsonFiles += $jsonFile.FullName
        Log "DEBUG" "Orphaned JSON detected: $($jsonFile.FullName)"
    }
}

function Purge 
{
    param (
        [string]$list_file
    )
    Get-Content -Path $list_file | ForEach-Object {
        $file = $_.Trim() # Remove any leading or trailing whitespace

        # Check if the file exists before attempting to delete it
        if (Test-Path -Path "$file" -PathType Leaf) {
            try {
                # Delete the file
                Remove-Item -Path "$file" -Force
            } catch {
                Log "WARNING" "Failed to delete '$file': $_"
            }
        } else {
            Log "WARNING" "File not found: $file"
        }
    }
}

# Write results
$orphanedJsonFiles | Out-File -FilePath $outputFile -Encoding UTF8
Purge -list_file $outputFile

Log "INFO" "Found $($orphanedJsonFiles.Count) orphaned JSON files."
Log "INFO" "Wrote orphaned JSON list to '$outputFile'"
