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
function Verbose {
    param(
        [string]$message,
        [string]$type
    )
    if ($verbosity -eq 1) {
        switch ($type.ToLower()) {
            "error" { Write-Error $message; exit }
            "information" { Write-Host $message -ForegroundColor Green }
            "warning" { Write-Host $message -ForegroundColor Yellow }
            default { Write-Host $message -ForegroundColor White }
        }
    }
}

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
        [Object[]] $arguments,
        [string] $type = "execute"
    )
    $fullPath = $file.FullName
    $params = $arguments -join ' '
    $command = "& $ExifToolPath $params ""$fullPath"""
    $ExifToolOutput = Invoke-Expression $command

    if ($type.ToLower() -eq "timestamp") {
        if ($null -ne $ExifToolOutput -and "" -ne $ExifToolOutput) {
            $ExifToolOutput = Standardize_TimeStamp -InputTimestamp $ExifToolOutput
        } else {
            $ExifToolOutput = Make_zero_TimeStamp
        }
    } elseif ($type.ToLower() -eq "geotag") {
        if ($null -ne $ExifToolOutput -and "" -ne $ExifToolOutput) {
            $ExifToolOutput = Standardize_GeoTag -InputGeoTag $ExifToolOutput
        } else {
            $ExifToolOutput = Make_zero_GeoTag
        }
    } else {
        $ExifToolOutput = $null
    }

    return $ExifToolOutput
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

# Move all files from the unzipped directory to the src directory
Move-Item -Path $unzippeddirectory -Destination $srcDirectory.FullName

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
