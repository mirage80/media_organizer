# Define the input/output directory (same path as the script)
$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$unzipedDirectory = 'E:\'

# Validate the directory
if (!(Test-Path -Path $unzipedDirectory -PathType Container)) {
    Write-Error "Invalid directory path: $unzipedDirectory"
    exit 1
}

# Define the log file for conversion failures
$logFile = Join-Path -Path $scriptDirectory -ChildPath "conversion_failures.txt"
# Define the log file for conversion skipped
$logSkippedFile = Join-Path -Path $scriptDirectory -ChildPath "conversion_skipped.txt"
# Define the log file for successful conversions
$logSuccessfulConversions = Join-Path -Path $scriptDirectory -ChildPath "conversion_success.txt"
# Define the log file for files fixed
$logFixFile = Join-Path -Path $scriptDirectory -ChildPath "conversion_fixed.txt"
# Define the log file for files report (make sure this is correct)
$logReportFile = Join-Path -Path $scriptDirectory -ChildPath "file_report.txt"

# Define the path to the ImageMagick executable
$magickPath = "C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe"  # Update this path if needed

# Function to convert video files using FFmpeg
# Define the path to the ffmpeg executable (make sure this is correct)
$ffmpeg = "ffmpeg.exe"


# Create the log files if they don't exist, or clear them if they do
$logFiles = @($logFile, $logSkippedFile, $logSuccessfulConversions, $logFixFile, $logReportFile)
foreach ($file in $logFiles) {
    if (-not (Test-Path -Path $file)) {
        New-Item -ItemType File -Path $file | Out-Null
    } else {
        Clear-Content -Path $file
    }
}

# Define the list of video and photo extensions
$videoExtensions = @(".mov", ".avi", ".mkv", ".flv", ".webm", ".mpeg", ".mpx", ".3gp", ".mp4", ".wmv", ".mpg" , ".m4v" ) #added .mpeg
$photoExtensions = @(".jpeg", ".png", ".gif", ".bmp", ".tiff", ".heic", ".heif") # added heif

# Function to convert video files using FFmpeg
function Convert-VideoUsingFFmpeg {
    param (
        [string]$inputFile,
        [string]$outputFile
    )

    $ffmpegPath = "ffmpeg"  # Ensure ffmpeg is in the PATH or specify the full path
    $logFile = "conversion.log"
    $logReportFile = "conversion_report.log"

    # Get video duration in seconds
    try {
        $durationString = & $ffmpegPath -i $inputFile 2>&1 | Select-String "Duration"
        if ($durationString -match "Duration: (\d+):(\d+):(\d+\.\d+)") {
            $totalSeconds = ($matches[1] -as [int]) * 3600 + ($matches[2] -as [int]) * 60 + ($matches[3] -as [double])
        } else {
            throw "Could not determine video duration."
        }
    } catch {
        Write-Host "Error: Failed to get video duration. $_" -ForegroundColor Red
        return $false
    }

    # Start the conversion process and monitor progress
    try {
        $process = Start-Process -FilePath $ffmpegPath -ArgumentList "-i `"$inputFile`" -qscale 0 `"$outputFile`" -y -progress pipe:1" -NoNewWindow -PassThru -RedirectStandardOutput "ffmpeg_progress.log"

        while (!$process.HasExited) {
            Start-Sleep -Seconds 1
            if (Test-Path "ffmpeg_progress.log") {
                $progressLines = Get-Content "ffmpeg_progress.log" -Tail 10
                foreach ($line in $progressLines) {
                    if ($line -match "out_time_ms=(\d+)") {
                        $elapsedSeconds = [math]::Round(($matches[1] -as [double]) / 1000000, 2)
                        $percentComplete = [math]::Round(($elapsedSeconds / $totalSeconds) * 100, 2)
                        Write-Progress -Activity "Converting: $inputFile" -Status "$percentComplete% complete" -PercentComplete $percentComplete
                    }
                }
            }
        }

        Remove-Item "ffmpeg_progress.log" -ErrorAction Ignore

        if ($process.ExitCode -ne 0) {
            $errorMessage = "FFmpeg failed with exit code $($process.ExitCode)"
            Add-Content -Path $logFile -Value "$errorMessage on $inputFile"
            Add-Content -Path $logReportFile -Value "Conversion failed: $($inputFile)"
            return $false
        }
    } catch {
        $errorMessage = "Failed to convert video: $inputFile. Error: $_"
        Add-Content -Path $logFile -Value $errorMessage
        Add-Content -Path $logReportFile -Value "Conversion failed: $($inputFile)"
        return $false
    }

    Add-Content -Path $logReportFile -Value "Converted: $($inputFile) to $($outputFile)"
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
            Add-Content -Path $logFile -Value "$errorMessage on $inputFile"
            Add-Content -Path $logReportFile -Value "Conversion failed: $($inputFile)"
            return $false
        }
    } catch {
        $errorMessage = "Failed to convert photo: $inputFile. Error: $_"
        Add-Content -Path $logFile -Value $errorMessage
        Add-Content -Path $logReportFile -Value "Conversion failed: $($inputFile)"
        return $false
    }
    Add-Content -Path $logReportFile -Value "Converted: $($inputFile) to $($outputFile)"
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
    $baseOriginalFileName = [System.IO.Path]::GetFileNameWithoutExtension($originalFileName)
    $baseNewFileName = [System.IO.Path]::GetFileNameWithoutExtension($newFileName)
    $originalFileExtension = [System.IO.Path]::GetExtension($originalFileName)
    $newFileExtension = [System.IO.Path]::GetExtension($newFileName)

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
                    Add-Content -Path $logFixFile -Value "Renamed $($relatedFile.FullName) to $($newRelatedFilePath)"
                    Add-Content -Path $logReportFile -Value "Renamed $($relatedFile.FullName) to $($newRelatedFilePath)"
                } catch {
                    Add-Content -Path $logFile -Value "Error renaming $($relatedFile.FullName) to $($newRelatedFilePath): $_"
                    Add-Content -Path $logReportFile -Value "Error renaming $($relatedFile.FullName) to $($newRelatedFilePath): $_"
                }
            } else {
                Add-Content -Path $logFile -Value "Skipped renaming $($relatedFile.FullName) to $($newRelatedFilePath) because the file already exists."
                Add-Content -Path $logReportFile -Value "Skipped renaming $($relatedFile.FullName) to $($newRelatedFilePath) because the file already exists."
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
            Add-Content -Path $logFixFile -Value "Renamed $($jsonTmpFile.FullName) to $($newJsonTmpPath)"
            Add-Content -Path $logReportFile -Value "Renamed $($jsonTmpFile.FullName) to $($newJsonTmpPath)"
        } catch {
            Add-Content -Path $logFile -Value "Error renaming $($jsonTmpFile.FullName) to $($newJsonTmpPath): $_"
            Add-Content -Path $logReportFile -Value "Error renaming $($jsonTmpFile.FullName) to $($newJsonTmpPath): $_"
        }
    }
}

# Function to fix missed related files
function Fix-MissedRelatedFiles {
    param (
        [string]$directory
    )
    $allMediaFiles = Get-ChildItem -Path $directory -Recurse -File | Where-Object {
        $videoExtensions -contains $_.Extension.ToLower() -or $photoExtensions -contains $_.Extension.ToLower()
    }
    foreach ($mediaFile in $allMediaFiles) {
        Rename-AnyFile -originalFile $mediaFile.FullName -newFile $mediaFile.FullName
    }
}

# Remove .MP files before processing
Write-Host "Removing .MP files..."
$mpFiles = Get-ChildItem -Path $unzipedDirectory -Recurse -File -Filter "*.mp"
foreach ($mpFile in $mpFiles) {
    Remove-Item -Path $mpFile.FullName -Force
    Write-Host "Removed: $($mpFile.FullName)"
    Add-Content -Path $logReportFile -Value "Removed : $($mpFile.FullName)"
}

# Process the remaining files
$files = Get-ChildItem -Path $unzipedDirectory -Recurse -File
$currentItem = 0
$totalItems = $files.Count
foreach ($file in $files) {

    $currentItem++
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message $($file.FullName)

    $extension = $file.Extension.ToLower()
    $outputFile = ""
    $result = $false
    $fileAction = ""

    if ($videoExtensions -contains $extension) {
        if ($extension -eq ".mp4") {
            $outputFile = $file.FullName
            Add-Content -Path $logSkippedFile -Value "Skipping mp4 file: $($file.FullName)"
            $result = $true
            $fileAction = "Skipped"
        } else {
            $outputFile = $file.FullName -replace [regex]::Escape($file.Extension), '.mp4'
            $result = Convert-VideoUsingFFmpeg -inputFile $file.FullName -outputFile $outputFile
            if ($result) {
                Add-Content -Path $logSuccessfulConversions -Value "Converted video: $($file.FullName) to $outputFile"
                $fileAction = "Converted to mp4"
            }
        }
    } elseif ($photoExtensions -contains $extension) {
        if ($extension -eq ".heic" -or $extension -eq ".heif") {
            $outputFile = $file.FullName -replace [regex]::Escape($file.Extension), '.jpg'
            $result = Convert-PhotoToJpg -inputFile $file.FullName -outputFile $outputFile
            if ($result) {
                Add-Content -Path $logSuccessfulConversions -Value "Converted photo: $($file.FullName) to $outputFile"
                $fileAction = "Converted to jpg"
            }
        } else {
            $outputFile = $file.FullName -replace [regex]::Escape($file.Extension), '.jpg'
            $result = Convert-PhotoToJpg -inputFile $file.FullName -outputFile $outputFile
            if ($result) {
                Add-Content -Path $logSuccessfulConversions -Value "Converted photo: $($file.FullName) to $outputFile"
                $fileAction = "Converted to jpg"
            }
        }
    } elseif ($extension -eq ".jpg" -or $extension -eq ".json") {
        $result = $true
        $fileAction = "Skipped"
    } else {
        Add-Content -Path $logSkippedFile -Value "Skipping non-convertible file: $($file.FullName)"
        $result = $false
        $fileAction = "Skipped"
    }

    if ($result) {
        if ($videoExtensions -contains $extension -or $photoExtensions -contains $extension) {
            Rename-AnyFile -originalFile $file.FullName -newFile $outputFile
        }
        if ($fileAction -ne "Skipped") {
            Remove-Item -Path $file.FullName -Force
            Add-Content -Path $logReportFile -Value "Removed : $($file.FullName)"
        }
    } else {
        if (Test-Path -Path $outputFile) {
            Remove-Item -Path $outputFile -Force
        }
    }

    $totalFiles--
    if ($fileAction -eq "Skipped") {
        Add-Content -Path $logReportFile -Value "$($fileAction) : $($file.FullName)"
    }
}

# After processing all files, rename .json.tmp to .json
Rename-JsonTmpToJson -directory $unzipedDirectory
# Fix any missed related files
Fix-MissedRelatedFiles -directory $unzipedDirectory
Write-Host " `nConversion and .json.tmp processing completed "
