param(
    [Parameter(Mandatory=$true)]
    $Config
)

# --- Path Setup ---
$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

# Get paths from config
$processedDirectory = $Config.paths.processedDirectory
$outputDirectory = $Config.paths.outputDirectory
$ffmpeg = $Config.paths.tools.ffmpeg
$magickPath = $Config.paths.tools.imageMagick
$phase = $env:CURRENT_PHASE

# Utils Directory
$UtilDirectory = Join-Path $scriptDirectory "..\Utils"
$UtilFile = Join-Path $UtilDirectory "Utils.psm1"
$MediaToolsFile = Join-Path $UtilDirectory 'MediaTools.psm1'
Import-Module $UtilFile -Force
Import-Module $MediaToolsFile -Force

# --- Logging Setup ---
$logDirectory = $Config.paths.logDirectory
$Logger = Initialize-ScriptLogger -LogDirectory $logDirectory -ScriptName $scriptName -Step $phase -Config $Config
$Log = $Logger.Logger

# Inject logger for module functions
Set-UtilsLogger -Logger $Log
Set-MediaToolsLogger -Logger $Log

& $Log "INFO" "--- Script Started: $scriptName ---"

# Validate the directory
if (!(Test-Path -Path $processedDirectory -PathType Container)) {
    & $Log "ERROR" "Invalid directory path: $processedDirectory"
    exit 1
}

# Define progress log path
$progressLogPath = Join-Path $OutputDirectory "Step5_ffmpeg_progress_realtime.log"

# Define the list of video and photo extensions
$videoExtensions = @(".mov", ".avi", ".mkv", ".flv", ".webm", ".mpeg", ".mpx", ".3gp", ".mp4", ".wmv", ".mpg" , ".m4v" ) #added .mpeg
$photoExtensions = @(".jpeg", ".png", ".gif", ".bmp", ".tiff", ".heic", ".heif") # added heif

# --- Load the metadata file which will be our source of work ---
$metaPath = Join-Path $outputDirectory "Consolidate_Meta_Results.json"

$initialData = @{}
if (Test-Path $metaPath) {
    try {
        # Load the file content and convert from JSON into a hashtable.
        $initialData = Get-Content $metaPath -Raw | ConvertFrom-Json
    } catch {
        & $Log "CRITICAL" "Failed to parse JSON at $metaPath : $($_.Exception.Message)"
        exit 1
    }
}

# Create a thread-safe ConcurrentDictionary with the desired string comparer.
# This uses an unambiguous constructor that is guaranteed to exist.
$initialJsonData = [System.Collections.Concurrent.ConcurrentDictionary[string, object]]::new([System.StringComparer]::OrdinalIgnoreCase)

# Populate the dictionary from the initial data. This two-step process is more robust
# than relying on constructor overload resolution, which can be ambiguous in PowerShell.
if ($null -ne $initialData) {
    foreach ($key in $initialData.Keys) {
        $initialJsonData.TryAdd($key, $initialData[$key]) | Out-Null
    }
}

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
					$percentComplete = if ($totalSeconds -gt 0) { [int](($elapsedSeconds / $totalSeconds) * 100) } else { 0 }
                    # Update the sub-task message to show FFmpeg's progress for the current file, without changing the overall percentage bar.
                    Update-GraphicalProgressBar -SubTaskMessage "Converting $(Split-Path $inputFile -Leaf) ($percentComplete%)"
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
        [string]$outputFile,
        [string]$imageMagickPath
    )
    try {
        if (!(Test-Path -Path $imageMagickPath)) {
            throw "ImageMagick executable not found at: $imageMagickPath"
        }
        & $imageMagickPath $inputFile $outputFile
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

# Remove .MP files before processing
& $Log "INFO" "Starting cleanup: removing .MP files..."
$mpFiles = Get-ChildItem -Path $processedDirectory -Recurse -File -Filter "*.mp"
foreach ($mpFile in $mpFiles) {
    Remove-Item -Path $mpFile.FullName -Force
    & $Log "INFO" "Removed .mp file: $($mpFile.FullName)"
}

if (-not (Test-Path $metaPath)) {
    & $Log "CRITICAL" "Consolidated metadata file not found at '$metaPath'. This script must run after 'MapGoogleJson'."
    exit 1
}

$updatedJsonData = @{}

$allPaths = Get-ChildItem -Path $processedDirectory -Recurse -File

$currentItem = 0
$totalItems = $allPaths.Count

foreach ($originalPath in $allPaths) {
    $currentItem++
    $percent = if ($totalItems -gt 0) { [int](($currentItem / $totalItems) * 100) } else { 100 }
    Update-GraphicalProgressBar -SubTaskPercent $percent -SubTaskMessage "Processing file $currentItem of $totalItems : $(Split-Path $originalPath -Leaf)"

    if (-not (Test-Path $originalPath.FullName)) {
        & $Log "WARNING" "File '$($originalPath.Name)' not found on disk. Skipping."
        continue
    }

    $file = $originalPath
    $originalPath = ConvertTo-StandardPath -Path $file.FullName
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
            if ($initialJsonData.ContainsKey($originalPath)) {
                $updatedJsonData[$newPath] = $initialJsonData[$originalPath]
            } else {
                $updatedJsonData[$newPath] = New-DefaultMetadataObject -filepath $newPath
            }
            $updatedJsonData[$newPath] = $initialJsonData[$originalPath]
            continue
        }

        $success = $false
        if ($newPath.EndsWith('.mp4')) {
            $success = Convert-VideoUsingFFmpeg -inputFile $originalPath -outputFile $newPath
        } elseif ($newPath.EndsWith('.jpg')) {
            $success = Convert-PhotoToJpg -inputFile $originalPath -outputFile $newPath -imageMagickPath $magickPath
        }

        if ($success) {
            Rename-SidecarFiles -OriginalFilePath $originalPath -NewFilePath $newPath
            Remove-Item -Path $originalPath -Force
            & $Log "INFO" "Removed original file after conversion: $originalPath"
            if ($initialJsonData.ContainsKey($originalPath)) {
                & $Log "INFO" "Adding converted file '$newPath' to updated metadata."
                # Add the converted file to the updated metadata
                $updatedJsonData[$newPath] = $initialJsonData[$originalPath]
                $updatedJsonData[$newPath].size = (Get-Item $newPath).Length
                $updatedJsonData[$newPath].name = Split-Path $newPath -Leaf 
            } else {
                $updatedJsonData[$newPath] = New-DefaultMetadataObject -filepath $newPath
            }
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
        if ($initialJsonData.ContainsKey($originalPath)) {
            $updatedJsonData[$originalPath] = $initialJsonData[$originalPath]
        } else {
            $updatedJsonData[$originalPath] = New-DefaultMetadataObject -filepath $originalPath
        }
       & $Log "INFO" "No conversion needed for '$originalPath'. Keeping original path."
    }
}

# Convert all keys to standardized string paths before writing to JSON
$updatedJsonData = Convert-HashtableToStringKey -InputHashtable $updatedJsonData
# Atomically write the updated JSON data back to the file
try {
    Write-JsonAtomic -Data $updatedJsonData -Path $metaPath
    & $Log "INFO" "Successfully updated metadata file with converted paths."
} catch {
    & $Log "CRITICAL" "Failed to write updated metadata to '$metaPath': $($_.Exception.Message)"
    exit 1
}

& $Log "INFO" "--- Script Finished: $scriptName ---"
