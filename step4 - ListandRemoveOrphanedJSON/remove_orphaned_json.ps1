param(
    [Parameter(Mandatory=$true)]
    [string]$unzipedDirectory,
    [string]$step
)

$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

#Outputs Dirctory
$OutputDirectory = Join-Path $scriptDirectory "..\Outputs"

#Utils Dirctory
$UtilDirectory = Join-Path $scriptDirectory "..\Utils"
$UtilFile = Join-Path $UtilDirectory "Utils.psm1"
Import-Module $UtilFile -Force

# --- Logging Setup ---
$logDir = Join-Path $scriptDirectory "..\Logs"
$logFile = Join-Path $logDir $("Step_$step" + "_" + "$scriptName.log")
$logFormat = "{0} - {1}: {2}"

# Create the log directory if it doesn't exist
if (-not (Test-Path $logDir)) {
    try {
        New-Item -ItemType Directory -Path $logDir -Force -ErrorAction Stop | Out-Null
    } catch {
        Write-Error "FATAL: Failed to create log directory '$logDir'. Aborting. Error: $_"
        exit 1
    }
}

# Deserialize the JSON back into a hashtable
$logLevelMap = $null
$logLevelMap = $env:LOG_LEVEL_MAP_JSON

if (-not [string]::IsNullOrWhiteSpace($logLevelMap)) {
    try {
        # --- FIX IS HERE ---
        # Use -AsHashtable to ensure the correct object type
        $logLevelMap = $logLevelMap | ConvertFrom-Json -AsHashtable -ErrorAction Stop
        # --- END FIX ---
    } catch {
        # Log a fatal error and exit immediately if deserialization fails
        Write-Error "FATAL: Failed to deserialize LOG_LEVEL_MAP_JSON environment variable. Check the variable's content is valid JSON. Aborting. Error: $_"
        exit 1
    }
}
if ($null -eq $logLevelMap) {
    # This case should ideally not happen if top.ps1 ran, but handle defensively
    Write-Error "FATAL: LOG_LEVEL_MAP_JSON environment variable not found or invalid. Aborting."
    exit 1
}

# Check if required environment variables are set (by top.ps1 or externally)
if ($null -eq $env:DEDUPLICATOR_CONSOLE_LOG_LEVEL) {
    Write-Error "FATAL: Environment variable DEDUPLICATOR_CONSOLE_LOG_LEVEL is not set. Run via top.ps1 or set externally. Aborting."
    exit 1
}
if ($null -eq $env:DEDUPLICATOR_FILE_LOG_LEVEL) {
    Write-Error "FATAL: Environment variable DEDUPLICATOR_FILE_LOG_LEVEL is not set. Run via top.ps1 or set externally. Aborting."
    exit 1
}

# Read the environment variables directly and trim whitespace (NOW SAFE)
$EffectiveConsoleLogLevelString = $env:DEDUPLICATOR_CONSOLE_LOG_LEVEL.Trim()
$EffectiveFileLogLevelString    = $env:DEDUPLICATOR_FILE_LOG_LEVEL.Trim()

# Look up the numeric level using the effective string and the map
$consoleLogLevel = $logLevelMap[$EffectiveConsoleLogLevelString.ToUpper()]
$fileLogLevel    = $logLevelMap[$EffectiveFileLogLevelString.ToUpper()]

# --- Validation for THIS script's levels ---
if ($null -eq $consoleLogLevel) {
    Write-Error "FATAL: Invalid Console Log Level specified ('$EffectiveConsoleLogLevelString'). Check environment variable or script default. Aborting."
    exit 1
}
if ($null -eq $fileLogLevel) {
    Write-Error "FATAL: Invalid File Log Level specified ('$EffectiveFileLogLevelString'). Check environment variable or script default. Aborting."
    exit 1
}

# --- Log Function Definition ---
function Log {
    param (
        [string]$Level,
        [string]$Message
    )
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $formatted = $logFormat -f $timestamp, $Level.ToUpper(), $Message
    $levelIndex = $logLevelMap[$Level.ToUpper()]

    if ($null -ne $levelIndex) {
        if ($levelIndex -ge $consoleLogLevel) {
            Write-Host $formatted
        }
        if ($levelIndex -ge $fileLogLevel) {
            try {
                Add-Content -Path $logFile -Value $formatted -Encoding UTF8 -ErrorAction Stop
            } catch {
                Write-Warning "Failed to write to log file '$logFile': $_"
            }
        }
    } else {
        Write-Warning "Invalid log level used: $Level"
    }
}

# Validate input directory
if (-not (Test-Path -Path $unzipedDirectory -PathType Container)) {
    Log "ERROR" "Invalid input directory: $unzipedDirectory"
    exit 1
}

# Define output file for orphaned .json files
$outputFile = Join-Path -Path $OutputDirectory -ChildPath 'orphaned_json_files.txt'
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
