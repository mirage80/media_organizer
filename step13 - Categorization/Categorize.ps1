param(
    [Parameter(Mandatory=$true)]
    [string]$unzippedDirectory,
    [string]$ExifToolPath,
    [Parameter(Mandatory = $true)] [string]$step
)

$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

#Utils Dirctory
$UtilDirectory = Join-Path $scriptDirectory "..\Utils"
$UtilFile = Join-Path $UtilDirectory "Utils.psm1"
Import-Module $UtilFile -Force

# --- Logging Setup ---
$logDir = Join-Path $scriptDirectory "..\Logs"
$logFile = Join-Path $logDir $("Step_$step" + "_" + "$scriptName.log")
$logFormat = "{0} - {1}: {2}"

function Get-ProcessedLog {
    param (
        [Parameter(Mandatory = $true)]
        [string]$LogPath
    )
    if (Test-Path $LogPath) {
        return Get-Content $LogPath -Raw | ConvertFrom-Json
    } else {
        return @()
    }
}

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
        $logLevelMap = $logLevelMap | ConvertFrom-Json -AsHashtable
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

# --- Script Setup ---
$MediaToolsFile = Join-Path $UtilDirectory 'MediaTools.psm1'
try {
    Import-Module $MediaToolsFile -Force
} catch {
    Log "CRITICAL" "Failed to import MediaTools module from '$MediaToolsFile'. Error: $_. Aborting."
    exit 1
}

# Define Image and Video extensions (these are from MediaTools.psm1 and are available after import)
$imageExtensions = $imageExtensions
$videoExtensions = $videoExtensions

$hashLogPath = Join-Path $scriptDirectory "consolidation_log.json"  # << This line must come BEFORE functions

Log "INFO" "Attempting to load processed log from '$hashLogPath'..." # ADD
try {
    $processedLog = Get-ProcessedLog -LogPath $hashLogPath -ErrorAction Stop # Add ErrorAction
    Log "INFO" "Successfully loaded $($processedLog.Count) initial entries from '$hashLogPath'." # ADD
} catch {
    Log "INFO" "Failed to load or parse processed log '$hashLogPath': $_" # ADD
    # Decide how to proceed - maybe exit or start with empty?
    $processedLog = @() # Start with empty if loading failed
}

# Build a fast lookup hash set from the initial log
$processedSet = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
$processedLog | ForEach-Object {
    if ($_.path) { [void]$processedSet.Add($_.path) }
}
Log "INFO" "Loaded $($processedSet.Count) paths from initial log '$hashLogPath'."




#===========================================================
#                 Main functions
#===========================================================
# Create a destination directory for categorized files
$dstDirectory = New-Item -Path "$unzippedDirectory\dst" -ItemType Directory -Force

Log "INFO" "Scanning for media files in '$unzippedDirectory'..."
# Get all media files recursively and make the extension check case-insensitive.
$files = Get-ChildItem -Path $unzippedDirectory -Recurse -File | Where-Object {
    $ext = $_.Extension.ToLower()
    $imageExtensions -contains $ext -or $videoExtensions -contains $ext
}

if (-not $files) {
    Log "WARNING" "No media files found to categorize in '$unzippedDirectory'."
    # Clean up the empty dst directory and exit gracefully
    Remove-Item -Path $dstDirectory.FullName -Force -ErrorAction SilentlyContinue
    exit 0
}

$currentItem = 0
$totalItems = $files.count
Log "INFO" "Found $totalItems media files to categorize."
$runspaces = @()

$totalItems = $files.Count
$runspacePool = [RunspaceFactory]::CreateRunspacePool(1, 20)
$runspacePool.Open()
$UtilDirectory = Join-Path $scriptDirectory "..\Utils"
$progressFile = Join-Path $env:TEMP "categorize_progress_$PID.txt"
if (Test-Path $progressFile) { Remove-Item $progressFile }

foreach ($file in $files) {
    $ps = [PowerShell]::Create()
    $ps.AddScript({
        param(
            $filePathStr, $rootDirStr, $targetPathStr, $progressFile, $utilDir,
            $logFile, $logFormat, $logLevelMap, $consoleLogLevel, $fileLogLevel,
            $ExifToolPath
        )


            $script:logFile = $logFile
            $script:logFormat = $logFormat
            $script:logLevelMap = $logLevelMap
            $script:consoleLogLevel = $consoleLogLevel
            $script:fileLogLevel = $fileLogLevel
            $script:ExifToolPath = $ExifToolPath

        try {

            $utilsPath = Join-Path $utilDir 'Utils.psm1'
            $mediaPath = Join-Path $utilDir 'MediaTools.psm1'
            Import-Module $utilsPath -Force
            Import-Module $mediaPath -Force


            # Log start of categorization
            Log "INFO" "THREAD START $filePathStr"

            $filePath = Get-Item $filePathStr
            $rootDir = Get-Item $rootDirStr
            $targetPath = Get-Item $targetPathStr

            Log "INFO" "Categorizing $filePathStr"

            categorize_bulk_media_based_on_metadata_keep_directory_structure `
                -filePath $filePath `
                -rootDir $rootDir `
                -targetPath $targetPath

            # Log success
            Log "INFO" "Moved $($filePath.FullName) to $category"
        } catch {
            Log "ERROR" "Thread failed for $filePathStr : $_"
        } finally {
            Log "DEBUG"  "THREAD END $filePathStr" 
            Add-Content -Path $progressFile -Value $filePathStr
        }
    }) | Out-Null
    $ps.AddArgument($file.FullName) | Out-Null
    $ps.AddArgument($unzippedDirectory) | Out-Null
    $ps.AddArgument($dstDirectory) | Out-Null
    $ps.AddArgument($progressFile) | Out-Null
    $ps.AddArgument($UtilDirectory) | Out-Null
    $ps.AddArgument($logFile) | Out-Null
    $ps.AddArgument($logFormat) | Out-Null
    $ps.AddArgument($logLevelMap) | Out-Null
    $ps.AddArgument($consoleLogLevel) | Out-Null
    $ps.AddArgument($fileLogLevel) | Out-Null
    $ps.AddArgument($ExifToolPath) | Out-Null
    $ps.RunspacePool = $runspacePool
    $runspaces += [PSCustomObject]@{ Pipe = $ps; Handle = $ps.BeginInvoke() }
}


$currentItem = 0
$lastProgress = -1
$waitCounter = 0

while ($currentItem -lt $totalItems) {
    Start-Sleep -Milliseconds 100
while ((Get-Content $progressFile -ErrorAction SilentlyContinue).Count -gt $currentItem) {
        $currentItem++
        Show-ProgressBar -Current $currentItem -Total $totalItems -Message "Categorizing $currentItem of $totalItems"
        $waitCounter = 0
    }

    if ($lastProgress -eq $currentItem) {
        $waitCounter++
    } else {
        $lastProgress = $currentItem
        $waitCounter = 0
    }

    if ($waitCounter -gt 100) {
        Write-Warning "No progress in 10 seconds. Thread(s) might be stalled."
        break
    }
}

# Clean up runspaces
foreach ($rs in $runspaces) {
    $rs.Pipe.EndInvoke($rs.Handle)
    $rs.Pipe.Dispose()
}
$runspacePool.Close()
$runspacePool.Dispose()

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