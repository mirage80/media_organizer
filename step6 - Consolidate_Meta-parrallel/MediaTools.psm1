# === Logging Utilities ===
function Get-FileHashString {
    param (
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$File
    )
    if (-not (Test-Path $File.FullName)) {
        throw "File not found: $($File.FullName)"
    }
    $hash = Get-FileHash -Path $File.FullName -Algorithm SHA256
    return $hash.Hash
}

function Load-ProcessedLog {
    if (Test-Path -Path $hashLogPath) {
        try {
            $content = Get-Content -Path $hashLogPath -Raw | ConvertFrom-Json
            if ($content -is [System.Collections.IEnumerable]) {
                return @($content)  # Already a collection
            } else {
                return @($content)  # Wrap a single object as array
            }
        } catch {
            Write-Warning "Corrupted log file. Starting fresh."
            return @()
        }
    }
    return @()
}


$logLock = New-Object System.Object

function SafeLog {
    param (
        [string]$path
    )
    $entry = @{
        path      = $path
        timestamp = (Get-Date).ToUniversalTime().ToString("o")
    }

    [System.Threading.Monitor]::Enter($logLock)
    try {
        $global:processedLog += $entry
        $global:processedLog | ConvertTo-Json -Depth 3 | Set-Content -Path $hashLogPath -Encoding UTF8
    } finally {
        [System.Threading.Monitor]::Exit($logLock)
    }
}





# === Verbose Logger ===
function Verbose {
    param(
        [string]$message,
        [string]$type,
        [int]$level = 1
    )

    switch ($type.ToLower()) {
        "error" { Write-Host $message }
        "information" { Write-Host $message -ForegroundColor Green }
        "warning" { Write-Host $message -ForegroundColor Yellow }
        default { Write-Host $message -ForegroundColor White }
    }
}

function is_photo {
    param (
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$file
    )
    $extension = $file.Extension

    # Return whether the file extension matches an image extension
    return $imageExtensions -contains $extension
}

function is_video {
    param (
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$file
    )
    $extension = $file.Extension

    # Return whether the file extension matches a video extension
    return $videoExtensions -contains $extension
}

function Standardize_GeoTag {
    param (
        [Parameter(Mandatory = $true)]
        [string]$InputGeoTag
    )
	
    $geoParts = $InputGeoTag -split ","
	
    if ($geoParts.Count -eq 4) {
		try {
			$GPSLatitude = [double]($geoParts[0].Trim())
			$GPSLatitudeRef = $geoParts[1].Trim()
			$GPSLongitude = [double]($geoParts[2].Trim())
			$GPSLongitudeRef = $geoParts[3].Trim()
		} catch {
			Verbose -message  "Error: Unable to convert '$stringValue' to a double." -type "error"
		}
        $resulted_geotag = "${GPSLatitude},${GPSLatitudeRef},${GPSLongitude},${GPSLongitudeRef}"
	} elseif ($geoParts.Count -eq 2) {	
		try {
            $GPSLatitude = Standardize_GeoTag_value -InputGeoTag $geoParts[0].Trim()
			$GPSLongitude = Standardize_GeoTag_value -InputGeoTag $geoParts[1].Trim()
			$GPSLatitudeRef = Get_LatitudeRef -latitude $GPSLatitude -LatitudeRef "N"
			$GPSLongitudeRef = Get_LongitudeRef -longitude $GPSLongitude -LongitudeRef "E"
            $GPSLatitude=$([math]::Abs($GPSLatitude)) # Absolute latitude
            $GPSLongitude=$([math]::Abs($GPSLongitude)) # Absolute longitude

		} catch {
			Verbose -message  "Error: Unable to convert '$stringValue' to a double." -type "error"
		}
        $resulted_geotag = "${GPSLatitude},${GPSLatitudeRef},${GPSLongitude},${GPSLongitudeRef}"
	} elseif ($geoParts.Count -eq 1) {	
		try {
            $GPSLatitude = 200
			$GPSLongitude = 200
			$GPSLatitudeRef = "M"
			$GPSLongitudeRef = "M"
            $geotag=$geoParts[0].Trim()
            $resulted_geotag =Standardize_GeoTag_value -InputGeoTag $geotag
		} catch {
			Verbose -message  "Error: Unable to convert '$stringValue' to a double." -type "error"
		}
	} else {
        Verbose -message  "Error: Unable to convert '$stringValue' to a double." -type "error"
    }    
	return $resulted_geotag
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
        return
    }

    $fullPath  = $file.FullName       # Full path of the file
    $argument_mix = $arguments -replace '^(?:"([^"]*)="([^"]*)"|([^"]*)="([^"]*))$', '$1$3="$2$4"'

    # Build the command string and wrap it in additional quotes
    $params = $argument_mix -join ' '
    $command = "& $ExifToolPath $params '$fullPath'"

    # Execute the command string
        
    # Retry logic
    $attempt = 0
    $ExifToolOutput = $null
    while ($attempt -lt $maxRetries) {
        try {
            $attempt++
            $ExifToolOutput = Invoke-Expression $command 2>&1

            # Check for errors or warnings in the output
            if ($ExifToolOutput -match "Error") {
                $errorMessage = "ExifTool command returned an error: $($ExifToolOutput -join '; ')"
                throw [System.Exception]$errorMessage
            }
            if ($ExifToolOutput -match "Warning") {
                Verbose -message "ExifTool command returned a warning: $($ExifToolOutput -join '; ')" -type "warning"
            }
            break  # Exit the loop on success
        } catch [System.IO.FileNotFoundException] {
            $errorMessage = "ExifTool command failed: ExifTool not found. Error: $_"
            Verbose -message $errorMessage -type "error"
            throw
        } catch [System.Exception] {
            if ($attempt -ge $maxRetries) {
                $errorMessage = "Failed to execute ExifTool command after $maxRetries attempts. Error: $_"
                Verbose -message $errorMessage -type "error"
                throw
            }
            Start-Sleep -Seconds $retryDelay
        } catch {
            $errorMessage = "An unexpected error occurred: $_"
            Verbose -message $errorMessage -type "error"
            throw
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


function IsValid_GeoTag {
    param (
        [Parameter(Mandatory = $true)]
        [string]$GeoTag
    )

    # Validate input
    if ([string]::IsNullOrEmpty($GeoTag)) {
        $errorMessage = "GeoTag is null or empty."
        Verbose -message $errorMessage -type "warning"
        throw [System.ArgumentNullException]$errorMessage
    }

    # Split the GeoTag into parts
    $geoParts = $GeoTag -split ","
    if ($geoParts.Count -ne 4) {
        $errorMessage = "Invalid GeoTag format: $GeoTag"
        Verbose -message $errorMessage -type "warning"
        throw [System.FormatException]$errorMessage
    }

    try {
        # Parse latitude and longitude
        $latitude = [double]($geoParts[0].Trim())
        $latitudeRef = $geoParts[1].Trim().ToUpper()
        $longitude = [double]($geoParts[2].Trim())
        $longitudeRef = $geoParts[3].Trim().ToUpper()

        # Validate latitude and longitude ranges
        if (($latitude -lt -90 -or $latitude -gt 90) -or ($longitude -lt -180 -or $longitude -gt 180)) {
            $errorMessage = "Latitude or longitude is out of range: $GeoTag"
            Verbose -message $errorMessage -type "warning"
            throw [System.ArgumentOutOfRangeException]$errorMessage
        }

        # Validate latitude and longitude references
        if (($latitudeRef -ne "N" -and $latitudeRef -ne "S") -or ($longitudeRef -ne "E" -and $longitudeRef -ne "W")) {
            $errorMessage = "Invalid latitude or longitude reference: $GeoTag"
            Verbose -message $errorMessage -type "warning"
            throw [System.FormatException]$errorMessage
        }
    } catch [System.FormatException] {
        Verbose -message "Failed to parse GeoTag: $GeoTag. Error: $_" -type "error"
        throw
    } catch [System.ArgumentOutOfRangeException] {
        Verbose -message "Failed to parse GeoTag: $GeoTag. Error: $_" -type "error"
        throw
    } catch {
        $errorMessage = "An unexpected error occurred: $_"
        Verbose -message $errorMessage -type "error"
        throw
    }

    # If all checks pass, the GeoTag is valid
    return $true
}


function Make_zero_GeoTag {
    return "200,M,200,M"
}

function IsValid_TimeStamp {
    param (
        [string]$timestamp_in
    )

    # Check if the input timestamp is null or empty
    if ([string]::IsNullOrEmpty($timestamp_in)) {
        $errorMessage = "Timestamp is null or empty."
        throw [System.ArgumentNullException]$errorMessage
    }

    # Standardize the timestamp
    try {
        $output_timestamp = Standardize_TimeStamp -InputTimestamp $timestamp_in
    } catch {
        Verbose -message "Failed to standardize timestamp: $timestamp_in. Error: $_" -type "error"
        throw
    }

    # Check if the standardized timestamp is valid
    if ($output_timestamp -eq "0001:01:01 00:00:00+00:00" -or $output_timestamp -eq "0000:00:00 00:00:00+00:00") {
        $errorMessage = "Timestamp is invalid: $output_timestamp"
        throw [System.FormatException]$errorMessage
    }

    return $true
}

function Normalize_Directions_In_String {
    param (
        [string]$inputString
    )

    # Define a hashtable for mapping directions
    $directionMap = @{
        "north" = "N"
        "n"     = "N"
        "south" = "S"
        "s"     = "S"
        "east"  = "E"
        "e"     = "E"
        "west"  = "W"
        "w"     = "W"
    }

    # Iterate through the hashtable and replace matches
    foreach ($key in $directionMap.Keys) {
        $inputString = $inputString -replace "(?i)\b$key\b", $directionMap[$key]
    }

    return $inputString
}

function ParseToDecimal {
    param (
        [Parameter(Mandatory = $true)][string]$geoTag,
        [Parameter(Mandatory = $true)][string]$direction
    )

    $geoTag = $geoTag -replace '>', '"'

    # Match DMS format
    if ($geoTag -match "(\d+)\s*deg\s*(\d+)'\s*(\d+(\.\d+)?)""") {
        $degrees = [double]$matches[1]
        $minutes = [double]$matches[2]
        $seconds = [double]$matches[3]

        # Convert DMS to decimal
        $decimal = $degrees + ($minutes / 60) + ($seconds / 3600)

        # Adjust sign based on direction
        switch ($direction) {
            "S" { return -$decimal }
            "W" { return -$decimal }
            default { return $decimal }
        }
    } else {
        $errorMessage = "Invalid coordinate format: $geoTag"
        Verbose -message $errorMessage -type "error"
        throw [System.FormatException]$errorMessage
    }
}

function Get_LatitudeRef {
    param (
        [double]$latitude,
		[string]$LatitudeRef
    )
	if ( $latitude -eq 200 ) {
		return $LatitudeRef
	}
	if ($LatitudeRef -eq "M") 
	{
		if ($latitude -ge 0) {
			return "N"  # North for positive values
		} else {
			return "S"  # South for negative values
		}
	}
	elseif ($latitude -ge 0) {
		return $LatitudeRef  # North for positive values
	} elseif ($LatitudeRef -eq "N") {
		return "S"  # South for negative values
	} else {
		return "N"  # North for other cases
	}
}

function Get_LongitudeRef {
    param (
        [double]$longitude,
		[string]$LongitudeRef
    )
	if ( $longitude -eq 200 ) {
		return $LongitudeRef
	}
	if ($LongitudeRef -eq "M") 
	{
		if ($longitude -ge 0) {
			return "E"  # North for positive values
		} else {
			return "W"  # South for negative values
		}
	}
	elseif ($longitude -ge 0) {
		return $LongitudeRef  # North for positive values
	} elseif ($LongitudeRef -eq "E") {
		return "W"  # South for negative values
	} else {
		return "E"  # North for other cases
	}
}

function Get-TimeZoneOffset {
    param (
        [string]$timeZoneAbbreviation
    )
    # Common mapping for known abbreviations
    $timeZoneMap = @{
        "UTC" = "UTC"
        "Z"   = "UTC"
        "PST" = "Pacific Standard Time"
        "PDT" = "Pacific Daylight Time"
        "EST" = "Eastern Standard Time"
        "EDT" = "Eastern Daylight Time"
        "CST" = "Central Standard Time"
        "CDT" = "Central Daylight Time"
    }

    # Find full time zone name
    if ($timeZoneMap.ContainsKey($timeZoneAbbreviation)) {
        $timeZoneName = $timeZoneMap[$timeZoneAbbreviation]
        $timeZoneInfo = [System.TimeZoneInfo]::FindSystemTimeZoneById($timeZoneName)
        $baseUtcOffset = $timeZoneInfo.BaseUtcOffset

        # Format the offset as +HH:mm or -HH:mm
        $formattedOffset = "{0:+00;-00}:{1:D2}" -f $baseUtcOffset.Hours, $baseUtcOffset.Minutes
        return $formattedOffset
    } else {
        return "+00:00" # Default to UTC if not found
    }
}

function Make_zero_TimeStamp {
    # Return a default invalid timestamp
    # Format: "yyyy:MM:dd HH:mm:ss+00:00"
    return "0001:01:01 00:00:00+00:00"
}

function Compare_TimeStamp {
    param (
        [string]$timestamp1,
        [string]$timestamp2
    )

    # Trim strings
    $timestamp1 = $timestamp1.Trim()
    $timestamp2 = $timestamp2.Trim()

    # Initialize the result with a default invalid timestamp
    $result_TimeStamp = Make_zero_TimeStamp

    # Handle special cases with default values
    $isValidTimestamp1 = try {
        IsValid_TimeStamp -timestamp_in $timestamp1
    } catch {
        $false
    }
    $isValidTimestamp2 = try {
        IsValid_TimeStamp -timestamp_in $timestamp2
    } catch {
        $false
    }

    if ($isValidTimestamp1 -and -not $isValidTimestamp2) {
        $result_TimeStamp = $timestamp1
    } elseif (-not $isValidTimestamp1 -and $isValidTimestamp2) {
        $result_TimeStamp = $timestamp2
    } elseif ($isValidTimestamp1 -and $isValidTimestamp2) {
        # Compare valid timestamps
        if ($timestamp1 -lt $timestamp2) {
            $result_TimeStamp = $timestamp1
        } else {
            $result_TimeStamp = $timestamp2
        }
    } else {
        return $null # Both timestamps are invalid
    }

    # Return the result
    return $result_TimeStamp
}

function Get_Json_TimeStamp {
    param (
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$JsonFile
    )

    # Check if the JSON file exists
    if (-not (Test-Path -Path $JsonFile.FullName)) {
        $errorMessage = "JSON file not found: $($JsonFile.FullName)"
        Verbose -message $errorMessage -type "error"
        throw [System.IO.FileNotFoundException]$errorMessage
    }

    # Load and parse the JSON file
    try {
        $jsonContent = Get-Content -Path $JsonFile.FullName | ConvertFrom-Json
    } catch {
        $errorMessage = "Failed to read or parse JSON file: $($JsonFile.FullName). Error: $_"
        Verbose -message $errorMessage -type "error"
        throw [System.FormatException]$errorMessage
    }

    # Extract timestamps from the JSON content
    try {
        $creationDate = Standardize_TimeStamp -InputTimestamp $jsonContent.creationTime?.formatted
    } catch {
        Verbose -message "Failed to standardize creationTime timestamp from JSON file: $($JsonFile.FullName). Error: $_" -type "error"
        throw
    }
    try {
        $photoTakenDate = Standardize_TimeStamp -InputTimestamp $jsonContent.photoTakenTime?.formatted
    } catch {
        Verbose -message "Failed to standardize photoTakenTime timestamp from JSON file: $($JsonFile.FullName). Error: $_" -type "error"
        throw
    }

    # Compare and return the most appropriate timestamp
    $result = Compare_TimeStamp -timestamp1 $creationDate -timestamp2 $photoTakenDate

    if (-not $result -or $result -eq $(Make_zero_TimeStamp)) {
        Verbose -message "Failed to standardize photoTakenTime timestamp from JSON file: $($JsonFile.FullName). Error: $_" -type "error"
        throw
    }
    return $result
}

function Get_Exif_Timestamp {
    param (
        [System.IO.FileInfo]$File
    )

    # Ensure the file exists
    if (-not (Test-Path $File.FullName)) {
        $errorMessage = "File not found: $($File.FullName)"
        Verbose -message $errorMessage -type "error"
        throw [System.IO.FileNotFoundException]$errorMessage
    }

    # Get the file extension in lowercase
    $extension = $File.Extension.ToLower()

    # Get timestamp fields for the given extension
    $actions = Get_Field_By_Extension -Extension $extension -FieldDictionary $TimeStampFields
    if (-not $actions -or $actions.Count -eq 0) {
        $errorMessage = "No timestamp fields defined for extension: $extension"
        Verbose -message $errorMessage -type "error"
        throw [System.IO.FileNotFoundException]$errorMessage
    }

    # Execute ExifTool commands for each action
    $result_TimeStamp = $null
    foreach ($action in $actions) {
        $exifArgs = @("-${action}", "-s3", "-m")
        try {
            $temp_TimeStamp = Run_ExifToolCommand -Arguments $exifArgs -File $File -type "timestamp"
        } catch {
            $Message = "Failed to retrieve timestamp from Exif metadata for file: $($File.FullName)."
            throw [System.IO.FileNotFoundException]$Message
        }
        $result_TimeStamp = Compare_TimeStamp -timestamp1 $result_TimeStamp -timestamp2 $temp_TimeStamp
    }

    # Return the final timestamp or defaulttimestamp if invalid
    if (-not $result_TimeStamp -or $result_TimeStamp -eq $(Make_zero_TimeStamp)) {
        $Message = "Failed to retrieve timestamp from Exif metadata for file: $($File.FullName)."
        throw [System.IO.FileNotFoundException]$Message
    }
    return $result_TimeStamp
}

function Verbose {
    param(
        [string]$message,
        [string]$type,
        [int]$level = 1
    )

    if ($verbosity -ge $level) {
        switch ($type.ToLower()) {
            "error" {
                Write-Host $message
            }
            "information" {
                Write-Host $message -ForegroundColor Green
            }
            "warning" {
                Write-Host $message -ForegroundColor Yellow
            }
            default {
                Write-Host $message -ForegroundColor White
            }
        }
    }
}

function Find_and_Write_Valid_Timestamp {
    param (
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$File  # The media file path (image or video)
    )

    # Get the full path of the file
    $fullPath = $File.FullName
    $JsonPath = "${fullPath}.json"

    # Initialize timestamps
    $filenameTimestamp = $null
    $jsonTimestamp = $null
    $exifTimestamp = $null

    # Get the timestamp from the filename
    try {
        $filenameTimestamp = Parse_DateTimeFromFilename -FilePath $File
        Verbose -message "Extracted TimeStamp from FileName: $filenameTimestamp" -type "information"
    } catch {
        Verbose -message "Failed to retrieve timestamp from filename for file: $($file.basename)" -type "warning"
    }

    # Get the timestamp from the JSON metadata if the JSON file exists
    if (Test-Path -Path $JsonPath) {
        try {
            $JsonFile = [System.IO.FileInfo]$JsonPath
            $jsonTimestamp = Get_Json_TimeStamp -JsonFile $JsonFile
            Verbose -message "Extracted TimeStamp from JSON: $jsonTimestamp" -type "information"
        } catch {
            Verbose -message "Failed to retrieve timestamp from JSON file:  $($file.basename)" -type "warning"
        }
    } else {
        Verbose -message "There is no JSON file" -type "warning"
    }

    # Get the timestamp from the Exif metadata
    try {
        $exifTimestamp = Get_Exif_Timestamp -File $File
        Verbose -message "Extracted TimeStamp from EXIF: $exifTimestamp" -type "information"
    } catch {
        Verbose -message "Failed to retrieve timestamp from Exif metadata for file:  $($file.basename)" -type "warning"
    }

    # Compare the timestamps and determine the earliest valid timestamp
    $earliestTimestamp = Compare_TimeStamp -timestamp1 $filenameTimestamp -timestamp2 $jsonTimestamp
    $earliestTimestamp = Compare_TimeStamp -timestamp1 $earliestTimestamp -timestamp2 $exifTimestamp

    # Check if the earliest timestamp is valid
    if ($earliestTimestamp -and (IsValid_TimeStamp -timestamp_in $earliestTimestamp)) {
        # Check if the timestamp is before 1970
        $parsedDate = [datetime]::ParseExact($earliestTimestamp, "yyyy:MM:dd HH:mm:sszzz", $null)
        if ($parsedDate -lt [datetime]"1970-01-01") {
            # Prompt the user for confirmation
            yes
            yes$userInput = Read-Host "The timestamp $earliestTimestamp is before 1970. Do you want to use it? (yes/no)"
            if ($userInput -ne "yes") {
                Verbose -message "User rejected the timestamp $earliestTimestamp for file: $fullPath" -type "warning"
                return $null
            }
        }

        # Write the timestamp to the file
        try {
            Write_TimeStamp -File $File -TimeStamp $earliestTimestamp
            return $earliestTimestamp
        } catch {
            throw [System.IO.FileNotFoundException]$Message
        }
    } else {
        throw [System.IO.FileNotFoundException]$Message
    }
}

function Find_and_Write_Valid_GeoTag {
    param (
        [System.IO.FileInfo]$File
    )

    # Get the full path of the file
    $fullPath = $File.FullName
    $JsonPath = "${fullPath}.json"

    # Initialize geotags
    $Json_geotag = $null
    $Exif_geotag = $null

    # Get the geotag from the JSON metadata if the JSON file exists
    if (Test-Path -Path $JsonPath) {
        try {
            $JsonFile = [System.IO.FileInfo]$JsonPath
            $Json_geotag = Get_Json_Geotag -JsonFile $JsonFile
            Verbose -message "Extracted GeoTag from JSON: $Json_geotag" -type "information"
        } catch {
            Verbose -message "Failed to retrieve geotag from JSON file: $JsonPath." -type "warning"
        }
    } else {
        Verbose -message "There is no JSON file" -type "warning"
    }

    # Get the geotag from the Exif metadata
    try {
        $Exif_geotag = Get_Exif_Geotag -File $File
        Verbose -message "Extracted GeoTag from EXIF: $Json_geotag" -type "information"
    } catch {
        Verbose -message "Failed to retrieve geotag from Exif metadata for file: $($File.basename)" -type "warning"
    }

    # Compare the geotags and determine the final geotag
    if ( $Exif_geotag -and $Json_geotag) {
        $FinalGeoTag = Compare_Geotag -geotag1 $Exif_geotag -geotag2 $Json_geotag
    } elseif ($Exif_geotag) {
        $FinalGeoTag = $Exif_geotag
    } elseif ($Json_geotag) {
        $FinalGeoTag = $Json_geotag
    } else {
        return
    }

    # If a valid geotag is found, write it
    if ($FinalGeoTag -and (IsValid_GeoTag -GeoTag $FinalGeoTag)) {
        try {
            Write_Geotag -File $File -GeoTag $FinalGeoTag
            return $FinalGeoTag
        } catch {
        }
    } else {
        Verbose -message "No valid geotag found for $fullPath" -type "warning"
    }
}

function Parse_DateTimeFromFilename {
    param (
        [System.IO.FileInfo]$FilePath
    )

    $filename = $FilePath.BaseName  # File name without extension

    # Iterate through patterns to extract date and time
    foreach ($pattern in $patterns) {
        if ($filename -match $pattern) {
            $date = $matches['date']
            $time = $matches['time']

            # Handle missing date or time
            if ([string]::IsNullOrEmpty($date) -or [string]::IsNullOrEmpty($time)) {
                continue
            }

            # Normalize date formats
            $formattedDate = switch ($true) {
                ($date -match '\d{8}') { $date.Substring(0, 4) + ":" + $date.Substring(4, 2) + ":" + $date.Substring(6, 2) }
                ($date -match '\d{2}-\d{2}-\d{4}') { $date.Substring(6, 4) + ":" + $date.Substring(3, 2) + ":" + $date.Substring(0, 2) }
                ($date -match '\d{4}-\d{2}-\d{2}') { $date -replace '-', ':' }
                default {
                    Verbose -message "Date format not recognized: $date" -type "warning"
                    continue
                }
            }

            # Normalize time formats
            $formattedTime = switch ($true) {
                ($time -match '\d{6}') { $time.Substring(0, 2) + ":" + $time.Substring(2, 2) + ":" + $time.Substring(4, 2) }
                ($time -match '\d{2}-\d{2}-\d{2}') { $time -replace '-', ':' }
                ($time -match '\d{2}:\d{2}:\d{2}') { $time }
                default {
                    Verbose -message "Time format not recognized: $time. Defaulting to 00:00:00." -type "warning"
                    "00:00:00"
                }
            }

            # Combine date and time
            $formattedDateTime = "$formattedDate $formattedTime"

            # Validate the combined date-time using $time_formats
            foreach ($format in $time_formats) {
                try {
                    $parsedDateTime = [datetimeoffset]::ParseExact($formattedDateTime, $format, $null)
                    return $parsedDateTime.ToString("yyyy:MM:dd HH:mm:sszzz")  # Return standardized format
                } catch {
                    # Continue to the next format if parsing fails
                }
            }
        } else {
        }
    }

    # Log if no match was found
    throw [System.FormatException] "No valid date-time found in filename: $filename"
}

function Write_TimeStamp {
    param (
        [System.IO.FileInfo]$File,
        [string]$TimeStamp
    )

    $fullPath = $File.FullName  # Full path of the file

    # Ensure the file exists
    if (-not (Test-Path -Path $fullPath)) {
        $errorMessage = "File does not exist: $fullPath"
        Verbose -message $errorMessage -type "error"
        throw [System.IO.FileNotFoundException]$errorMessage
    }

    $extension = $File.Extension.ToLower()  # File extension (including the leading dot)

    # Validate the timestamp
    if ([string]::IsNullOrEmpty($TimeStamp)) {
        $errorMessage = "No Timestamp provided."
        Verbose -message $errorMessage -type "error"
        throw [System.ArgumentNullException]$errorMessage
    }

    if (-not (IsValid_TimeStamp -timestamp_in $TimeStamp)) {
        $errorMessage = "Invalid Timestamp provided: $TimeStamp"
        Verbose -message $errorMessage -type "error"
        throw [System.FormatException]$errorMessage
    }

    # Get actions for the given extension
    $actions = Get_Field_By_Extension -Extension $extension -FieldDictionary $TimeStampFields

    if ($actions.Count -eq 0) {
        Verbose -message "No actions to execute for extension: $extension" -type "warning"
        return
    }

    # Construct ExifTool arguments
    $exifArgs = @(
        $actions | ForEach-Object { "-${_}=`'${TimeStamp}`'" }
    )
    $exifArgs += "-s3"
    $exifArgs += "-m"
    $exifArgs += "-overwrite_original"  # Overwrite the original image file

    # Run ExifTool command
    try {
        Run_ExifToolCommand -Arguments $exifArgs -File $File
    } catch {
        throw
    }
}

function Update-FileMetadata {
    param(
        [System.IO.FileInfo]$File
    )
    try {
        $FinalTimestamp = Find_and_Write_Valid_Timestamp -File $File
        Verbose -message "Successfully wrote timestamp $($FinalTimestamp[1])" -type "information"
    } catch {
        Verbose -message "Failed to write timestamp for file: $($File.basename)." -type "warning"
    }
    try {
        $FinalGeoTag = Find_and_Write_Valid_GeoTag -File $File
        Verbose -message "Successfully wrote GeoTag $($FinalGeoTag[1])" -type "information"
    } catch {
        Verbose -message "Failed to write geotag for file: $($File.basename)." -type "warning"
    }
}

function Move-FileToDestination {
    param(
        [System.IO.FileInfo]$File,
        [System.IO.DirectoryInfo]$SrcRoot,
        [System.IO.DirectoryInfo]$DestRoot
    )
    # Calculate the relative path
    $relativePath = $File.FullName -replace [regex]::Escape($SrcRoot.FullName), ""
    $relativePath = $relativePath.TrimStart("\\")

    # Combine the new root with the relative path
    $destination = Join-Path -Path $DestRoot.FullName -ChildPath $relativePath

    # Ensure the destination directory exists
    try {
        $desiredPath = Split-Path -Path $destination
        if (!(Test-Path -Path $desiredPath -PathType Container)) {
            New-Item -Path $desiredPath -ItemType Directory -Force | Out-Null
            Verbose -message "Created destination directory: $desiredPath" -type "information"
        }
    } catch {
        $errorMessage = "Failed to create destination directory: $desiredPath. Error: $_"
        Verbose -message $errorMessage -type "error"
        throw [System.IO.DirectoryNotFoundException]$errorMessage
    }

    # Move the file to the destination directory
    try {
        Move-Item -Path $File.FullName -Destination $destination
        Verbose -message "Successfully moved file to: $destination" -type "information"
    } catch {
        $errorMessage = "Failed to move file: $($File.FullName). Error: $_"
        Verbose -message $errorMessage -type "error"
        throw
    }
}

function Consolidate_Json_Exif_Data {
    param (
        [System.IO.FileInfo]$File
    )
    try {
        Update-FileMetadata -File $File
    } catch {
        Verbose -message "Failed to update metadata for file: $($File.FullName). Error: $_" -type "error"
        throw
    }
}

function Get_Json_Geotag {
    param (
        [System.IO.FileInfo]$JsonFile
    )

    # Check if the JSON file exists
    if (-not (Test-Path -Path $JsonFile.FullName)) {
        $errorMessage = "JSON file not found: $($JsonFile.FullName)"
        Verbose -message $errorMessage -type "error"
        throw [System.IO.FileNotFoundException]$errorMessage
    }

    # Load the JSON file
    try {
        $jsonContent = Get-Content -Path $JsonFile.FullName | ConvertFrom-Json
    } catch {
        $errorMessage = "Failed to read or parse JSON file: $($JsonFile.FullName). Error: $_"
        Verbose -message $errorMessage -type "error"
        throw [System.FormatException]$errorMessage
    }

    # Extract latitude and longitude
    $latitude = $jsonContent.geoData?.latitude
    $longitude = $jsonContent.geoData?.longitude

    if ($latitude -and $longitude) {
        # Standardize and return the geotag
        return Standardize_GeoTag -InputGeoTag "${latitude}, ${longitude}"
    } else {
        Verbose -message "GeoData is missing or incomplete in JSON file: $($JsonFile.FullName)" -type "warning"
        return $null
    }
}

function Standardize_TimeStamp {
    param (
        [Parameter(Mandatory = $true)]
        [string]$InputTimestamp,
        [string]$OutputFormat = "yyyy:MM:dd HH:mm:sszzz" # Desired output format
    )

    # Default value for invalid or null timestamps
    $standardTimestamp = Make_zero_TimeStamp

    # Step 1: Handle null or empty input
    if ([string]::IsNullOrEmpty($InputTimestamp) -or $InputTimestamp.StartsWith("0000")) {
        return $standardTimestamp
    }

    # Step 2: Detect non-ASCII characters
    if ($InputTimestamp -match '[^\u0000-\u007F]') {
        $InputTimestamp = $InputTimestamp -replace '[^\u0000-\u007F]', ''
    }

    # Step 3: Handle UTC `Z` suffix
    if ($InputTimestamp -match 'Z$') {
        $InputTimestamp = $InputTimestamp -replace 'Z$', '+00:00'
    }

    # Step 4: Extract and remove time zone abbreviation
    $timeZoneAbbreviation = $null
    if ($InputTimestamp -match '\s([A-Z]{2,4})$') {
        $timeZoneAbbreviation = $matches[1]
        $InputTimestamp = $InputTimestamp -replace '\s[A-Z]{2,4}$', '' # Remove the abbreviation
    }

    # Step 5: Remove invalid `00:00:00` offset
    if ($InputTimestamp -match '\s00:00:00$') {
        Verbose -message "Removing invalid '00:00:00' offset from timestamp: $InputTimestamp" -type "information"
        $InputTimestamp = $InputTimestamp -replace '\s00:00:00$', ''
    }

    # Step 6: Normalize spaces and delimiters
    $InputTimestamp = $InputTimestamp -replace '\s+', ' '        # Normalize multiple spaces
    $InputTimestamp = $InputTimestamp -replace ' +:', ':'        # Remove spaces before colons
    $InputTimestamp = $InputTimestamp.Trim()                    # Trim leading/trailing whitespace

    # Step 7: Get UTC offset from the time zone abbreviation using Get-TimeZoneOffset
    $zzzFormat = "+00:00" # Default offset if no abbreviation is found
    if ($timeZoneAbbreviation) {
        try {
            $zzzFormat = Get-TimeZoneOffset -timeZoneAbbreviation $timeZoneAbbreviation
        } catch {
            Verbose -message "Invalid or unrecognized time zone abbreviation: $timeZoneAbbreviation. Using default offset '+00:00'." -type "warning"
        }
    }

    # Step 8: Check for Offset Presence
    if (-not ($InputTimestamp -match "(\+|-)\d{2}:\d{2}$")) {
        $InputTimestamp = "$InputTimestamp$zzzFormat" # Explicitly append offset
    }

    # Step 9: Parse the timestamp
    foreach ($format in $time_formats) {
        try {
            $parsedDateTime = [datetimeoffset]::ParseExact($InputTimestamp, $format, $null)
            $standardTimestamp = $parsedDateTime.ToString($OutputFormat)
            return $standardTimestamp
        } catch {
            # Continue to the next format if parsing fails
        }
    }

    # Log if parsing fails for all formats
    $errorMessage = "Failed to parse the input timestamp: $InputTimestamp. Returning default invalid timestamp."
    Verbose -message $errorMessage -type "warning"
    throw [System.FormatException]$errorMessage
}

function Standardize_GeoTag_value {
    param (
        [Parameter(Mandatory = $true)]
        [string]$InputGeoTag
    )

    # Normalize direction strings
    $sanitizedInputGeoTag = Normalize_Directions_In_String -inputString $InputGeoTag

    # Remove unescaped double quotes
    $sanitizedInputGeoTag = $sanitizedInputGeoTag -replace '"', '>'

    # Handle single direction (e.g., "N", "S", "E", "W")
    if ($sanitizedInputGeoTag -match "^[NSEW]$") {
        return $sanitizedInputGeoTag
    }

    # Handle coordinate with direction (e.g., "45.123 N")
    if ($sanitizedInputGeoTag -match "(.+?)\s*([NSEW])$") {
        try {
            $coordinate = $matches[1].Trim()
            $direction = $matches[2].ToUpper()
            return ParseToDecimal -geoTag $coordinate -direction $direction
        } catch {
            $errorMessage = "Error during decimal conversion for geotag: $sanitizedInputGeoTag. Error: $_"
            Verbose -message $errorMessage -type "error"
            throw
        }
    }

    # Handle decimal format (e.g., "45.123")
    if ($sanitizedInputGeoTag -match "^[+-]?\d+(\.\d+)?$") {
        try {
            return [double]$sanitizedInputGeoTag
        } catch {
            $errorMessage = "Error converting geotag to decimal: $sanitizedInputGeoTag. Error: $_"
            Verbose -message $errorMessage -type "error"
            throw
        }
    }

    # Handle degrees, minutes, seconds format (e.g., "45 deg 30' 15.5\"")
    if ($sanitizedInputGeoTag -match "(\d+)\s*deg\s*(\d+)'\s*(\d+(\.\d+)?)>") {
        try {
            $degrees = [double]$matches[1]
            $minutes = [double]$matches[2]
            $seconds = [double]$matches[3]
            return $degrees + ($minutes / 60) + ($seconds / 3600)
        } catch {
            $errorMessage = "Error parsing degrees, minutes, seconds format: $sanitizedInputGeoTag. Error: $_"
            Verbose -message $errorMessage -type "error"
            throw
        }
    }

    # Log and throw error for invalid format
    $errorMessage = "Invalid geotag format: $InputGeoTag"
    Verbose -message $errorMessage -type "error"
    throw [System.FormatException]$errorMessage
}

function AddFields_GeoTags {
    param (
        [string]$current_geotag,
        [string[]]$fields,
        [string[]]$values
    )

    $result_GeoTag = Make_zero_GeoTag
    $GPS_valid = $true
    $pos_valid = $true
    $zero_GeoTag = Make_zero_GeoTag

    for ($i = 0; $i -lt $fields.Count; $i++) {
        $field = $fields[$i]
        $value = $values[$i]

        # Validate field and value
        # Update the appropriate field
        switch ($field) {
            "GPSLatitudeRef" {
               if (-not $value -or $value -eq "" -or $value -eq $zero_GeoTag) {
                    $GPS_valid=$false
                } else {
                    $value = Normalize_Directions_In_String -inputString $value
                    if ($value -eq "N" -or $value -eq "S") {
                        $GPSLatitudeRef = $value
                    }  else {
                        $errorMessage = "Invalid LatitudeRef value: $value"
                        Verbose -message $errorMessage -type "error"
                        throw [System.FormatException]$errorMessage
                    }
                }
            }
            "GPSLatitude" {
                if (-not $value -or $value -eq "" -or $value -eq $zero_GeoTag) {
                    $GPS_valid=$false
                } else {
                    $value = Standardize_GeoTag_value -InputGeoTag $value
                    try {
                        $GPSLatitude = [double]$value
                    } catch {
                        $errorMessage = "Error: Unable to convert '$value' to a valid latitude."
                        Verbose -message $errorMessage -type "error"
                        throw [System.FormatException]$errorMessage
                    }
                }
            }
            "GPSLongitudeRef" {
                if (-not $value -or $value -eq "" -or $value -eq $zero_GeoTag) {
                    $GPS_valid=$false
                } else {
                    $value = Normalize_Directions_In_String -inputString $value
                    if ($value -eq "E" -or $value -eq "W") {
                        $GPSLongitudeRef = $value
                    } else {
                        $errorMessage = "Invalid LongitudeRef value: $value"
                        Verbose -message $errorMessage -type "error"
                        throw [System.FormatException]$errorMessage
                    }
                }                    
            }
            "GPSLongitude" {
                if (-not $value -or $value -eq "" -or $value -eq $zero_GeoTag) {
                    $GPS_valid=$false
                } else {
                    $value = Standardize_GeoTag_value -InputGeoTag $value
                    try {
                        $GPSLongitude = [double]$value
                    } catch {
                        $errorMessage = "Error: Unable to convert '$value' to a valid longitude."
                        Verbose -message $errorMessage -type "error"
                        throw [System.FormatException]$errorMessage
                    }
                }
            }
            "GPSPosition" {
                if (-not $value -or $value -eq "" -or $value -eq $zero_GeoTag) {
                    $pos_valid=$false
                } else {
                    $geoParts = $value -split ","
                    try {
                        $GPSLatitude_pos = $([math]::Abs([double]($geoParts[0].Trim())))
                        $GPSLatitudeRef_pos = $geoParts[1].Trim()
                        $GPSLongitude_pos = $([math]::Abs([double]($geoParts[2].Trim())))
                        $GPSLongitudeRef_pos = $geoParts[3].Trim()
                    } catch {
                        $errorMessage = "Error: Unable to parse GPSPosition value: $value. Error: $_"
                        throw [System.FormatException]$errorMessage
                    }
                }
            }
            default {
                Verbose -message "Unknown field: $field. No changes made." -type "warning"
            }
        }
    }

    if ( $GPS_valid ){
        # Calculate latitude and longitude references
        if (($GPSLatitudeRef -eq "S" -and $GPSLatitude -gt 0) -or
            ($GPSLatitudeRef -eq "N" -and $GPSLatitude -lt 0) -or
            ($GPSLongitudeRef -eq "W" -and $GPSLongitude -gt 0) -or
            ($GPSLongitudeRef -eq "E" -and $GPSLongitude -lt 0) ) 
        {
            $errorMessage = "Error: Invalid GPSPosition value: $value. Latitude and Longitude references do not match."
            throw [System.FormatException]$errorMessage
        }
        $GPSLatitude = $([math]::Abs($GPSLatitude)) # Absolute latitude
        $GPSLongitude = $([math]::Abs($GPSLongitude)) # Absolute longitude
    }

    if ($pos_valid -and $GPS_valid) {
        if ($GPSLatitude -eq $GPSLatitude_pos -and $GPSLongitude -eq $GPSLongitude_pos -and $GPSLatitudeRef -eq $GPSLatitudeRef_pos -and $GPSLongitudeRef -eq $GPSLongitudeRef_pos) {
            # No changes needed, as the geotag is already valid
            $Result_GeoTag = "${GPSLatitude},${GPSLatitudeRef},${GPSLongitude},${GPSLongitudeRef}"
        } else {
            $errorMessage = "Error: MisMatch between GPSPosition value & GPS values."
            throw [System.FormatException]$errorMessage
        }
    } elseif (-not $pos_valid -and $GPS_valid) {
        $Result_GeoTag = "${GPSLatitude},${GPSLatitudeRef},${GPSLongitude},${GPSLongitudeRef}"
    } elseif ($pos_valid -and -not $GPS_valid) {
        $Result_GeoTag = "${GPSLatitude_pos},${GPSLatitudeRef_pos},${GPSLongitude_pos},${GPSLongitudeRef_pos}"
    } else {
        $errorMessage = "warning: No geotag value found."
        throw [System.FormatException]$errorMessage
    }
    return $Result_GeoTag
}

function Get_Field_By_Extension {
    param (
        [Parameter(Mandatory = $true)]
        [string]$Extension,
        [Parameter(Mandatory = $true)]
        [hashtable]$FieldDictionary
    )

    if ([string]::IsNullOrEmpty($Extension)) {
        $errorMessage = "Extension is null or empty. Cannot retrieve fields."
        Verbose -message $errorMessage -type "error"
        throw [System.ArgumentNullException]$errorMessage
    }

    if ($FieldDictionary -eq $null) {
        $errorMessage = "FieldDictionary is null. Cannot retrieve fields."
        Verbose -message $errorMessage -type "error"
        throw [System.ArgumentNullException]$errorMessage
    }

    $normalizedExtension = $Extension.ToLower()
    if ($FieldDictionary.ContainsKey($normalizedExtension)) {
        return $FieldDictionary[$normalizedExtension]
    } else {
        Verbose -message "No fields defined for extension: $normalizedExtension" -type "warning"
        return @()
    }
}

function Get_Exif_Geotag {
    param (
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$File
    )

    # Validate the file
    if (-not (Test-Path $File.FullName)) {
        $errorMessage = "File not found: $($File.FullName)"
        Verbose -message $errorMessage -type "error"
        throw [System.IO.FileNotFoundException]$errorMessage
    }

    $extension = $File.Extension.ToLower()  # File extension (including the leading dot)

    # Get actions for the given extension
    $actions = Get_Field_By_Extension -Extension $extension -FieldDictionary $gpsFields
    if (-not $actions -or $actions.Count -eq 0) {
        Verbose -message "No actions to execute for file: $($File.FullName)" -type "warning"
        return $null
    }

    $geo_tag_fields = @()
    # Execute ExifTool commands for each action
    foreach ($action in $actions) {
        $exifArgs = @("-${action}", "-s3", "-m")
        try {
            $temp_GeoTag = Run_ExifToolCommand -Arguments $exifArgs -File $File -type "GeoTag"
            $geo_tag_fields += $temp_GeoTag
        } catch {
            Verbose -message "Failed to execute ExifTool command for action: $action. Error: $_" -type "error"
            throw
        }
    }
    $result_GeoTag = AddFields_GeoTags -fields $actions -values $geo_tag_fields
    return $result_GeoTag
}

function Write_Geotag {
    param (
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$File,
        [Parameter(Mandatory = $true)]
        [string]$GeoTag
    )

    $fullPath = $File.FullName  # Full path of the file

    # Ensure the file exists
    if (-not (Test-Path -Path $fullPath)) {
        $errorMessage = "File does not exist: $fullPath"
        Verbose -message $errorMessage -type "error"
        throw [System.IO.FileNotFoundException]$errorMessage
    }

    # Validate the GeoTag
    if ([string]::IsNullOrEmpty($GeoTag)) {
        $errorMessage = "No geotag provided."
        Verbose -message $errorMessage -type "error"
        throw [System.ArgumentNullException]$errorMessage
    }

    if (-not (IsValid_GeoTag -GeoTag $GeoTag)) {
        $errorMessage = "Invalid geotag provided: $GeoTag"
        Verbose -message $errorMessage -type "error"
        throw [System.FormatException]$errorMessage
    }

    # Parse GeoTag into latitude and longitude
    $geoParts = $GeoTag -split ","
    if ($geoParts.Count -ne 4) {
        $errorMessage = "GeoTag does not have exactly 4 parts: $GeoTag"
        Verbose -message $errorMessage -type "error"
        throw [System.FormatException]$errorMessage
    }

    try {
        $latitude = [double]($geoParts[0].Trim())
        $latitudeRef = $geoParts[1].Trim().ToUpper()
        $longitude = [double]($geoParts[2].Trim())
        $longitudeRef = $geoParts[3].Trim().ToUpper()

        # Adjust latitude and longitude based on references
        if ($latitudeRef -eq "S") {
            $latitude = -1 * $latitude
        }

        if ($longitudeRef -eq "W") {
            $longitude = -1 * $longitude
        }

        # Construct ExifTool arguments
        $exifArgs = @(
            "-GPSLatitude=`"$latitude`"",
            "-GPSLatitudeRef=`"$latitudeRef`"",
            "-GPSLongitude=`"$longitude`"",
            "-GPSLongitudeRef=`"$longitudeRef`""
        )

        # Run ExifTool command
        $temp_GeoTag = Run_ExifToolCommand -Arguments $exifArgs -File $File
        return $temp_GeoTag
    } catch {
        Verbose -message "Failed to write geotag for file: $fullPath." -type "warning"
        throw
    }
}

function Remove_FilesWithOriginalExtension {
    param (
        [Parameter(Mandatory = $true)]
		[System.IO.DirectoryInfo]$root
	)
	$fullPath = $root.FullName   # Full path of the directory
	

    # Get all files in the directory with extensions ending in "_original"
    $files = Get-ChildItem -Path $fullPath -File -Recurse | Where-Object { $_.Extension -like "*_original" }

    # Remove each file
    foreach ($file in $files) {
        Remove-Item -Path $file.FullName -Force | Out-Null
    }
}
function Compare_Geotag {
    param (
        [Parameter(Mandatory = $true)]
        [string]$geotag1,
        [Parameter(Mandatory = $true)]
        [string]$geotag2
    )

    # Trim strings
    $geotag1 = $geotag1.Trim()
    $geotag2 = $geotag2.Trim()

    # Validate geotags
    $geotag1_valid = $false
    $geotag2_valid = $false

    try {
        if (-not [string]::IsNullOrWhiteSpace($geotag1) -and (IsValid_GeoTag -GeoTag $geotag1)) {
            $geotag1_valid = $true
        }
    } catch {
        Verbose -message "Error validating geotag1: $geotag1. Error: $_" -type "warning"
    }

    try {
        if (-not [string]::IsNullOrWhiteSpace($geotag2) -and (IsValid_GeoTag -GeoTag $geotag2)) {
            $geotag2_valid = $true
        }
    } catch {
        Verbose -message "Error validating geotag2: $geotag2. Error: $_" -type "warning"
    }

    # Determine the final geotag
    if ($geotag1_valid) {
        return $geotag1
    } elseif ($geotag2_valid) {
        return $geotag2
    } else {
        return Make_zero_GeoTag
    }
}

Export-ModuleMember -Function *  # Export ALL functions