param(
    [Parameter(Mandatory = $true)] [string]$ffmpeg,
    [Parameter(Mandatory = $true)] [string]$ffprobe,
    [Parameter(Mandatory = $true)] [string]$vlcpath,
    [Parameter(Mandatory = $true)] [string]$reconstructListPath
)

$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

$UtilDirectory = Join-Path $scriptDirectory "..\Utils"
$UtilFile = Join-Path $UtilDirectory "Utils.psm1"
Import-Module $UtilFile -Force

$logDir = Join-Path $scriptDirectory "..\Logs"
$logFile = Join-Path $logDir "$scriptName.log"
$logFormat = "{0} - {1}: {2}"

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

if (-not (Test-Path -Path $magickPath -PathType Leaf)) {
    Log "CRITICAL" "Magick executable not found at specified path: '$magickPath'. Aborting."
    exit 1
}

# --- Helper Function for FFmpeg ---
function Invoke-Ffmpeg {
    param(
        [Parameter(Mandatory = $true)] [string]$InputPath,
        [Parameter(Mandatory = $true)] [string]$OutputPath,
        [Parameter(Mandatory = $true)] [string]$ffmpeg,
        [Parameter(Mandatory = $true)] [string]$vertical,
        [Parameter(Mandatory = $true)] [string]$ab
    )

    if (-not (Test-Path -Path $ffmpeg -PathType Leaf)) {
        Log "ERROR" "Ffmpeg executable not found: '$vlc'"
        return @{ Success = $false; Output = "Executable not found"; ExitCode = -1 }
    }

    if ($InputPath -eq $OutputPath) {
        Log "ERROR" "InputPath and OutputPath are the same. Cannot overwrite in-place."
        return @{ Success = $false; Output = "Input == Output"; ExitCode = -1 }
    }

    Log "DEBUG" "Calling ffmpeg:"
    Log "DEBUG" "  & `"$ffmpeg`" $($FfmpegArgs -join ' ')"
   
    try {
        $exitCode = & "$ffmpeg" -i $InputPath -c:v libx264 -b:v $vertical"k" -c:a aac -b:a $ab"k" -ac 2 -ar 44100 -loglevel error -y $OutputPath 
        $success = ($null -eq $exitCode)
        Log "DEBUG" "VLC raw output:`n$output"

        if ($success -and -not (Test-Path $OutputPath)) {
            Log "ERROR" "VLC exited with code 0 but did not create output file."
            $success = $false
        }

        if ($success) {
            Log "INFO" "VLC succeeded for '$InputPath' → '$OutputPath'"
        } else {
            Log "WARNING" "ffmpeg failed for '$InputPath' with exit code $exitCode."
            Log "DEBUG" "ffmpeg Output:`n$fullOutput"
            return @{ Success = $false; Output = $fullOutput }
        }

        return @{
            Success  = $success
            ExitCode = $exitCode
            Output   = $output -join "`n"
        }

    } catch {
        $errorMessage = $_.Exception.Message
        Log "ERROR" "Exception running VLC: $errorMessage"
        return @{
            Success  = $false
            ExitCode = -1
            Output   = "EXCEPTION: $errorMessage"
        }
    }
}

function Get-BitrateByResolution {
    param (
        [string]$ffprobe,
        [string]$InputPath
    )

    $probe = & $ffprobe -v error -select_streams v:0 `
        -show_entries stream=width,height `
        -of csv=p=0 "$InputPath" 2>&1

    if (-not $probe -or $LASTEXITCODE -ne 0) {
        Log "WARN" "Failed to extract resolution from '$InputPath'. Defaulting to 1200/128."
        return @{ vb = 1200; ab = 128 }
    }

    $width, $height = $probe -split ','
    $width = [int]$width
    $height = [int]$height

    if ($width -le 640 -and $height -le 360) {
        return @{ vb = 600; ab = 96 }
    } elseif ($width -le 1280 -and $height -le 720) {
        return @{ vb = 1200; ab = 128 }
    } elseif ($width -le 1920 -and $height -le 1080) {
        return @{ vb = 2000; ab = 160 }
    } else {
        return @{ vb = 3000; ab = 192 }
    }
}

# --- Load and Deduplicate List ---
$videosToReconstruct = @()
if (Test-Path -Path $reconstructListPath -PathType Leaf) {
    try {
        $videosToReconstruct = Get-Content $reconstructListPath -Raw | ConvertFrom-Json
        if ($null -eq $videosToReconstruct) { $videosToReconstruct = @() } # Handle empty JSON file
        Log "INFO" "Loaded $($videosToReconstruct.Count) videos marked for reconstruction from '$reconstructListPath'."
    } catch {
        Log "ERROR" "Failed to read or parse '$reconstructListPath': $_. Aborting reconstruction."
        exit 1
    }
} else {
    Log "INFO" "Reconstruction list '$reconstructListPath' not found. No videos to reconstruct."
    exit 0
}

# --- Deduplication Fix ---
$videosToReconstruct = $videosToReconstruct | Select-Object -Unique
Log "DEBUG" "Deduplicated input list:`n$($videosToReconstruct -join "`n")"

if ($videosToReconstruct.Count -eq 0) {
    Log "INFO" "Reconstruction list is empty. Nothing to do."
    exit 0
}

$totalItems = $videosToReconstruct.Count
$currentItem = 0
$successCount = 0
$failCount = 0
$successfullyReconstructed = [System.Collections.Generic.List[string]]::new()

# Process each video
foreach ($videoPath in $videosToReconstruct) {
    $currentItem++
    $baseName = Split-Path $videoPath -Leaf
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message "Reconstructing: $baseName"

    if (-not (Test-Path $videoPath)) {
        Log "WARNING" "Missing: '$videoPath'. Skipping."
        $failCount++
        continue
    }

    # Define temporary output path
    $tempOutputPath = "$videoPath.repaired.mp4"
    $rates = Get-BitrateByResolution -ffprobe $ffprobe -InputPath $videoPath
    $vb = $rates.vb
    $ab = $rates.ab
    $result = Invoke-Ffmpeg -InputPath $videoPath -OutputPath $tempOutputPath -ffmpeg $ffmpeg -vertical $vb -ab $ab 
    if (-not $result.Success) {
        Log "ERROR" "vlc failed for '$baseName'. Output:"
        Log "ERROR" $result.Output
    }
    if ($result.Success) {
        $isValidOutput = $false
        try {
            Log "DEBUG" "Verifying re-muxed output: $tempOutputPath"
            $identifyOutput = & $ffprobe -v error -show_streams "$tempOutputPath" 2>&1
            if ($LASTEXITCODE -eq 0) {
                Log "DEBUG" "Verification successful for '$tempOutputPath'."
                $isValidOutput = $true
            } else {
                Log "WARNING" "FFprobe identify verification failed for '$tempOutputPath'. Exit code: $LASTEXITCODE."
                Log "DEBUG" "FFprobe identify Output/Error:`n$identifyOutput"
            }
        } catch {
            Log "WARNING" "Error during ffprobe verification for '$tempOutputPath': $_"
        }

        # Verify temp file exists and has size before replacing original
        if ($isValidOutput -and (Test-Path $tempOutputPath) -and ((Get-Item $tempOutputPath).Length -gt 0)) {
            Log "INFO" "Successfully re-muxed '$baseName'."
            $backupPath = "$videoPath.bak"
            try {
                # 1. Rename original to backup
                Rename-Item $videoPath $backupPath -Force -ErrorAction Stop
                Log "DEBUG" "Renamed original '$videoPath' to '$backupPath'."
                # 2. Rename temp file to original name
                Rename-Item $tempOutputPath $videoPath -Force -ErrorAction Stop
                Log "INFO" "Replaced original with re-muxed version: '$videoPath'"

                # 3. If successful, remove backup
                Remove-Item -Path $backupPath -Force -ErrorAction SilentlyContinue
                Log "DEBUG" "Removed backup file '$backupPath'."
            
                $successfullyReconstructed.Add($videoPath)
                $successCount++
            } catch {
                Log "ERROR" "Failed during replacement process for '$videoPath'. Error: $_"
                # Attempt rollback if possible
                if ((Test-Path $backupPath) -and -not (Test-Path $videoPath)) {
                    Log "INFO" "Attempting to restore original from backup '$backupPath'..."
                    Rename-Item $backupPath $videoPath -Force
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
# Filter out successfully reconstructed videos
$remainingVideos = @($videosToReconstruct | Where-Object { $successfullyReconstructed -notcontains $_ })
if ($null -eq $remainingVideos) {
    $remainingVideos = @()  # ensure it's always an array
}
Log "INFO" "Updated reconstruction list: $($remainingVideos.Count) remaining."
Log "INFO" "Summary: Success=$successCount, Failed=$failCount"
