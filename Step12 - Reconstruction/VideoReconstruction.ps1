$ErrorActionPreference = "Stop"
# Define the directory containing the zip files.
$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent

# --- Logging Setup ---
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)
$logDir = Join-Path $scriptDirectory "..\Logs"
$logFile = Join-Path $logDir "$scriptName.log"
$logFormat = "{0} - {1}: {2}"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

$env:DEDUPLICATOR_CONSOLE_LOG_LEVEL = $env:DEDUPLICATOR_CONSOLE_LOG_LEVEL ?? "INFO"
$env:DEDUPLICATOR_FILE_LOG_LEVEL = $env:DEDUPLICATOR_FILE_LOG_LEVEL ?? "DEBUG"
$logLevelMap = @{ "DEBUG" = 0; "INFO" = 1; "WARNING" = 2; "ERROR" = 3; "CRITICAL" = 4 }
$consoleLogLevel = $logLevelMap[$env:DEDUPLICATOR_CONSOLE_LOG_LEVEL.ToUpper()]
$fileLogLevel = $logLevelMap[$env:DEDUPLICATOR_FILE_LOG_LEVEL.ToUpper()]

function Log {
    param ([string]$Level, [string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $formatted = $logFormat -f $timestamp, $Level.ToUpper(), $Message
    $levelIndex = $logLevelMap[$Level.ToUpper()]
    if ($levelIndex -ge $consoleLogLevel) { Write-Host $formatted }
    if ($levelIndex -ge $fileLogLevel) { Add-Content -Path $logFile -Value $formatted -Encoding UTF8 }
}

# Define paths relative to the main script directory assumed by top.ps1
$outputDir = Join-Path -Path $scriptDirectory -ChildPath "output"
$reconstructListPath = Join-Path -Path $outputDir -ChildPath "video_reconstruct_info.json"

# --- Helper Function for FFmpeg ---
function Invoke-FFmpeg {
    param(
        [Parameter(Mandatory = $true)]
        [string]$InputPath,
        [Parameter(Mandatory = $true)]
        [string]$OutputPath,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments # e.g., @("-codec", "copy")
    )

    $processInfo = New-Object System.Diagnostics.ProcessStartInfo
    $processInfo.FileName = $ffmpeg # Use variable from top.ps1
    # Construct arguments: -i input [specific args] -y output
    $processInfo.Arguments = @("-i", "`"$InputPath`"") + $Arguments + @("-y", "`"$OutputPath`"") -join " "
    $processInfo.RedirectStandardOutput = $true
    $processInfo.RedirectStandardError = $true
    $processInfo.UseShellExecute = $false
    $processInfo.CreateNoWindow = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $processInfo

    $output = [System.Text.StringBuilder]::new()
    $process.OutputDataReceived.add({ $output.AppendLine($EventArgs.Data) | Out-Null })
    $process.ErrorDataReceived.add({ $output.AppendLine($EventArgs.Data) | Out-Null })

    Log "DEBUG" "Executing FFmpeg: $($processInfo.FileName) $($processInfo.Arguments)"

    try {
        $process.Start() | Out-Null
        $process.BeginOutputReadLine()
        $process.BeginErrorReadLine()
        $process.WaitForExit() # Wait indefinitely

        $exitCode = $process.ExitCode
        $fullOutput = $output.ToString()

        if ($exitCode -eq 0) {
            Log "DEBUG" "FFmpeg completed successfully for '$InputPath'."
            return @{ Success = $true; Output = $fullOutput }
        } else {
            Log "WARNING" "FFmpeg failed for '$InputPath' with exit code $exitCode."
            Log "DEBUG" "FFmpeg Output:`n$fullOutput"
            return @{ Success = $false; Output = $fullOutput }
        }
    } catch {
        Log "ERROR" "Exception running FFmpeg for '$InputPath': $_"
        return @{ Success = $false; Output = $_.Exception.Message }
    } finally {
        if ($process -ne $null) {
            $process.Dispose()
        }
    }
}

# Load the list of videos to reconstruct
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
    $baseName = Split-Path -Path $videoPath -Leaf
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message "Reconstructing: $baseName"

    if (-not (Test-Path -Path $videoPath -PathType Leaf)) {
        Log "WARNING" "File not found: '$videoPath'. Skipping."
        $failCount++
        continue
    }

    # Define temporary output path
    $tempOutputPath = "$videoPath.repaired.mp4"

    # Attempt reconstruction (re-muxing)
    $ffmpegArgs = @("-codec", "copy") # Simple re-mux
    $result = Invoke-FFmpeg -InputPath $videoPath -OutputPath $tempOutputPath -Arguments $ffmpegArgs

    if ($result.Success) {
        # Verify temp file exists and has size before replacing original
        if ((Test-Path $tempOutputPath) -and ((Get-Item $tempOutputPath).Length -gt 0)) {
            Log "INFO" "Successfully re-muxed '$baseName'."
            try {
                Remove-Item -Path $videoPath -Force -ErrorAction Stop
                Rename-Item -Path $tempOutputPath -NewName $baseName -Force -ErrorAction Stop
                Log "INFO" "Replaced original with repaired version: '$videoPath'"
                $successfullyReconstructed.Add($videoPath)
                $successCount++
            } catch {
                Log "ERROR" "Failed to replace original file '$videoPath' with repaired version '$tempOutputPath': $_"
                # Attempt to clean up temp file if replacement failed
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
$remainingVideos = $videosToReconstruct | Where-Object { $successfullyReconstructed -notcontains $_ }

# Save the updated list (atomically)
Write-JsonAtomic -Data $remainingVideos -Path $reconstructListPath
Log "INFO" "Reconstruction list updated. $($remainingVideos.Count) videos remain."
Log "INFO" "Summary: Success=$successCount, Failed=$failCount, Remaining=$($remainingVideos.Count)"

