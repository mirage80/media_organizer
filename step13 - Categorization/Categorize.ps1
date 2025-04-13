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

# Define Image and video extensions
$imageExtensions = @(".jpg")
$videoExtensions = @(".mp4")

# Define simplified metadata fields
$TimeStampFields = @{
    ".jpg" = @("CreateDate")
    ".mp4" = @("MediaCreateDate")
}

$gpsFields = @{
    ".jpg" = @("GPSPosition")
    ".mp4" = @("GPSPosition")
}

$time_formats = @("yyyy:MM:dd HH:mm:sszzz", "yyyy:MM:dd HH:mm:ss zzz")

function Show-ProgressBar {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Current,

        [Parameter(Mandatory = $true)]
        [int]$Total,

        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    $percent = [math]::Round(($Current / $Total) * 100)
    $screenWidth = $Host.UI.RawUI.WindowSize.Width - 30 # Adjust for message and percentage display
    $barLength = [math]::Min($screenWidth, 80) # Limit to 80 characters, or screen width, whichever is smaller
    $filledLength = [math]::Round(($barLength * $percent) / 100)
    $emptyLength = $barLength - $filledLength

    $filledBar = ('=' * $filledLength)
    $emptyBar = (' ' * $emptyLength)

    Write-Host -NoNewline "$Message [$filledBar$emptyBar] $percent% ($Current/$Total)`r"
}

#===========================================================
#                     General functions
#===========================================================
function is_photo {
    param (
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$file
    )
    return $file.Extension -eq ".jpg"
}

function is_video {
    param (
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$file
    )
    return $file.Extension -eq ".mp4"
}

function Run_ExifToolCommand {
    param (
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$file,
        [Object[]]$arguments,
        [string]$type = "execute",
        [int]$maxRetries = 3,
        [int]$retryDelay = 10
    )

     # Ensure the file exists
     if (-not (Test-Path -Path $file.FullName)) {
        # Consider returning null or throwing an error specific to file not found
        Log "ERROR" "File not found for ExifTool command: $($file.FullName)"
        throw [System.IO.FileNotFoundException] "File not found: $($file.FullName)"
        # return # Or just return if throwing is too disruptive downstream
    }

    $fullPath  = $file.FullName       # Full path of the file

    # Build the command string and wrap it in additional quotes
    $commandArgs = @($ExifToolPath) + $arguments + @($fullPath) # Combine executable, specific args, and file path
      
    # Retry logic
    $attempt = 0
    $ExifToolOutput = $null
    while ($attempt -lt $maxRetries) {
        try {
            $attempt++
            $ExifToolOutput = & $commandArgs[0] $commandArgs[1..($commandArgs.Count-1)] 2>&1

            # Check for errors or warnings in the output
            if ($ExifToolOutput -match "Error") {
                $errorMessage = "ExifTool command returned an error: $($ExifToolOutput -join '; ')"
                throw [System.Exception]$errorMessage
            }
            if ($ExifToolOutput -match "Warning") {
                Log "WARNING" ""ExifTool command returned a warning: $($ExifToolOutput -join '; ')""
            }
            break  # Exit the loop on success
        } catch [System.Exception] {
            # Catch specific ExifTool error first
            if ($_.Exception.Message -match "ExifTool command returned an error") {
                 Log "ERROR" "ExifTool execution failed on attempt $attempt for '$fullPath'. Error: $($_.Exception.Message)"
                 if ($attempt -ge $maxRetries) { throw } # Re-throw after max retries
                 Start-Sleep -Seconds $retryDelay
            } else {
                # Catch other potential exceptions during execution
                Log "ERROR" "Unexpected error executing ExifTool on attempt $attempt for '$fullPath'. Error: $_"
                if ($attempt -ge $maxRetries) { throw } # Re-throw after max retries
                Start-Sleep -Seconds $retryDelay
            }
        }
    }
    # Process the output based on the type
    switch ($type.ToLower()) {
        "timestamp" {
            if ($ExifToolOutput -and $ExifToolOutput -ne "") {
                return Standardize_TimeStamp -InputTimestamp $ExifToolOutput
            } else {
                return Make_zero_TimeStamp
            }
        }
        "geotag" {
            if ($ExifToolOutput -and $ExifToolOutput -ne "") {
                return Standardize_GeoTag -InputGeoTag $ExifToolOutput
            } else {
                return Make_zero_GeoTag
            }
        }
        default {
            return $ExifToolOutput
        }
    }
}

#===========================================================
#                 TimeStamp functions
#===========================================================
function IsValid_TimeStamp {
    param (
        [string]$timestamp_in
    )
    if ($null -eq $timestamp_in -or $timestamp_in -eq "") {
        return $false
    }
    $output_timestamp = Standardize_TimeStamp -InputTimestamp $timestamp_in
    return $output_timestamp -ne "0001:01:01 00:00:00+00:00" -and $output_timestamp -ne "0000:00:00 00:00:00+00:00"
}

function Make_zero_TimeStamp {
    return "0001:01:01 00:00:00+00:00"
}

function Get_Exif_Timestamp {
    param (
        [System.IO.FileInfo]$File
    )
    if (-not (Test-Path $File.FullName)) {
        Verbose -message "File not found: $File" -type "error"
        return $null
    }

    $extension = $File.Extension.ToLower()
    $result_TimeStamp = Make_zero_TimeStamp

    $action = $TimeStampFields[$extension]
    if (-not $action) {
        Verbose -message "No timestamp field defined for extension: $extension" -type "warning"
        return $result_TimeStamp
    }
    $exifArgs = @("-${action}", "-s3", "-m")
    $result_TimeStamp = Run_ExifToolCommand -Arguments $exifArgs -File $File -type TimeStamp
    return $result_TimeStamp
}

function Standardize_TimeStamp {
    param (
        [Parameter(Mandatory = $true)]
        [string]$InputTimestamp,
        [string]$OutputFormat = "yyyy:MM:dd HH:mm:sszzz"
    )
    if ([string]::IsNullOrEmpty($InputTimestamp) -or $InputTimestamp.StartsWith("0000")) {
        return Make_zero_TimeStamp
    }

    $InputTimestamp = $InputTimestamp -replace 'Z$', '+00:00'
    $InputTimestamp = $InputTimestamp -replace '\s+', ' '
    $InputTimestamp = $InputTimestamp -replace ' +:', ':'
    $InputTimestamp = $InputTimestamp.Trim()

    foreach ($format in $time_formats) {
        try {
            $parsedDateTime = [datetimeoffset]::ParseExact($InputTimestamp, $format, $null)
            return $parsedDateTime.ToString($OutputFormat)
        } catch {
            # Continue to the next format if parsing fails
        }
    }
    return Make_zero_TimeStamp
}

#===========================================================
#                 GeoTagging functions
#===========================================================
function Make_zero_GeoTag {
    return "200,M,200,M"
}

function Standardize_GeoTag {
    param (
        [Parameter(Mandatory = $true)]
        [string]$InputGeoTag
    )
    $geoParts = $InputGeoTag -split ","
    if ($geoParts.Count -eq 4) {
        return $InputGeoTag
    }
    if ($geoParts.Count -eq 1) {
        return $InputGeoTag
    }
    return Make_zero_GeoTag
}

function IsValid_GeoTag {
    param (
        [Parameter(Mandatory = $true)]
        [string]$GeoTag
    )
    $geoParts = $GeoTag -split ","
    if ($geoParts.Count -ne 4) {
        return $false
    }
    try {
        $latitude = [double]($geoParts[0].Trim())
        $latitudeRef = $geoParts[1].Trim()
        $longitude = [double]($geoParts[2].Trim())
        $longitudeRef = $geoParts[3].Trim()
    } catch {
        return $false
    }
    if ($latitude -eq 200 -or $latitudeRef -eq "M" -or $longitude -eq 200 -or $longitudeRef -eq "M") {
        return $false
    }
    return $true
}

function Get_Exif_Geotag {
    param (
        [System.IO.FileInfo]$File
    )
    if (-not (Test-Path $File.FullName)) {
        Verbose -message "File not found: $File" -type "error"
        return $null
    }

    $extension = $File.Extension.ToLower()
    $result_GeoTag = Make_zero_GeoTag

    $action = $gpsFields[$extension]
    if (-not $action) {
        Verbose -message "No geotag field defined for extension: $extension" -type "warning"
        return $result_GeoTag
    }
    $exifArgs = @("-${action}", "-s3", "-m")
    $result_GeoTag = Run_ExifToolCommand -Arguments $exifArgs -File $File -type GeoTag
    return $result_GeoTag
}

#===========================================================
#                 Categorization functions
#===========================================================
function Categorize_Media_Based_On_Metadata {
    param (
        [System.IO.FileInfo]$SrcFile
    )
    $timestamp = IsValid_TimeStamp -timestamp_in $(Get_Exif_Timestamp -File $SrcFile)
    $geotag = IsValid_GeoTag -GeoTag $(Get_Exif_Geotag -File $SrcFile)

    if ($timestamp -and $geotag) {
        return "with_time_with_geo"
    } elseif ($timestamp -and -not $geotag) {
        return "with_time_no_geo"
    } elseif (-not $timestamp -and $geotag) {
        return "no_time_with_geo"
    } else {
        return "no_time_no_geo"
    }
}

function categorize_bulk_media_based_on_metadata_keep_directory_structure {
    param (
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$filePath,

        [Parameter(Mandatory = $true)]
        [System.IO.DirectoryInfo]$rootDir,

        [Parameter(Mandatory = $true)]
        [System.IO.DirectoryInfo]$targetPath
    )
    $category = Categorize_Media_Based_On_Metadata -SrcFile $filePath
    $newroot = Join-Path -Path $targetPath -ChildPath $category

    $relativePath = $filePath -replace [regex]::Escape($rootDir), ""
    $destination = Join-Path -Path $newRoot -ChildPath $relativePath
    $desiredPath = Split-Path -Path $destination
    New-Item -Path $desiredPath -ItemType Directory -Force | Out-Null

    Move-Item -Path $filePath.FullName -Destination $destination
    Verbose -message "Moved $($filePath.FullName) to $category" -type "information"
}

#===========================================================
#                 Main functions
#===========================================================
# Create src and dst subdirectories if they don't exist
$srcDirectory = New-Item -Path "$unzippeddirectory\src" -ItemType Directory -Force
$dstDirectory = New-Item -Path "$unzippeddirectory\dst" -ItemType Directory -Force

# Move ONLY the target media files into the src directory
Log "INFO" "Moving target media files (.jpg, .mp4) to $($srcDirectory.FullName)..."
Get-ChildItem -Path $unzippeddirectory -File | Where-Object { $imageExtensions -contains $_.Extension -or $videoExtensions -contains $_.Extension } | Move-Item -Destination $srcDirectory.FullName -Force
Log "INFO" "Finished moving target media files."

$files = Get-ChildItem -Path $srcDirectory.FullName -Recurse -File
$currentItem = 0
$totalItems = $files.count

# Process files in the src directory
foreach ($file in $files) {
    if ((is_photo -file $file) -or (is_video -file $file)) {
        $currentItem++
        Show-ProgressBar -Current $currentItem -Total $totalItems -Message "$zipFile"

        categorize_bulk_media_based_on_metadata_keep_directory_structure `
            -filePath $file `
            -rootDir $srcDirectory `
            -targetPath $dstDirectory
    }
}

# Check if the src directory is empty
$remainingItems = Get-ChildItem -Path $srcDirectory.FullName -Recurse
if ($remainingItems) {
    Log "WARNING" "Source directory '$($srcDirectory.FullName)' was NOT empty after processing. This might indicate non-media files were present or an error occurred."
    $remainingItems | ForEach-Object { Log "WARNING" "- Remaining item: $($_.FullName)" }
} else {
    Log "INFO" "Source directory '$($srcDirectory.FullName)' is empty as expected."
    # Remove the now-empty src directory itself
    Remove-Item -Path $srcDirectory.FullName -Force -ErrorAction SilentlyContinue
}

# --- Move categorized content from dst back to the root ---
Log "INFO" "Moving categorized folders from '$($dstDirectory.FullName)' back to '$unzippedDirectory'..."

# Get the category folders inside 'dst'
$categoryFolders = Get-ChildItem -Path $dstDirectory.FullName -Directory -ErrorAction SilentlyContinue

if ($categoryFolders) {
    foreach ($folder in $categoryFolders) {
        $destinationPath = Join-Path -Path $unzippedDirectory -ChildPath $folder.Name
        Log "INFO" "Moving '$($folder.FullName)' to '$unzippedDirectory' (will become '$destinationPath')..."
        try {
            # Move the category folder itself up one level
            Move-Item -Path $folder.FullName -Destination $unzippedDirectory -Force
        } catch {
            Log "ERROR" "Failed to move '$($folder.FullName)': $_"
        }
    }

    # --- Clean up the now empty dst directory ---
    Log "INFO" "Cleaning up the empty destination directory: $($dstDirectory.FullName)"
    try {
        # Optional: Verify it's truly empty before removing
        if (-not (Get-ChildItem -Path $dstDirectory.FullName -ErrorAction SilentlyContinue)) {
            Remove-Item -Path $dstDirectory.FullName -Force
            Log "INFO" "Successfully removed empty destination directory."
        } else {
             Log "WARNING" "Destination directory '$($dstDirectory.FullName)' was not empty after moving category folders. Manual cleanup might be required."
        }
    } catch {
        Log "ERROR" "Failed to remove destination directory '$($dstDirectory.FullName)': $_"
    }
} else {
    Log "WARNING" "No category folders found in '$($dstDirectory.FullName)' to move. The 'dst' directory might be empty or categorization failed."
    # Optionally remove the empty dst directory even if no category folders were found
    try {
        if (Test-Path $dstDirectory.FullName -PathType Container) {
             Remove-Item -Path $dstDirectory.FullName -Force -ErrorAction SilentlyContinue
             Log "INFO" "Removed potentially empty destination directory."
        }
    } catch {
         Log "ERROR" "Failed to remove destination directory '$($dstDirectory.FullName)' even though no category folders were found: $_"
    }
}

# Correct the final log message
Log "INFO" "Categorization and final move complete."