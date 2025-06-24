param(
    [Parameter(Mandatory = $true)] [string]$magickPath,
    [Parameter(Mandatory = $true)] [string]$reconstructListPath,
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

# --- Script Setup ---
$MediaToolsFile = Join-Path $UtilDirectory 'MediaTools.psm1'
try {
    Import-Module $MediaToolsFile -Force
} catch {
    Log "CRITICAL" "Failed to import MediaTools module from '$MediaToolsFile'. Error: $_. Aborting."
    exit 1
}

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


# --- Helper Function for ImageMagick ---
function Invoke-Magick {
    param(
        [Parameter(Mandatory = $true)] [string]$InputPath,
        [Parameter(Mandatory = $true)] [string]$OutputPath,
        [Parameter(Mandatory = $true)] [string]$ImageMagick
    )

    if (-not (Test-Path -Path $ImageMagick -PathType Leaf)) {
        Log "ERROR" "ImageMagick executable not found: '$vlc'"
        return @{ Success = $false; Output = "Executable not found"; ExitCode = -1 }
    }

    if ($InputPath -eq $OutputPath) {
        Log "ERROR" "InputPath and OutputPath are the same. Cannot overwrite in-place."
        return @{ Success = $false; Output = "Input == Output"; ExitCode = -1 }
    }

    Log "DEBUG" "Calling ImageMagick:"
    Log "DEBUG" "  & `"$ImageMagick`" $($FfmpegArgs -join ' ')"
   
    try {
        $exitCode = & "$ImageMagick" $InputPath $OutputPath 
        $success = ($null -eq $exitCode)
        Log "DEBUG" "ffmpeg raw output:`n$output"

        if ($success -and -not (Test-Path $OutputPath)) {
            Log "ERROR" "ffmpeg exited with code 0 but did not create output file."
            $success = $false
        }

        if ($success) {
            Log "INFO" "ffmpeg succeeded for '$InputPath' → '$OutputPath'"
        } else {
            Log "WARNING" "ImageMagick failed for '$InputPath' with exit code $exitCode."
            Log "DEBUG" "ImageMagick Output:`n$fullOutput"
            return @{ Success = $false; Output = $fullOutput }
        }

        return @{
            Success  = $success
            ExitCode = $exitCode
            Output   = $output -join "`n"
        }

    } catch {
        $errorMessage = $_.Exception.Message
        Log "ERROR" "Exception running ffmpeg: $errorMessage"
        return @{
            Success  = $false
            ExitCode = -1
            Output   = "EXCEPTION: $errorMessage"
        }
    }
}

# --- Load and Deduplicate List ---
$imagesToReconstruct = @()
if (Test-Path -Path $reconstructListPath -PathType Leaf) {
    try {
        $imagesToReconstruct = Get-Content -Path $reconstructListPath -Raw | ConvertFrom-Json
        if ($null -eq $imagesToReconstruct) { $imagesToReconstruct = @() } # Handle empty JSON file
        Log "INFO" "Loaded $($imagesToReconstruct.Count) images marked for reconstruction from '$reconstructListPath'."
    } catch {
        Log "ERROR" "Failed to read or parse '$reconstructListPath': $_. Aborting reconstruction."
        exit 1
    }
} else {
    Log "INFO" "Reconstruction list '$reconstructListPath' not found. No images to reconstruct."
    exit 0
}

# --- Deduplication Fix ---
$imagesToReconstruct = $imagesToReconstruct | Select-Object -Unique
Log "DEBUG" "Deduplicated input list:`n$($imagesToReconstruct -join "`n")"

if ($imagesToReconstruct.Count -eq 0) {
    Log "INFO" "Reconstruction list is empty. Nothing to do."
    exit 0
}

$totalItems = $imagesToReconstruct.Count
$currentItem = 0
$successCount = 0
$failCount = 0
$successfullyReconstructed = [System.Collections.Generic.List[string]]::new()

# Process each image
foreach ($imagePath in $imagesToReconstruct) {
    $currentItem++
    $baseName = Split-Path $imagePath -Leaf
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message "Reconstructing: $baseName"

    if (-not (Test-Path $imagePath)) {
        Log "WARNING" "Missing: '$imagePath'. Skipping."
        $failCount++
        continue
    }

    # Define temporary output path
    $tempOutputPath = "$imagePath.repaired.jpg"

    # Attempt reconstruction (re-muxing)
													 
    $result = Invoke-Magick -InputPath $imagePath -OutputPath $tempOutputPath -ImageMagick $magickPath
    if (-not $result.Success) {
        Log "ERROR" "vlc failed for '$baseName'. Output:"
        Log "ERROR" $result.Output
    }
    if ($result.Success) {
        $isValidOutput = $false
        try {
            Log "DEBUG" "Verifying re-muxed output: $tempOutputPath"
            $identifyOutput = & $magickPath identify "$tempOutputPath" 2>&1
            if ($LASTEXITCODE -eq 0) {
                Log "DEBUG" "Verification successful for '$tempOutputPath'."
                $isValidOutput = $true
            } else {
                Log "WARNING" "ImageMagick identify verification failed for '$tempOutputPath'. Exit code: $LASTEXITCODE."
                Log "DEBUG" "ImageMagick identify Output/Error:`n$identifyOutput"
            }
        } catch {
            Log "WARNING" "Error during ffprobe verification for '$tempOutputPath': $_"
        }

        # Verify temp file exists and has size before replacing original
        if ($isValidOutput -and (Test-Path $tempOutputPath) -and ((Get-Item $tempOutputPath).Length -gt 0)) {
            Log "INFO" "Successfully re-muxed '$baseName'."
            $backupPath = "$imagePath.bak"
            try {
                # 1. Rename original to backup
                Rename-Item $imagePath $backupPath -Force -ErrorAction Stop
                Log "DEBUG" "Renamed original '$imagePath' to '$backupPath'."
                # 2. Rename temp file to original name
                Rename-Item $tempOutputPath $imagePath -Force -ErrorAction Stop
                Log "INFO" "Replaced original with re-muxed version: '$imagePath'"

                # 3. If successful, remove backup
                Remove-Item -Path $backupPath -Force -ErrorAction SilentlyContinue
                Log "DEBUG" "Removed backup file '$backupPath'."
            
                $successfullyReconstructed.Add($imagePath)
                $successCount++
            } catch {
                Log "ERROR" "Failed during replacement process for '$imagePath'. Error: $_"
                # Attempt rollback if possible
                if ((Test-Path $backupPath) -and -not (Test-Path $imagePath)) {
                    Log "INFO" "Attempting to restore original from backup '$backupPath'..."
                    Rename-Item $backupPath $imagePath -Force
                }
                # Clean up temp file if it still exists
                if (Test-Path $tempOutputPath) { Remove-Item $tempOutputPath -Force -ErrorAction SilentlyContinue }
                $failCount++
            }
        } else {
            Log "ERROR" "Re-muxing seemed successful for '$baseName', but output file '$tempOutputPath' is missing or empty."
            if (Test-Path $tempOutputPath) { Remove-Item $tempOutputPath -Force -ErrorAction SilentlyContinue } # Clean up invalid temp file
            $failCount++
        }
    } else {
        Log "ERROR" "Failed to reconstruct '$baseName'."
        # Clean up failed temp file
        if (Test-Path $tempOutputPath) {
            Remove-Item $tempOutputPath -Force -ErrorAction SilentlyContinue
        }
        $failCount++
    }
}

Write-Host # Clear progress bar line

# --- Update JSON List ---
Log "INFO" "Updating reconstruction list..."
# Filter out successfully reconstructed images
$remainingImages = @($imagesToReconstruct | Where-Object { $successfullyReconstructed -notcontains $_ })
if ($null -eq $remainingImages) {
    $remainingImages = @()  # ensure it's always an array
}
Log "INFO" "Updated reconstruction list: $($remainingImages.Count) remaining."
Log "INFO" "Summary: Success=$successCount, Failed=$failCount"
