param(
    [Parameter(Mandatory=$true)]
    [string]$unzipedDirectory,
    [string]$ExifToolPath
)

$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

# --- Logging Setup ---
$logDir = Join-Path $scriptDirectory "..\Logs"
$logFile = Join-Path $logDir "$scriptName.log"
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

# --- Show-ProgressBar Function Definition ---
function Show-ProgressBar {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Current,

        [Parameter(Mandatory = $true)]
        [int]$Total,

        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    # Check if running in a host that supports progress bars
    if ($null -eq $Host.UI.RawUI) {
        # Fallback for non-interactive environments or simplified hosts
        $percent = 0; 
        if ($Total -gt 0) { 
            $percent = [math]::Round(($Current / $Total) * 100) 
        }
        Write-Host "$Message Progress: $percent% ($Current/$Total)"
        return
    }
    try {
        $percent = [math]::Round(($Current / $Total) * 100)
        $screenWidth = $Host.UI.RawUI.WindowSize.Width - 30
        $barLength = [math]::Min($screenWidth, 80)
        $filledLength = [math]::Round(($barLength * $percent) / 100)
        $emptyLength = $barLength - $filledLength
        $filledBar = ('=' * $filledLength)
        $emptyBar = (' ' * $emptyLength)
        Write-Host -NoNewline "$Message [$filledBar$emptyBar] $percent% ($Current/$Total)`r"
    } catch {
        $percent = 0; if ($Total -gt 0) { $percent = [math]::Round(($Current / $Total) * 100) }
        Write-Host "$Message Progress: $percent% ($Current/$Total)"
    }
}
# --- End Show-ProgressBar Function Definition ---

function Write-JsonAtomic {
    param (
        [Parameter(Mandatory = $true)][object]$Data,
        [Parameter(Mandatory = $true)][string]$Path
    )

    try {
        $tempPath = "$Path.tmp"
        $json = $Data | ConvertTo-Json -Depth 10
        $json | Out-File -FilePath $tempPath -Encoding UTF8 -Force

        # Validate JSON before replacing
        $null = Get-Content $tempPath -Raw | ConvertFrom-Json

        Move-Item -Path $tempPath -Destination $Path -Force
        Log "INFO" "✅ Atomic write succeeded: $Path"
    } catch {
        Log "ERROR" "❌ Atomic write failed for $Path : $_"
        if (Test-Path $tempPath) {
            Remove-Item $tempPath -Force -ErrorAction SilentlyContinue
        }
    }
}

Import-Module (Join-Path $scriptDirectory "..\step6 - Consolidate_Meta\MediaTools.psm1") -Force

#===========================================================
#                 Categorization functions
#===========================================================
function Categorize_Media_Based_On_Metadata {
    param (
        [System.IO.FileInfo]$SrcFile
    )
    $timestamp = IsValid_TimeStamp -timestamp_in $(Get_Exif_Timestamp -File $SrcFile)
    $geotag = IsValid_GeoTag -GeoTag $(Get_Exif_Geotag -File $SrcFile)

    if ($timestamp -and $geotag) {
        return "with_time_with_geo"
    } elseif ($timestamp -and -not $geotag) {
        return "with_time_no_geo"
    } elseif (-not $timestamp -and $geotag) {
        return "no_time_with_geo"
    } else {
        return "no_time_no_geo"
    }
}

function categorize_bulk_media_based_on_metadata_keep_directory_structure {
    param (
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$filePath,

        [Parameter(Mandatory = $true)]
        [System.IO.DirectoryInfo]$rootDir,

        [Parameter(Mandatory = $true)]
        [System.IO.DirectoryInfo]$targetPath
    )
    $category = Categorize_Media_Based_On_Metadata -SrcFile $filePath
    $newroot = Join-Path -Path $targetPath -ChildPath $category

    $relativePath = $filePath -replace [regex]::Escape($rootDir), ""
    $destination = Join-Path -Path $newRoot -ChildPath $relativePath
    $desiredPath = Split-Path -Path $destination
    New-Item -Path $desiredPath -ItemType Directory -Force | Out-Null

    Move-Item -Path $filePath.FullName -Destination $destination
    Verbose -message "Moved $($filePath.FullName) to $category" -type "information"
}

#===========================================================
#                 Main functions
#===========================================================
# Create src and dst subdirectories if they don't exist
$srcDirectory = New-Item -Path "$unzippeddirectory\src" -ItemType Directory -Force
$dstDirectory = New-Item -Path "$unzippeddirectory\dst" -ItemType Directory -Force

# Move ONLY the target media files into the src directory
Log "INFO" "Moving target media files (.jpg, .mp4) to $($srcDirectory.FullName)..."
Get-ChildItem -Path $unzippeddirectory -File | Where-Object { $module:imageExtensions -contains $_.Extension -or $module:videoExtensions -contains $_.Extension } | Move-Item -Destination $srcDirectory.FullName -Force
Log "INFO" "Finished moving target media files."

$files = Get-ChildItem -Path $srcDirectory.FullName -Recurse -File
$currentItem = 0
$totalItems = $files.count

# Process files in the src directory
foreach ($file in $files) {
    if ((is_photo -file $file) -or (is_video -file $file)) {
        $currentItem++
        Show-ProgressBar -Current $currentItem -Total $totalItems -Message "$zipFile"

        categorize_bulk_media_based_on_metadata_keep_directory_structure `
            -filePath $file `
            -rootDir $srcDirectory `
            -targetPath $dstDirectory
    }
}

# Check if the src directory is empty
$remainingItems = Get-ChildItem -Path $srcDirectory.FullName -Recurse
if ($remainingItems) {
    Log "WARNING" "Source directory '$($srcDirectory.FullName)' was NOT empty after processing. This might indicate non-media files were present or an error occurred."
    $remainingItems | ForEach-Object { Log "WARNING" "- Remaining item: $($_.FullName)" }
} else {
    Log "INFO" "Source directory '$($srcDirectory.FullName)' is empty as expected."
    # Remove the now-empty src directory itself
    Remove-Item -Path $srcDirectory.FullName -Force -ErrorAction SilentlyContinue
}

# --- Move categorized content from dst back to the root ---
Log "INFO" "Moving categorized folders from '$($dstDirectory.FullName)' back to '$unzippedDirectory'..."

# Get the category folders inside 'dst'
$categoryFolders = Get-ChildItem -Path $dstDirectory.FullName -Directory -ErrorAction SilentlyContinue

if ($categoryFolders) {
    foreach ($folder in $categoryFolders) {
        $destinationPath = Join-Path -Path $unzippedDirectory -ChildPath $folder.Name
        Log "INFO" "Moving '$($folder.FullName)' to '$unzippedDirectory' (will become '$destinationPath')..."
        try {
            # Move the category folder itself up one level
            Move-Item -Path $folder.FullName -Destination $unzippedDirectory -Force
        } catch {
            Log "ERROR" "Failed to move '$($folder.FullName)': $_"
        }
    }

    # --- Clean up the now empty dst directory ---
    Log "INFO" "Cleaning up the empty destination directory: $($dstDirectory.FullName)"
    try {
        # Optional: Verify it's truly empty before removing
        if (-not (Get-ChildItem -Path $dstDirectory.FullName -ErrorAction SilentlyContinue)) {
            Remove-Item -Path $dstDirectory.FullName -Force
            Log "INFO" "Successfully removed empty destination directory."
        } else {
             Log "WARNING" "Destination directory '$($dstDirectory.FullName)' was not empty after moving category folders. Manual cleanup might be required."
        }
    } catch {
        Log "ERROR" "Failed to remove destination directory '$($dstDirectory.FullName)': $_"
    }
} else {
    Log "WARNING" "No category folders found in '$($dstDirectory.FullName)' to move. The 'dst' directory might be empty or categorization failed."
    # Optionally remove the empty dst directory even if no category folders were found
    try {
        if (Test-Path $dstDirectory.FullName -PathType Container) {
             Remove-Item -Path $dstDirectory.FullName -Force -ErrorAction SilentlyContinue
             Log "INFO" "Removed potentially empty destination directory."
        }
    } catch {
         Log "ERROR" "Failed to remove destination directory '$($dstDirectory.FullName)' even though no category folders were found: $_"
    }
}

# Correct the final log message
Log "INFO" "Categorization and final move complete."