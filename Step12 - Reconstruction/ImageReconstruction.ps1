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

# --- Logging Setup for this script ---
$childLogFilePath = Join-Path "$scriptDirectory\..\Logs" -ChildPath $("Step_$step" + "_" + "$scriptName.log")
$logLevelMap = $env:LOG_LEVEL_MAP_JSON | ConvertFrom-Json -AsHashtable
$consoleLogLevel = $logLevelMap[$env:DEDUPLICATOR_CONSOLE_LOG_LEVEL.ToUpper()]
$fileLogLevel    = $logLevelMap[$env:DEDUPLICATOR_FILE_LOG_LEVEL.ToUpper()]

$Log = {
    param([string]$Level, [string]$Message)
    Write-Log -Level $Level -Message $Message -LogFilePath $childLogFilePath -ConsoleLogLevel $consoleLogLevel -FileLogLevel $fileLogLevel -LogLevelMap $logLevelMap
}

& $Log "INFO" "--- Script Started: $scriptName ---"

# Inject logger for module functions
Set-UtilsLogger -Logger $Log

# --- Helper Function for ImageMagick ---
function Invoke-Magick {
    param(
        [Parameter(Mandatory = $true)] [string]$InputPath,
        [Parameter(Mandatory = $true)] [string]$OutputPath,
        [Parameter(Mandatory = $true)] [string]$ImageMagick
    )

    if (-not (Test-Path -Path $ImageMagick -PathType Leaf)) {
        & $Log "ERROR" "ImageMagick executable not found: '$ImageMagick'"
        return @{ Success = $false; Output = "Executable not found"; ExitCode = -1 }
    }

    if ($InputPath -eq $OutputPath) {
        & $Log "ERROR" "InputPath and OutputPath are the same. Cannot overwrite in-place."
        return @{ Success = $false; Output = "Input == Output"; ExitCode = -1 }
    }

    & $Log "DEBUG" "Calling ImageMagick: & `"$ImageMagick`" `"$InputPath`" `"$OutputPath`""
   
    try {
        # Capture all output streams (stdout and stderr)
        $output = & "$ImageMagick" "$InputPath" "$OutputPath" 2>&1
        $exitCode = $LASTEXITCODE
        $success = $? # Use PowerShell's automatic success variable

        if ($success -and -not (Test-Path $OutputPath)) {
            & $Log "ERROR" "ImageMagick command succeeded but did not create the output file '$OutputPath'."
            $success = $false
        }

        if ($success) {
            & $Log "INFO" "ImageMagick conversion succeeded for '$InputPath' → '$OutputPath'"
        } else {
            & $Log "WARNING" "ImageMagick failed for '$InputPath' with exit code $exitCode."
            & $Log "DEBUG" "ImageMagick Output:`n$($output -join "`n")"
        }

        return @{
            Success  = $success
            ExitCode = $exitCode
            Output   = $output -join "`n"
        }
    } catch {
        $errorMessage = $_.Exception.Message
        & $Log "ERROR" "Exception running ImageMagick: $errorMessage"
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
        & $Log "INFO" "Loaded $($imagesToReconstruct.Count) images marked for reconstruction from '$reconstructListPath'."
    } catch {
        & $Log "ERROR" "Failed to read or parse '$reconstructListPath': $_. Aborting reconstruction."
        exit 1
    }
} else {
    & $Log "INFO" "Reconstruction list '$reconstructListPath' not found. No images to reconstruct."
    exit 0
}

# --- Deduplication Fix ---
$imagesToReconstruct = $imagesToReconstruct | Select-Object -Unique
& $Log "DEBUG" "Deduplicated input list:`n$($imagesToReconstruct -join "`n")"

if ($imagesToReconstruct.Count -eq 0) {
    & $Log "INFO" "Reconstruction list is empty. Nothing to do."
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
        & $Log "WARNING" "Missing: '$imagePath'. Skipping."
        $failCount++
        continue
    }

    # Define temporary output path
    $tempOutputPath = "$imagePath.repaired.jpg"

    # Attempt reconstruction (re-muxing)
													 
    $result = Invoke-Magick -InputPath $imagePath -OutputPath $tempOutputPath -ImageMagick $magickPath
    if (-not $result.Success) {
        # The Invoke-Magick function already logs the failure details.
        & $Log "DEBUG" "Invoke-Magick returned failure for '$baseName'. Full output: $($result.Output)"
    }
    if ($result.Success) {
        $isValidOutput = $false
        try {
            & $Log "DEBUG" "Verifying re-muxed output: $tempOutputPath"
            $identifyOutput = & $magickPath identify "$tempOutputPath" 2>&1
            if ($LASTEXITCODE -eq 0) {
                & $Log "DEBUG" "Verification successful for '$tempOutputPath'."
                $isValidOutput = $true
            } else {
                & $Log "WARNING" "ImageMagick identify verification failed for '$tempOutputPath'. Exit code: $LASTEXITCODE."
                & $Log "DEBUG" "ImageMagick identify Output/Error:`n$identifyOutput"
            }
        } catch {
            & $Log "WARNING" "Error during ImageMagick identify verification for '$tempOutputPath': $_"
        }

        # Verify temp file exists and has size before replacing original
        if ($isValidOutput -and (Test-Path $tempOutputPath) -and ((Get-Item $tempOutputPath).Length -gt 0)) {
            & $Log "INFO" "Successfully re-muxed '$baseName'."
            $backupPath = "$imagePath.bak"
            try {
                # 1. Rename original to backup
                Rename-Item $imagePath $backupPath -Force -ErrorAction Stop
                & $Log "DEBUG" "Renamed original '$imagePath' to '$backupPath'."
                # 2. Rename temp file to original name
                Rename-Item $tempOutputPath $imagePath -Force -ErrorAction Stop
                & $Log "INFO" "Replaced original with re-muxed version: '$imagePath'"

                # 3. If successful, remove backup
                Remove-Item -Path $backupPath -Force -ErrorAction SilentlyContinue
                & $Log "DEBUG" "Removed backup file '$backupPath'."
            
                $successfullyReconstructed.Add($imagePath)
                $successCount++
            } catch {
                & $Log "ERROR" "Failed during replacement process for '$imagePath'. Error: $_"
                # Attempt rollback if possible
                if ((Test-Path $backupPath) -and -not (Test-Path $imagePath)) {
                    & $Log "INFO" "Attempting to restore original from backup '$backupPath'..."
                    Rename-Item $backupPath $imagePath -Force
                }
                # Clean up temp file if it still exists
                if (Test-Path $tempOutputPath) { Remove-Item $tempOutputPath -Force -ErrorAction SilentlyContinue }
                $failCount++
            }
        } else {
            & $Log "ERROR" "Re-muxing seemed successful for '$baseName', but output file '$tempOutputPath' is missing or empty."
            if (Test-Path $tempOutputPath) { Remove-Item $tempOutputPath -Force -ErrorAction SilentlyContinue } # Clean up invalid temp file
            $failCount++
        }
    } else {
        & $Log "ERROR" "Failed to reconstruct '$baseName'."
        # Clean up failed temp file
        if (Test-Path $tempOutputPath) {
            Remove-Item $tempOutputPath -Force -ErrorAction SilentlyContinue
        }
        $failCount++
    }
}

Write-Host # Clear progress bar line

# --- Update JSON List ---
& $Log "INFO" "Updating reconstruction list..."
# Filter out successfully reconstructed images
$remainingImages = @($imagesToReconstruct | Where-Object { $successfullyReconstructed -notcontains $_ })
if ($null -eq $remainingImages) {
    $remainingImages = @()  # ensure it's always an array
}
& $Log "INFO" "Updated reconstruction list: $($remainingImages.Count) remaining."
& $Log "INFO" "Summary: Success=$successCount, Failed=$failCount"
