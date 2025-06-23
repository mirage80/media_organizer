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

# Validate the directory
if (!(Test-Path -Path $unzippedDirectory -PathType Container)) {
    Log "ERROR" "Invalid directory path: $unzippedDirectory"
    exit 1
}

# Define progress log path
$OutputDir = Join-Path $scriptDirectory "..\Output"
$progressLogPath = Join-Path $OutputDir "ffmpeg_progress_realtime.log"

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
        Log "ERROR" "Failed to get video duration for '$inputFile': $_"
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
			Log "ERROR" "FFmpeg failed with exit code $($process.ExitCode) on $inputFile"
			return $false
		}
	} catch {
		Log "ERROR" "Failed to convert video: $inputFile. Error: $_"
		return $false
	}

    Log "INFO" "Converted: $($inputFile) → $($outputFile)"
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
            Log "ERROR" "$errorMessage on $inputFile"
            Log "WARNING" "Conversion failed: $inputFile"            
            return $false
        }
    } catch {
        $errorMessage = "Failed to convert photo: $inputFile. Error: $_"
        Log "ERROR" "$errorMessage"
        Log "WARNING" "Conversion failed: $inputFile"
        return $false
    }
    Log "INFO" "Converted: $inputFile to $outputFile"
    return $true
}

# Function to rename any file based on base name and extension
function Rename-AnyFile {
    param (
        [string]$originalFile,
        [string]$newFile
    )
    $originalFileName = Split-Path -Path $originalFile -Leaf
    $newFileName = Split-Path -Path $newFile -Leaf
    $directory = Split-Path -Path $originalFile -Parent

    $relatedFiles = Get-ChildItem -Path $directory -File

    foreach ($relatedFile in $relatedFiles) {
        $relatedFileName = Split-Path -Path $relatedFile.FullName -Leaf
        $relatedFileBaseName = [System.IO.Path]::GetFileNameWithoutExtension($relatedFileName)
        $relatedFileExtension = [System.IO.Path]::GetExtension($relatedFileName)

        if ($relatedFileBaseName -eq $originalFileName) {
            $newRelatedFileName = $newFileName + $relatedFileExtension
            $newRelatedFilePath = Join-Path -Path $directory -ChildPath $newRelatedFileName

            if (-not (Test-Path -Path $newRelatedFilePath)) {
                try {
                    Rename-Item -Path $relatedFile.FullName -NewName $newRelatedFilePath -Force
                    Log "INFO" "Renamed $($relatedFile.FullName) to $($newRelatedFilePath)"
                } catch {
                    Log "ERROR" "Error renaming $($relatedFile.FullName) to $($newRelatedFilePath): $_"
                }
            } else {
                Log "WARNING" "Skipped renaming $($relatedFile.FullName) to $($newRelatedFilePath) because the file already exists."
            }
        }
    }
}

# Function to rename .json.tmp files to .json
function Rename-JsonTmpToJson {
    param (
        [string]$directory
    )
    $jsonTmpFiles = Get-ChildItem -Path $directory -Recurse -File -Filter "*.json.tmp"

    foreach ($jsonTmpFile in $jsonTmpFiles) {
        $newBaseName = $jsonTmpFile.BaseName -replace '\.MOV$', '.mp4' -replace '\.AVI$', '.mp4' -replace '\.MKV$', '.mp4' -replace '\.FLV$', '.mp4' -replace '\.WEBM$', '.mp4' -replace '\.MPX$', '.mp4' -replace '\.3GP$', '.mp4' -replace '\.MPEG$', '.mp4'

        $potentialMp4File = Join-Path -Path $jsonTmpFile.DirectoryName -ChildPath "$($newBaseName).mp4"
        if (Test-Path -Path $potentialMp4File) {
            $newJsonTmpName = "$($newBaseName).mp4.json"
            $newJsonTmpPath = Join-Path -Path $jsonTmpFile.DirectoryName -ChildPath $newJsonTmpName
        } else {
            $newJsonTmpName = $jsonTmpFile.Name -replace '\.json\.tmp$', '.json'
            $newJsonTmpPath = Join-Path -Path $jsonTmpFile.DirectoryName -ChildPath $newJsonTmpName
        }

        try {
            Rename-Item -Path $jsonTmpFile.FullName -NewName $newJsonTmpName -Force
            Log "INFO" "Renamed $($jsonTmpFile.FullName) to $($newJsonTmpPath)"
        } catch {
            Log "ERROR" "Error renaming $($jsonTmpFile.FullName) to $($newJsonTmpPath): $_"
        }
    }
}

# Function to fix missed related files
function Repair-MissedRelatedFiles {
    param (
        [string]$directory
    )
    $allMediaFiles = Get-ChildItem -Path $directory -Recurse -File | Where-Object {
        $videoExtensions -contains $_.Extension.ToLower() -or $photoExtensions -contains $_.Extension.ToLower()
    }
    $totalItems = $allMediaFiles.Count
    $currentItem = 1
    foreach ($mediaFile in $allMediaFiles) {
        Show-ProgressBar -Current $currentItem -Total $totalItems -Message "Renaming"
        $currentItem++
        Rename-AnyFile -originalFile $mediaFile.FullName -newFile $mediaFile.FullName
    }
}

# Remove .MP files before processing
Log "INFO" "Starting cleanup: removing .MP files..."
$mpFiles = Get-ChildItem -Path $unzippedDirectory -Recurse -File -Filter "*.mp"
foreach ($mpFile in $mpFiles) {
    Remove-Item -Path $mpFile.FullName -Force
    Log "INFO" "Removed .mp file: $($mpFile.FullName)"
}

# Process the remaining files
$files = Get-ChildItem -Path $unzippedDirectory -Recurse -File
$currentItem = 0
$totalItems = $files.Count
foreach ($file in $files) {

    $currentItem++
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message "Converting"

    $extension = $file.Extension.ToLower()
    $outputFile = ""
    $result = $false
    $fileAction = ""

    if ($videoExtensions -contains $extension) {
        if ($extension -eq ".mp4") {
            $outputFile = $file.FullName
            Log "INFO" "Skipped already in mp4 format: $($file.FullName)"
            $result = $true
            $fileAction = "Skipped"
        } else {
            $outputFile = $file.FullName -replace [regex]::Escape($file.Extension), '.mp4'
            $result = Convert-VideoUsingFFmpeg -inputFile $file.FullName -outputFile $outputFile
            if ($result) {
                Log "INFO" "Successfully converted video: $($file.FullName) → $outputFile"
                $fileAction = "Converted to mp4"
            }
        }
    } elseif ($photoExtensions -contains $extension) {
        if ($extension -eq ".heic" -or $extension -eq ".heif") {
            $outputFile = $file.FullName -replace [regex]::Escape($file.Extension), '.jpg'
            $result = Convert-PhotoToJpg -inputFile $file.FullName -outputFile $outputFile
            if ($result) {
                Log "INFO" "Successfully converted photo: $($file.FullName) → $outputFile"
                $fileAction = "Converted to jpg"
            }
        } else {
            $outputFile = $file.FullName -replace [regex]::Escape($file.Extension), '.jpg'
            $result = Convert-PhotoToJpg -inputFile $file.FullName -outputFile $outputFile
            if ($result) {
                Log "INFO" "Successfully converted photo: $($file.FullName) → $outputFile"
                $fileAction = "Converted to jpg"
            }
        }
    } elseif ($extension -eq ".jpg" -or $extension -eq ".json") {
        $result = $true
        $fileAction = "Skipped"
    } else {
        Log "INFO" "Skipped non-convertible file: $($file.FullName)"
        $result = $false
        $fileAction = "Skipped"
    }

    if ($result) {
        if ($videoExtensions -contains $extension -or $photoExtensions -contains $extension) {
            Rename-AnyFile -originalFile $file.FullName -newFile $outputFile
        }
        if ($fileAction -ne "Skipped") {
            Remove-Item -Path $file.FullName -Force
            Log "INFO" "Removed file: $($file.FullName)"
        }
    } else {
        if (Test-Path -Path $outputFile) {
            Remove-Item -Path $outputFile -Force
        }
    }

    $totalFiles--
    if ($fileAction -eq "Skipped") {
        Log "INFO" "$($fileAction): $($file.FullName)"
    }
}
# After processing all files, rename .json.tmp to .json
Rename-JsonTmpToJson -directory $unzippedDirectory
# Fix any missed related files
Repair-MissedRelatedFiles -directory $unzippedDirectory
Log "INFO" "Conversion and .json.tmp processing completed"
