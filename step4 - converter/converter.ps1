param(
    [Parameter(Mandatory=$true)]
    [string]$unzippedDirectory,
    [string]$ffmpeg,
    [string]$magickPath,
    [string]$step
)

$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

#Utils Dirctory
$UtilDirectory = Join-Path $scriptDirectory "..\Utils"
$UtilFile = Join-Path $UtilDirectory "Utils.psm1"
Import-Module $UtilFile -Force

#Outputs Dirctory
$OutputDirectory = Join-Path $scriptDirectory "..\Outputs"

# --- Logging Setup for this script ---
# 1. Define the log file path
$childLogFilePath = Join-Path "$scriptDirectory\..\Logs" -ChildPath $("Step_$step" + "_" + "$scriptName.log")

# 2. Get logging configuration from environment variables
$logLevelMap = $env:LOG_LEVEL_MAP_JSON | ConvertFrom-Json -AsHashtable
$consoleLogLevel = $logLevelMap[$env:DEDUPLICATOR_CONSOLE_LOG_LEVEL.ToUpper()]
$fileLogLevel    = $logLevelMap[$env:DEDUPLICATOR_FILE_LOG_LEVEL.ToUpper()]

# 3. Create a local, pre-configured logger for this script
$Log = {
    param([string]$Level, [string]$Message)
    Write-Log -Level $Level -Message $Message -LogFilePath $childLogFilePath -ConsoleLogLevel $consoleLogLevel -FileLogLevel $fileLogLevel -LogLevelMap $logLevelMap
}

# 4. Write initial log message to ensure file creation
& $Log "INFO" "--- Script Started: $scriptName ---"

# Validate the directory
if (!(Test-Path -Path $unzippedDirectory -PathType Container)) {
    & $Log "ERROR" "Invalid directory path: $unzippedDirectory"
    exit 1
}

# Define progress log path
$progressLogPath = Join-Path $OutputDirectory "Step5_ffmpeg_progress_realtime.log"

# Define the list of video and photo extensions
$videoExtensions = @(".mov", ".avi", ".mkv", ".flv", ".webm", ".mpeg", ".mpx", ".3gp", ".mp4", ".wmv", ".mpg" , ".m4v" ) #added .mpeg
$photoExtensions = @(".jpeg", ".png", ".gif", ".bmp", ".tiff", ".heic", ".heif") # added heif

# Function to convert video files using FFmpeg
function Convert-VideoUsingFFmpeg {
    param (
        [string]$inputFile,
        [string]$outputFile
    )

    # Get video duration in seconds
    try {
        $durationString = & $ffmpeg -i $inputFile 2>&1 | Select-String "Duration"
        if ($durationString -match "Duration: (\d+):(\d+):(\d+\.\d+)") {
            $totalSeconds = ($matches[1] -as [int]) * 3600 + ($matches[2] -as [int]) * 60 + ($matches[3] -as [double])
        } else {
            throw "Could not determine video duration."
        }
    } catch {
        & $Log "ERROR" "Failed to get video duration for '$inputFile': $_"
        return $false
    }

	try {
		$ffmpegArgs = "-i `"$inputFile`" -qscale 0 `"$outputFile`" -y -progress - -nostats"
	
		$processInfo = New-Object System.Diagnostics.ProcessStartInfo
		$processInfo.FileName = $ffmpeg
		$processInfo.Arguments = $ffmpegArgs
		$processInfo.RedirectStandardOutput = $true
		$processInfo.RedirectStandardError  = $true
		$processInfo.UseShellExecute = $false
		$processInfo.CreateNoWindow = $true
	
		$process = New-Object System.Diagnostics.Process
		$process.StartInfo = $processInfo
		$process.Start() | Out-Null
	
		$progressLines = @()
		while (-not $process.StandardOutput.EndOfStream) {
			$line = $process.StandardOutput.ReadLine()
			if ($line) {
				$progressLines += $line
	
				if ($line -match "out_time_ms=(\d+)") {
					$elapsedSeconds = [math]::Round(($matches[1] -as [double]) / 1000000, 2)
					$percentComplete = [math]::Round(($elapsedSeconds / $totalSeconds) * 100, 2)
					Write-Progress -Activity "Converting: $inputFile" -Status "$percentComplete% complete" -PercentComplete $percentComplete
				}
	
				# Save to progress file every few lines
				if ($progressLines.Count -ge 10) {
					$tempPath = "$progressLogPath.tmp"
					$progressLines -join "`n" | Out-File -FilePath $tempPath -Encoding UTF8
					Move-Item -Path $tempPath -Destination $progressLogPath -Force
					$progressLines = @()
				}
			}
		}
	
		# Final flush
		if ($progressLines.Count -gt 0) {
			$tempPath = "$progressLogPath.tmp"
			$progressLines -join "`n" | Out-File -FilePath $tempPath -Encoding UTF8
			Move-Item -Path $tempPath -Destination $progressLogPath -Force
		}
	
		$process.WaitForExit()
	
		if ($process.ExitCode -ne 0) {
			& $Log "ERROR" "FFmpeg failed with exit code $($process.ExitCode) on $inputFile"
			return $false
		}
	} catch {
		& $Log "ERROR" "Failed to convert video: $inputFile. Error: $_"
		return $false
	}

    & $Log "INFO" "Converted: $($inputFile) → $($outputFile)"
    return $true
}

# Function to convert photo files to JPG using ImageMagick
function Convert-PhotoToJpg {
    param (
        [string]$inputFile,
        [string]$outputFile
    )
    try {
        if (!(Test-Path -Path $magickPath)) {
            throw "ImageMagick executable not found at: $magickPath"
        }
        & $magickPath $inputFile $outputFile
        if ($LASTEXITCODE -ne 0) {
            $errorMessage = "ImageMagick failed with exit code $LASTEXITCODE"
            & $Log "ERROR" "$errorMessage on $inputFile"
            & $Log "WARNING" "Conversion failed: $inputFile"            
            return $false
        }
    } catch {
        $errorMessage = "Failed to convert photo: $inputFile. Error: $_"
        & $Log "ERROR" "$errorMessage"
        & $Log "WARNING" "Conversion failed: $inputFile"
        return $false
    }
    & $Log "INFO" "Converted: $inputFile to $outputFile"
    return $true
}

function Rename-SidecarFiles {
    param (
        [string]$OriginalFilePath,
        [string]$NewFilePath
    )
    $originalFileName = Split-Path -Path $OriginalFilePath -Leaf
    $newFileName = Split-Path -Path $NewFilePath -Leaf
    $directory = Split-Path -Path $OriginalFilePath -Parent

    # Find files that start with the original filename, but are not the original file itself.
    # e.g., for "IMG_1234.MOV", this finds "IMG_1234.MOV.json"
    $sidecarFiles = Get-ChildItem -Path $directory -File -Filter "$originalFileName.*" | Where-Object { $_.FullName -ne $OriginalFilePath }

    foreach ($sidecar in $sidecarFiles) {
        # Replace the original filename part with the new filename part
        $newSidecarName = $sidecar.Name.Replace($originalFileName, $newFileName, [System.StringComparison]::OrdinalIgnoreCase)
        try {
            Rename-Item -Path $sidecar.FullName -NewName $newSidecarName -Force -ErrorAction Stop
            & $Log "INFO" "Renamed sidecar: '$($sidecar.Name)' -> '$newSidecarName'"
        } catch {
            & $Log "ERROR" "Failed to rename sidecar '$($sidecar.FullName)': $_"
        }
    }
}

# Remove .MP files before processing
& $Log "INFO" "Starting cleanup: removing .MP files..."
$mpFiles = Get-ChildItem -Path $unzippedDirectory -Recurse -File -Filter "*.mp"
foreach ($mpFile in $mpFiles) {
    Remove-Item -Path $mpFile.FullName -Force
    & $Log "INFO" "Removed .mp file: $($mpFile.FullName)"
}

# --- Load the metadata file which will be our source of work ---
$metaPath = Join-Path $OutputDirectory "Consolidate_Meta_Results.json"
if (-not (Test-Path $metaPath)) {
    & $Log "CRITICAL" "Consolidated metadata file not found at '$metaPath'. This script must run after 'MapGoogleJson'."
    exit 1
}

try {
    $sourceJsonData = Get-Content $metaPath -Raw | ConvertFrom-Json
} catch {
    & $Log "CRITICAL" "Failed to parse JSON at '$metaPath': $($_.Exception.Message)"
    exit 1
}

# This will hold the results with updated paths
$updatedJsonData = [ordered]@{}

$allPaths = $sourceJsonData.PSObject.Properties.Name
$currentItem = 0
$totalItems = $allPaths.Count

foreach ($originalPath in $allPaths) {
    $currentItem++
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message "Converting: $(Split-Path $originalPath -Leaf)"

    if (-not (Test-Path $originalPath)) {
        & $Log "WARNING" "File '$originalPath' from metadata JSON not found on disk. Skipping."
        continue
    }

    $file = Get-Item $originalPath
    $extension = $file.Extension.ToLower()
    $newPath = $originalPath
    $conversionNeeded = $false

    # Determine if conversion is needed and what the new path will be
    if (($videoExtensions -contains $extension) -and ($extension -ne ".mp4")) {
        $newPath = [System.IO.Path]::ChangeExtension($file.FullName, '.mp4')
        $conversionNeeded = $true
    } elseif (($photoExtensions -contains $extension) -and ($extension -ne ".jpg")) {
        $newPath = [System.IO.Path]::ChangeExtension($file.FullName, '.jpg')
        $conversionNeeded = $true
    }

    if ($conversionNeeded) {
        if (Test-Path $newPath) {
            & $Log "WARNING" "Target file '$newPath' already exists. Skipping conversion of '$originalPath'."
            # Add the original data to the new map, assuming the existing file is what we want
            $updatedJsonData[$originalPath] = $sourceJsonData.$originalPath
            continue
        }

        $success = $false
        if ($newPath.EndsWith('.mp4')) {
            $success = Convert-VideoUsingFFmpeg -inputFile $originalPath -outputFile $newPath
        } elseif ($newPath.EndsWith('.jpg')) {
            $success = Convert-PhotoToJpg -inputFile $originalPath -outputFile $newPath
        }

        if ($success) {
            Rename-SidecarFiles -OriginalFilePath $originalPath -NewFilePath $newPath
            Remove-Item -Path $originalPath -Force
            & $Log "INFO" "Removed original file after conversion: $originalPath"
            $updatedJsonData[$newPath] = $sourceJsonData.$originalPath
        } else {
            & $Log "ERROR" "Failed to convert '$originalPath'. It will be excluded from the updated metadata file."
            # Clean up partially converted file on failure
            if (Test-Path -Path $newPath) {
                Remove-Item -Path $newPath -Force
                & $Log "WARNING" "Removed failed conversion output: $newPath"
            }
        }
    } else {
        # No conversion needed, just copy the data over
        $updatedJsonData[$originalPath] = $sourceJsonData.$originalPath
    }
}

# --- Atomically write the updated JSON data back to the file ---
try {
    Write-JsonAtomic -Data $updatedJsonData -Path $metaPath
    & $Log "INFO" "Successfully updated metadata file with converted paths."
} catch {
    & $Log "CRITICAL" "Failed to write updated metadata to '$metaPath': $($_.Exception.Message)"
    exit 1
}

& $Log "INFO" "--- Script Finished: $scriptName ---"
