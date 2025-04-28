param(
    [Parameter(Mandatory=$true)]
    [string]$unzipedDirectory,
    [string]$step
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

function Use-ValidDirectoryName {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DirectoryPath
    )

    # Check if the path is a drive root (e.g., "C:\")
    if ($DirectoryPath -match "^[a-zA-Z]:$") {
        return  # Exit the function without doing anything
    }
    
    $item = $null # Initialize $item
    $originalName = ''
    $parentPath = ''
    $sanitizedName = ''
    $newPath = ''

    try {
        $item = Get-Item -Path $DirectoryPath -ErrorAction Stop # Ensure item exists before proceeding
        $originalName = $item.Name.Trim()
        $parentPath = $item.Parent.FullName

        # --- Sanitization Logic ---
        # Allow word characters (alphanumeric + underscore), hyphen, and period. Replace others with underscore.
        $sanitizedName = $originalName -replace '[^\w\-.]+', '_'
        $sanitizedName = $sanitizedName -replace '__+','_'       # Collapse multiple underscores
        $sanitizedName = $sanitizedName -replace '^_|_$',''      # Remove leading/trailing underscores AFTER collapsing

        # Add check for empty name after sanitization
        if ([string]::IsNullOrWhiteSpace($sanitizedName)) {
            Log "WARNING" "Skipping rename of '$originalName' in '$parentPath' because sanitized name is empty."
            return
        }
        # --- End Sanitization ---
        if ($originalName -ne $sanitizedName) {
            $newPath = Join-Path -Path $parentPath -ChildPath $sanitizedName

            # --- Attempt Rename using Move-Item with -Force ---
            # Move-Item with -Force handles overwriting existing items at the destination path.
            Log "INFO" "Attempting to rename '$originalName' to '$sanitizedName' in '$parentPath' (will overwrite if target exists)."
            Move-Item -Path $item.FullName -Destination $newPath -Force -ErrorAction Stop
            Log "INFO" "Successfully renamed '$originalName' to '$sanitizedName' (now at '$newPath')."

        } else {
             Log "DEBUG" "Name '$originalName' in '$parentPath' is already sanitized."
        }
    } catch {
        # Log detailed error information
        $errorMessage = "Failed to process or rename path '$DirectoryPath'."
        if ($item) { # If we managed to get the item
            $errorMessage += " Original name: '$originalName'."
            if ($originalName -ne $sanitizedName) {
                 $errorMessage += " Target name: '$sanitizedName'. Target path: '$newPath'."
            }
        }
        # Check if it's a specific 'item already exists' error that Move-Item -Force should have handled but didn't (e.g., permissions)
        if ($_.Exception.Message -match 'Cannot create a file when that file already exists') {
             $errorMessage += " (Move-Item -Force might have failed due to permissions or item being in use)."
        }
        $errorMessage += " Error details: $($_.Exception.Message)"
        Log "WARNING" $errorMessage
        # Optionally log the full error record for debugging
        # Log "DEBUG" "Full error record: $_"
    }
}

function Use-ValidDirectoriesRecursively {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RootDirectory
    )

    if (-not (Test-Path -Path $RootDirectory -PathType Container)) {
        Log "ERROR" "Root directory '$RootDirectory' does not exist."
        return
    }

    $directories = Get-ChildItem -Path $RootDirectory -Directory -Recurse -ErrorAction SilentlyContinue
    $sortedDirectories = $directories | Sort-Object @{Expression = { $_.FullName.Length }} -Descending

    # Process the sorted directories (deepest first)
    foreach ($directory in $sortedDirectories) {
        Use-ValidDirectoryName -DirectoryPath $directory.FullName
    }

    # Finally, sanitize the root directory itself after all children are done
    Use-ValidDirectoryName -DirectoryPath $RootDirectory
}

Use-ValidDirectoriesRecursively -RootDirectory $unzipedDirectory
