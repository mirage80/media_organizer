param(
    [Parameter(Mandatory = $true)] [string]$ffmpeg,
    [Parameter(Mandatory = $true)] [string]$ffprobe,
    [Parameter(Mandatory = $true)] [string]$vlcpath,
    [Parameter(Mandatory = $true)] [string]$reconstructListPath,
    [Parameter(Mandatory = $true)] [string]$step
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

# --- Helper Function for FFmpeg ---
function Invoke-FfmpegSimpleCopy {
    param(
        [Parameter(Mandatory = $true)] [string]$InputPath,
        [Parameter(Mandatory = $true)] [string]$OutputPath,
        [Parameter(Mandatory = $true)] [string]$ffmpeg
   )

    if (-not (Test-Path -Path $ffmpeg -PathType Leaf)) {
        Log "ERROR" "Ffmpeg executable not found: '$ffmpeg'"
        return @{ Success = $false; Output = "Executable not found"; ExitCode = -1 }
    }

    if ($InputPath -eq $OutputPath) {
        Log "ERROR" "InputPath and OutputPath are the same. Cannot overwrite in-place."
        return @{ Success = $false; Output = "Input == Output"; ExitCode = -1 }
    }

    Log "INFO" "Attempt 1: Ffmpeg with simple stream copy for '$InputPath'"
   
    try {
        # Use -c copy to copy all streams without re-encoding.
        $output = & "$ffmpeg" -i "$InputPath" -c copy -loglevel error -y "$OutputPath" 2>&1
        $exitCode = $LASTEXITCODE
        $success = ($exitCode -eq 0)
        Log "DEBUG" "ffmpeg (stream copy) raw output:`n$output"

        if ($success -and -not (Test-Path $OutputPath)) {
            Log "ERROR" "ffmpeg (stream copy) exited with code 0 but did not create output file."
            $success = $false
        }

        if ($success) {
            Log "INFO" "ffmpeg stream copy succeeded for '$InputPath' → '$OutputPath'"
        } else {
            Log "WARNING" "ffmpeg (stream copy) failed for '$InputPath' with exit code $exitCode."
        }

        return @{
            Success  = $success
            ExitCode = $LASTEXITCODE
            Output   = $output -join "`n"
        }

    } catch {
        $errorMessage = $_.Exception.Message
        Log "ERROR" "Exception running ffmpeg (stream copy): $errorMessage"
        return @{
            Success  = $false
            ExitCode = -1
            Output   = "EXCEPTION: $errorMessage"
        }
    }
}

function Invoke-FfmpegWithAudioReencode {
    param(
        [Parameter(Mandatory = $true)] [string]$InputPath,
        [Parameter(Mandatory = $true)] [string]$OutputPath,
        [Parameter(Mandatory = $true)] [string]$ffmpeg
    )
    Log "INFO" "Attempt 2: Ffmpeg with audio re-encode for '$InputPath'"
    try {
        # Use -c:v copy to copy video, -c:a aac to re-encode audio to AAC
        $output = & "$ffmpeg" -i "$InputPath" -c:v copy -c:a aac -b:a 128k -loglevel error -y "$OutputPath" 2>&1
        $exitCode = $LASTEXITCODE
        $success = ($exitCode -eq 0)

        if ($success) {
            Log "INFO" "ffmpeg video copy / audio re-encode succeeded for '$InputPath' → '$OutputPath'"
        } else {
            Log "WARNING" "ffmpeg with audio re-encode failed for '$InputPath' with exit code $exitCode."
            Log "DEBUG" "ffmpeg (audio re-encode) Output:`n$output"
        }
        return @{ Success = $success; Output = $output }
    } catch {
        $errorMessage = $_.Exception.Message
        Log "ERROR" "Exception running ffmpeg with audio re-encode: $errorMessage"
        return @{
            Success  = $false
            ExitCode = -1
            Output   = "EXCEPTION: $errorMessage"
        }
    }
}

# --- Load and Deduplicate List ---
$videosToReconstruct = @()
if (Test-Path -Path $reconstructListPath -PathType Leaf) {
    try {
        $videosToReconstruct = Get-Content -Path $reconstructListPath -Raw | ConvertFrom-Json
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

    # Attempt 1: Simple stream copy (fastest, fixes container issues)
    $result = Invoke-FfmpegSimpleCopy -InputPath $videoPath -OutputPath $tempOutputPath -ffmpeg $ffmpeg

    # Attempt 2: If simple copy fails, try re-encoding just the audio. This fixes many audio codec issues.
    if (-not $result.Success) {
        Log "DEBUG" "Initial failure output: $($result.Output)"
        $result = Invoke-FfmpegWithAudioReencode -InputPath $videoPath -OutputPath $tempOutputPath -ffmpeg $ffmpeg
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
            Log "INFO" "Successfully repaired '$baseName'."
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
            Log "ERROR" "Repair process seemed successful for '$baseName', but output file '$tempOutputPath' is missing, empty, or invalid."
            if (Test-Path $tempOutputPath) { Remove-Item $tempOutputPath -Force -ErrorAction SilentlyContinue } # Clean up invalid temp file
            $failCount++
        }
    } else {
        Log "ERROR" "Failed to reconstruct '$baseName'."
        Log "DEBUG" "Final ffmpeg error output: $($result.Output)"
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
