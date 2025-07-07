# --- Module-level Logger ---
# This variable will hold the logger script block passed in from a calling script.
$script:MediaToolsLogger = $null

function Set-MediaToolsLogger {
    param(
        [Parameter(Mandatory=$true)]$Logger
    )
    $script:MediaToolsLogger = $Logger
}

# --- Module-level EXIF data cache ---
# Using a ConcurrentDictionary for thread-safe access from runspaces.
$script:ExifDataCache = [System.Collections.Concurrent.ConcurrentDictionary[string, psobject]]::new()

# --- Module-level FFPROBE data cache ---
# Using a ConcurrentDictionary for thread-safe access from runspaces.
$script:FfprobeDataCache = [System.Collections.Concurrent.ConcurrentDictionary[string, psobject]]::new()

$imageExtensions = @(".jpg", ".jpeg", ".heic")
$videoExtensions = @(".mov", ".mp4")

# Define timestamp fields for different file extensions
$TimeStampFields = @{
    ".jpeg" = @("DateTimeOriginal", "CreateDate", "DateAcquired")
    ".jpg"  = @("DateTimeOriginal", "CreateDate", "DateAcquired")
    ".heic" = @("DateTimeOriginal", "DateCreated", "DateTime")
    ".mov"  = @("TrackCreateDate", "CreateDate", "MediaCreateDate")
    ".mp4"  = @("TrackCreateDate", "MediaModifyDate", "MediaCreateDate", "TrackModifyDate")
}

# Define GPS fields for different file extensions
$gpsFields = @{
    ".jpeg" = @("GPSLatitudeRef", "GPSLatitude", "GPSLongitudeRef", "GPSLongitude", "GPSPosition")
    ".jpg"  = @("GPSLatitudeRef", "GPSLatitude", "GPSLongitudeRef", "GPSLongitude", "GPSPosition")
    ".heic" = @("GPSLatitudeRef", "GPSLatitude", "GPSLongitudeRef", "GPSLongitude", "GPSPosition")
    ".mov"  = @("GPSLatitudeRef", "GPSLatitude", "GPSLongitudeRef", "GPSLongitude", "GPSPosition")
    ".mp4"  = @("GPSLatitudeRef", "GPSLatitude", "GPSLongitudeRef", "GPSLongitude", "GPSPosition")
}

# Define patterns for extracting timestamps from filenames
$patterns = @(
    '(?<date>\d{4}-\d{2}-\d{2})_(?<time>\d{2}-\d{2}-\d{2})_-\d+',  # Matches 2019-02-18_13-12-18_-_89373.jpg
    '(?<date>\d{4}-\d{2}-\d{2})_(?<time>\d{2}-\d{2}-\d{2})',       # Matches 2020-03-31_16-04-32.mp4
    '(?<date>\d{2}-\d{2}-\d{4})@(?<time>\d{2}-\d{2}-\d{2})',       # Matches 29-03-2023@12-34-56
    '(?<date>\d{4}_\d{4})_(?<time>\d{6})',                         # Matches 2023_0329_123456
    '(?<date>\d{8})_(?<time>\d{6})-\w+',                           # Matches 20240214_103148-4d0e
    '(?<date>\d{8})_(?<time>\d{6})',                               # Matches 20240122_175641
    '(?<date>\d{8})',                                              # Matches VID_20200311
    '(?<date>\d{4}-\d{2}-\d{2})\(\d+\)',                           # Matches 2023-07-27(10).jpg
    '(?<date>[A-Za-z]{3} \d{1,2}, \d{4}), (?<time>\d{1,2}:\d{2}:\d{2}(AM|PM))',  # Matches Mar 29, 2023, 12:34:56PM
    '(?<date>\d{4}/\d{2}/\d{2}) (?<time>\d{2}:\d{2}:\d{2})',       # Matches 2023/03/29 12:34:56
    '(?<date>\d{4}-\d{2}-\d{2}) (?<time>\d{2}:\d{2}:\d{2}\.\d{3})',  # Matches 2023-03-29 12:34:56.123
    '@(?<date>\d{2}-\d{2}-\d{4})_(?<time>\d{2}-\d{2}-\d{2})',      # Matches photo_1406@18-10-2016_06-50-25
    '(?<date>\d{4}:\d{2}:\d{2}) (?<time>\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:[+-]\d{2}:\d{2})?)',  # Matches 2023:03:29 12:34:56+00:00
    '(?<prefix>[A-Za-z]+)_(?<date>\d{8})_(?<time>\d{6})'           # Matches PREFIX_YYYYMMDD_HHMMSS
)

# Define time formats for validating timestamps
$time_formats = @(
    "yyyy:MM:dd HH:mm:sszzz",       # Standard format with timezone offset
    "yyyy:MM:dd HH:mm:ss zzz",      # Standard format with space before offset
    "yyyy:MM:dd HH:mm:ss.fffzzz",   # Format with milliseconds and timezone offset
    "yyyy-MM-ddTHH:mm:sszzz",       # ISO 8601 format
    "yyyy-MM-dd HH:mm:ss",          # Common format without timezone
    "yyyy-MM-ddTHH:mm:ss",          # ISO 8601 without timezone
    "yyyy-MM-dd HH:mm:ss.fff",      # Format with milliseconds
    "MM/dd/yyyy HH:mm:ss zzz",      # US format with timezone offset
    "MMM d, yyyy, h:mm:sstt",       # Format with month name and AM/PM
    "MMM d, yyyy, h:mm:ss tt",      # Format with month name, AM/PM, and space
    "MMM d, yyyy, h:mm:ssttzzz",    # **New format for Jan 23, 2024, 3:44:03PM+00:00**
    "yyyy:MM:dd HH:mm:ss.ff zzz",   # Format with fractional seconds
    "yyyy:MM:dd HH:mm:ss.fffzzz",   # Format with milliseconds
    "yyyy:MM:dd HH:mm:ss"           # Format without timezone
)

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
			$GPSLongitude = [double]($geoParts[2].Trim()) # Corrected variable name
			$GPSLongitudeRef = $geoParts[3].Trim()
		} catch {
			& $script:MediaToolsLogger "ERROR" "Error: Unable to convert '$($InputGeoTag)' to a double."
		}
        $resulted_geotag = "${GPSLatitude},${GPSLatitudeRef},${GPSLongitude},${GPSLongitudeRef}"
	} elseif ($geoParts.Count -eq 2) {	
		try {
            $GPSLatitude = Standardize_GeoTag_value -InputGeoTag $geoParts[0].Trim()
			$GPSLongitude = Standardize_GeoTag_value -InputGeoTag $geoParts[1].Trim()
			$GPSLatitudeRef = Get_LatitudeRef -latitude $GPSLatitude -LatitudeRef "N"
			$GPSLongitudeRef = Get_LongitudeRef -longitude $GPSLongitude -LongitudeRef "E" # Corrected variable name
            $GPSLatitude=$([math]::Abs($GPSLatitude)) # Absolute latitude
            $GPSLongitude=$([math]::Abs($GPSLongitude)) # Absolute longitude

		} catch {
			& $script:MediaToolsLogger "ERROR" "Error: Unable to convert '$($InputGeoTag)' to a double."
		}
        $resulted_geotag = "${GPSLatitude},${GPSLatitudeRef},${GPSLongitude},${GPSLongitudeRef}"
	} elseif ($geoParts.Count -eq 1) {	
		try {
            $GPSLatitude = 200
			$GPSLongitude = 200
			$GPSLatitudeRef = "M"
			$GPSLongitudeRef = "M"
            $geotag=$geoParts[0].Trim() # Corrected variable name
            $resulted_geotag =Standardize_GeoTag_value -InputGeoTag $geotag
		} catch {
			& $script:MediaToolsLogger "ERROR" "Error: Unable to convert '$($InputGeoTag)' to a double."
		}
	} else {
        & $script:MediaToolsLogger "ERROR" "Error: Unable to convert '$($InputGeoTag)' to a double."
    }    
	return $resulted_geotag
}

# This function is the direct interface for running the exiftool.exe process.
function Invoke-ExifToolProcess {
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
        # & $script:MediaToolsLogger using the main & $script:MediaToolsLogger function
        & $script:MediaToolsLogger "ERROR" "File not found for ExifTool command: $($file.FullName)"
        throw [System.IO.FileNotFoundException] "File not found: $($file.FullName)"
        # return # Or just return if throwing is too disruptive downstream
    }

    $fullPath  = $file.FullName       # Full path of the file

    # Build the command string and wrap it in additional quotes
    $commandArgs = @($ExifToolPath) + $arguments + @($fullPath) # Combine executable, specific args, and file path

    # Retry Logic
    $attempt = 0
    $ExifToolOutput = $null
    while ($attempt -lt $maxRetries) {
        try {
            $attempt++
            $commandStringForLog = $commandArgs -join ' ' # For logging only
            & $script:MediaToolsLogger "INFO" "RUN_EXIF: Attempt $attempt : Executing: $commandStringForLog"
 
            $ExifToolOutput = & $commandArgs[0] $commandArgs[1..($commandArgs.Count-1)] 2>&1
            & $script:MediaToolsLogger "DEBUG" "RUN_EXIF: Attempt $attempt : Finished execution for '$fullPath'"

            # Check for errors or warnings in the output
            if ($ExifToolOutput -match "Error") {
                $errorMessage = "ExifTool command returned an error: $($ExifToolOutput -join '; ')"
                & $script:MediaToolsLogger "DEBUG" $errorMessage
                throw [System.Exception]$errorMessage
            }
            if ($ExifToolOutput -match "Warning") {
                & $script:MediaToolsLogger "WARNING" "ExifTool command returned a warning: $($ExifToolOutput -join '; ')"
                 return $null # Return null on warning. Returning a geotag for any command with a warning is a bug.
           }
            break  # Exit the loop on success
        } catch [System.Exception] {
            & $script:MediaToolsLogger "DEBUG" "RUN_EXIF: Attempt $attempt failed for '$fullPath'. Error: $_"
            # Catch specific ExifTool error first
            if ($_.Exception.Message -match "ExifTool command returned an error") {
                 & $script:MediaToolsLogger "ERROR" "ExifTool execution failed on attempt $attempt for '$fullPath'. Error: $($_.Exception.Message)"
                 if ($attempt -ge $maxRetries) { throw } # Re-throw after max retries
                 Start-Sleep -Seconds $retryDelay
            } else {
                # & $script:MediaToolsLogger other potential exceptions during execution
                & $script:MediaToolsLogger "ERROR" "Unexpected error executing ExifTool on attempt $attempt for '$fullPath'. Error: $_"
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

function Run_FfprobeCommand {
    param (
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$File
    )
    $filePath = $File.FullName

    # Check cache first
    if ($script:FfprobeDataCache.ContainsKey($filePath)) {
        & $script:MediaToolsLogger "DEBUG" "FFPROBE CACHE HIT for $($File.Name)."
        return $script:FfprobeDataCache[$filePath]
    }

    # On cache miss, execute ffprobe to get all format and stream data
    & $script:MediaToolsLogger "DEBUG" "FFPROBE CACHE MISS for $($File.Name). Executing ffprobe."
    $ffprobeArgs = @("-v", "quiet", "-print_format", "json", "-show_format", "-show_streams")
    $jsonOutput = Invoke-FfprobeProcess -file $File -arguments $ffprobeArgs

    if (-not $jsonOutput) {
        # Add a null to the cache to prevent re-probing a known-bad file in the same session
        $script:FfprobeDataCache.TryAdd($filePath, $null) | Out-Null
        return $null
    }

    try {
        $metadata = $jsonOutput | ConvertFrom-Json
        # Add the full metadata object to the cache
        $script:FfprobeDataCache.TryAdd($filePath, $metadata) | Out-Null
        return $metadata
    } catch {
        & $script:MediaToolsLogger "WARNING" "Could not parse ffprobe JSON for '$($File.Name)'. Error: $($_.Exception.Message)"
        $script:FfprobeDataCache.TryAdd($filePath, $null) | Out-Null
        return $null
    }
}

# This function is the direct interface for running the ffprobe.exe process.
function Invoke-FfprobeProcess {
    param(
        [Parameter(Mandatory=$true)]
        [System.IO.FileInfo]$file,
        [Object[]]$arguments
    )
    if (-not (Test-Path -Path $file.FullName)) {
        & $script:MediaToolsLogger "ERROR" "File not found for ffprobe command: $($file.FullName)"
        throw [System.IO.FileNotFoundException] "File not found: $($file.FullName)"
    }

    $ffprobePath = $env:FFPROBE_PATH
    if (-not (Test-Path -Path $ffprobePath)) {
        & $script:MediaToolsLogger "CRITICAL" "ffprobe.exe not found at path specified in environment variable FFPROBE_PATH: '$ffprobePath'"
        throw [System.IO.FileNotFoundException] "ffprobe.exe not found at '$ffprobePath'"
    }

    $commandArgs = @($arguments) + @($file.FullName)
    $commandStringForLog = "$ffprobePath " + ($commandArgs -join ' ')
    & $script:MediaToolsLogger "DEBUG" "RUN_FFPROBE: Executing: $commandStringForLog"

    try {
        $ffprobeOutput = & $ffprobePath $commandArgs 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "ffprobe failed with exit code $LASTEXITCODE. Output: $($ffprobeOutput -join '; ')"
        }
        # Return the raw output (which should be JSON)
        return $ffprobeOutput
    } catch {
        & $script:MediaToolsLogger "WARNING" "Failed to execute ffprobe for '$($file.FullName)'. Error: $($_.Exception.Message)"
        # Return null on failure so the calling function can handle it gracefully.
        return $null
    }
}

# This is the new caching wrapper. It replaces the old Run_ExifToolCommand.
# It intelligently decides whether to serve from the cache or execute a new process.
function Run_ExifToolCommand {
    param (
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$file,
        [Object[]]$arguments,
        [string]$type = "execute"
    )
    $filePath = $file.FullName

    # --- Determine Operation Type (Read vs. Write) ---
    $isWriteOperation = $false
    $tagToWrite = $null
    $valueToWrite = $null

    # Check for a simple write operation pattern like "-TagName=Value"
    if (($arguments -join ' ') -match '(-[^=]+)=(.+)') {
        $isWriteOperation = $true
        $tagToWrite = $matches[1].TrimStart('-')
        # The value from ExifTool arguments might be quoted, so we trim them.
        $valueToWrite = $matches[2].Trim("`'")
    }

    # --- Handle WRITE operation (modify cache only) ---
    if ($isWriteOperation) {
        & $script:MediaToolsLogger "DEBUG" "CACHE WRITE for tag '$tagToWrite' in file $($file.Name)."

        # Step 1: Ensure the file's data is in the cache. If not, read it from the file.
        if (-not $script:ExifDataCache.ContainsKey($filePath)) {
            & $script:MediaToolsLogger "DEBUG" "CACHE MISS for write on $filePath. Fetching all EXIF data first."
            try {
                $exifResult = Get-ExifDataAsJson -File $file
                $script:ExifDataCache.TryAdd($exifResult.FilePath, $exifResult.ExifData) | Out-Null
            } catch {
                & $script:MediaToolsLogger "WARNING" "Failed to fetch and cache EXIF data for $filePath. Write will fail. Error: $_"
                $script:ExifDataCache.TryAdd($filePath, $null) | Out-Null
            }
        }

        # Step 2: Modify the value in the cached object.
        $cachedData = $script:ExifDataCache[$filePath]
        if ($null -ne $cachedData) {
            # Add or update the property. Using -Force will overwrite the property if it already exists.
            $cachedData | Add-Member -MemberType NoteProperty -Name $tagToWrite -Value $valueToWrite -Force
            & $script:MediaToolsLogger "INFO" "Updated cache for '$filePath' with [$tagToWrite = $valueToWrite]. No file write performed."
        } else {
            & $script:MediaToolsLogger "WARNING" "Cannot perform cache write for '$tagToWrite' on '$filePath' because initial cache data is null."
        }
        # Return after modifying the cache. Do not proceed to execute anything.
        return
    }

    # --- Handle READ operation (from cache) ---
    # Find the tag we are supposed to read from the arguments.
    $tagToRead = $null
    foreach ($arg in $arguments) {
        if ($arg -like '-*' -and $arg -ne '-s3' -and $arg -ne '-m') {
            $tagToRead = $arg.TrimStart('-')
            break
        }
    }

    # If we couldn't determine a simple tag to read, it's a complex command that needs direct execution.
    if (-not $tagToRead) {
        & $script:MediaToolsLogger "DEBUG" "Complex command detected. Executing directly: $($arguments -join ' ')"
        return Invoke-ExifToolProcess -file $file -arguments $arguments -type $type
    }

    # Ensure the file's data is in the cache for the read operation.
    if (-not $script:ExifDataCache.ContainsKey($filePath)) {
        & $script:MediaToolsLogger "DEBUG" "CACHE MISS for read on $filePath. Fetching all EXIF data."
        try {
            $exifResult = Get-ExifDataAsJson -File $file
            $script:ExifDataCache.TryAdd($exifResult.FilePath, $exifResult.ExifData) | Out-Null
        } catch {
            & $script:MediaToolsLogger "WARNING" "Failed to fetch and cache EXIF data for $filePath. Read will fail. Error: $_"
            $script:ExifDataCache.TryAdd($filePath, $null) | Out-Null
        }
    }

    # Now, retrieve the specific tag value from the cached data.
    $cachedData = $script:ExifDataCache[$filePath]
    $foundValue = $null
    if ($null -ne $cachedData) {
        # Find the property in the cached object. It might have a group prefix like "EXIF:".
        $property = $cachedData.PSObject.Properties | Where-Object { $_.Name -like "*:$tagToRead" } | Select-Object -First 1
        if ($property) {
            $foundValue = $property.Value
        }
    }

    # If the tag wasn't found in the cache, return a default value for the type.
    if ($null -eq $foundValue) {
        & $script:MediaToolsLogger "DEBUG" "Tag '$tagToRead' not found in cache for $filePath. Returning default for type '$type'."
        switch ($type.ToLower()) {
            "timestamp" { return Make_zero_TimeStamp }
            "geotag"    { return Make_zero_GeoTag }
            default     { return $null }
        }
    }

    # Process and return the cached value.
    & $script:MediaToolsLogger "DEBUG" "CACHE HIT for tag '$tagToRead' in file $($file.Name)."
    switch ($type.ToLower()) {
        "timestamp" {
            if ($foundValue -and $foundValue -ne "") {
                return Standardize_TimeStamp -InputTimestamp $foundValue
            } else {
                return Make_zero_TimeStamp
            }
        }
        "geotag" {
            if ($foundValue -and $foundValue -ne "") {
                return Standardize_GeoTag -InputGeoTag $foundValue
            } else {
                return Make_zero_GeoTag
            }
        }
        default {
            return $foundValue
        }
    }
}

function IsValid_GeoTag {
    param (
        [Parameter(Mandatory = $true)]
        [string]$GeoTag
    )

    if ([string]::IsNullOrEmpty($GeoTag)) {
        & $script:MediaToolsLogger "DEBUG" "Validation failed: GeoTag is null or empty."
        return $false
    }

    $geoParts = $GeoTag -split ","
    if ($geoParts.Count -ne 4) {
        & $script:MediaToolsLogger "DEBUG" "Validation failed: Invalid GeoTag format (not 4 parts): $GeoTag"
        return $false
    }

    try {
        $latitude = [double]($geoParts[0].Trim())
        $latitudeRef = $geoParts[1].Trim().ToUpper()
        $longitude = [double]($geoParts[2].Trim())
        $longitudeRef = $geoParts[3].Trim().ToUpper()

        if (($latitude -lt -90 -or $latitude -gt 90) -or ($longitude -lt -180 -or $longitude -gt 180)) {
            & $script:MediaToolsLogger "DEBUG" "Validation failed: Latitude or longitude out of range: $GeoTag"
            return $false
        }

        if (($latitudeRef -ne "N" -and $latitudeRef -ne "S") -or ($longitudeRef -ne "E" -and $longitudeRef -ne "W")) {
            & $script:MediaToolsLogger "DEBUG" "Validation failed: Invalid latitude or longitude reference: $GeoTag"
            return $false
        }
    } catch {
        & $script:MediaToolsLogger "DEBUG" "Validation failed: Could not parse GeoTag parts. Error: $($_.Exception.Message)"
        return $false
    }

    return $true
}

function Make_zero_GeoTag {
    return "200,M,200,M"
}

function IsValid_TimeStamp {
    param (
        [string]$timestamp_in
    )

    if ([string]::IsNullOrEmpty($timestamp_in)) {
        & $script:MediaToolsLogger "DEBUG" "Validation failed: Timestamp is null or empty."
        return $false
    }

    try {
        $output_timestamp = Standardize_TimeStamp -InputTimestamp $timestamp_in
        if ($output_timestamp -eq "0001:01:01 00:00:00+00:00" -or $output_timestamp -eq "0000:00:00 00:00:00+00:00") {
            & $script:MediaToolsLogger "DEBUG" "Validation failed: Timestamp is a zero-date value: $output_timestamp"
            return $false
        }
    } catch {
        & $script:MediaToolsLogger "DEBUG" "Validation failed: Could not standardize timestamp '$timestamp_in'. Error: $($_.Exception.Message)"
        return $false
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
        & $script:MediaToolsLogger  "ERROR" "$errorMessage"
        throw [System.FormatException]$errorMessage
    }
}

function Get_LatitudeRef {
    param (
        [double]$latitude
    )
    # The cardinal direction is determined SOLELY by the sign of the coordinate.
    # A positive latitude is North, a negative latitude is South.
    if ($latitude -ge 0) {
        return "N"
    } else {
        return "S"
    }
}

function Get_LongitudeRef {
    param (
        [double]$longitude
    )
    # The cardinal direction is determined SOLELY by the sign of the coordinate.
    # A positive longitude is East, a negative longitude is West.
    if ($longitude -ge 0) {
        return "E"
    } else {
        return "W"
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
        [Parameter(Mandatory = $true)]
        [string[]]$Timestamps
    )

    foreach ($timestamp in $Timestamps) {
        # With the refactored IsValid_TimeStamp, no try/catch is needed here.
        if (IsValid_TimeStamp -timestamp_in $timestamp) {
            # Return the first valid timestamp found.
            return $timestamp
        }
    }

    # If no valid timestamp was found, return null.
    return $null
}

function Get_Json_TimeStamp {
    param (
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$JsonFile
    )

    # Check if the JSON file exists
    if (-not (Test-Path -Path $JsonFile.FullName)) {
        $errorMessage = "JSON file not found: $($JsonFile.FullName)"
        & $script:MediaToolsLogger  "ERROR" "$errorMessage"
        throw [System.IO.FileNotFoundException]$errorMessage
    }

    # Load and parse the JSON file
    try {
        $jsonContent = Get-Content -Path $JsonFile.FullName | ConvertFrom-Json
    } catch {
        $errorMessage = "Failed to read or parse JSON file: $($JsonFile.FullName). Error: $_"
        & $script:MediaToolsLogger  "ERROR" "$errorMessage"
        throw [System.FormatException]$errorMessage
    }

    # Extract timestamps from the JSON content
    try {
        $creationDate = Standardize_TimeStamp -InputTimestamp $jsonContent.creationTime?.formatted
    } catch {
        & $script:MediaToolsLogger  "ERROR" "Failed to standardize creationTime timestamp from JSON file: $($JsonFile.FullName). Error: $_"
        throw
    }
    try {
        $photoTakenDate = Standardize_TimeStamp -InputTimestamp $jsonContent.photoTakenTime?.formatted
    } catch {
        & $script:MediaToolsLogger  "ERROR" "Failed to standardize photoTakenTime timestamp from JSON file: $($JsonFile.FullName). Error: $_"
        throw
    }

    # Compare and return the most appropriate timestamp
    $result = Compare_TimeStamp -timestamp1 $creationDate -timestamp2 $photoTakenDate

    if (-not $result -or $result -eq $(Make_zero_TimeStamp)) {
        & $script:MediaToolsLogger  "ERROR" "Failed to standardize photoTakenTime timestamp from JSON file: $($JsonFile.FullName). Error: $_"
        throw
    }
    return $result
}

function Get-ExifDataAsJson {
    param (
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$File  # The media file path (image or video)
    )
    # Get all possible timestamp and geotag fields in one go for maximum performance.
    # This avoids starting exiftool.exe multiple times for the same file.
    $allTimestampFieldNames = $TimeStampFields.Values | ForEach-Object { $_ } | Select-Object -Unique
    $allGpsFieldNames = $gpsFields.Values | ForEach-Object { $_ } | Select-Object -Unique
    
    $allFieldNames = $allTimestampFieldNames + $allGpsFieldNames | Select-Object -Unique
    $allFieldsForExiftool = $allFieldNames | ForEach-Object { "-$_" }

    # Use -json to get structured output, -G to get group names (e.g., "EXIF", "File")
    $exifArgs = @("-json", "-G", "-s") + $allFieldsForExiftool

    try {
        # Run_ExifToolCommand_real returns an array of strings (the JSON output)
        $jsonOutput = Invoke-ExifToolProcess -Arguments $exifArgs -File $File -type "execute"
        if ($jsonOutput) {
            $exifDataObject = ($jsonOutput | ConvertFrom-Json)[0]
            # Return a structured object containing both the file path and the retrieved EXIF data.
            # This makes it easier for the calling script to manage the results.
            return [PSCustomObject]@{
                FilePath = $File.FullName
                ExifData = $exifDataObject
            }
        }
        return $null
    } catch {
        & $script:MediaToolsLogger "WARNING" "Failed to get bulk EXIF JSON for $($File.FullName). Error: $($_.Exception.Message)"
        return $null
    }
}


function Get_Exif_Timestamp {
    param (
        [System.IO.FileInfo]$File
    )

    # Ensure the file exists
    if (-not (Test-Path $File.FullName)) {
        $errorMessage = "File not found: $($File.FullName)"
        & $script:MediaToolsLogger  "ERROR" "$errorMessage"
        throw [System.IO.FileNotFoundException]$errorMessage
    }

    # Get the file extension in lowercase
    $extension = $File.Extension.ToLower()

    # Get timestamp fields for the given extension
    $actions = Get_Field_By_Extension -Extension $extension -FieldDictionary $TimeStampFields
    if (-not $actions -or $actions.Count -eq 0) {
        $errorMessage = "No timestamp fields defined for extension: $extension"
        & $script:MediaToolsLogger  "ERROR" "$errorMessage"
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
            & $script:MediaToolsLogger  "INFO" "$Message"
            throw [System.IO.FileNotFoundException]$Message
        }
        $result_TimeStamp = Compare_TimeStamp -timestamp1 $result_TimeStamp -timestamp2 $temp_TimeStamp
    }

    # Return the final timestamp or defaulttimestamp if invalid
    if (-not $result_TimeStamp -or $result_TimeStamp -eq $(Make_zero_TimeStamp)) {
        $Message = "Failed to retrieve timestamp from Exif metadata for file: $($File.FullName)."
        & $script:MediaToolsLogger  "INFO" "$Message"
        throw [System.IO.FileNotFoundException]$Message
    }
    return $result_TimeStamp
}

# Inside MediaTools.psm1

                                              param (
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$File  # The media file path (image or video)
    )

    $fullPath = $File.FullName
    $JsonPath = "${fullPath}.json"

    # Create an ordered list of potential timestamp sources.
    # The order determines the priority. The first valid one found will be used.
    $potentialTimestamps = [System.Collections.Generic.List[string]]::new()

    # 1. JSON Sidecar (Highest priority)
    if (Test-Path -Path $JsonPath) {
        try {
            $JsonFile = [System.IO.FileInfo]$JsonPath
            $potentialTimestamps.Add($(Get_Json_TimeStamp -JsonFile $JsonFile))
        } catch {
            & $script:MediaToolsLogger "DEBUG" "Could not get timestamp from JSON for $($File.Name): $($_.Exception.Message)"
        }
    }

    # 2. EXIF Data
    try {
        $potentialTimestamps.Add($(Get_Exif_Timestamp -File $File))
    } catch {
        & $script:MediaToolsLogger "DEBUG" "Could not get timestamp from EXIF for $($File.Name): $($_.Exception.Message)"
    }

    # 3. FFprobe Data (for videos)
    if ($videoExtensions -contains $File.Extension.ToLower()) {
        try {
            $potentialTimestamps.Add($(Get_Ffprobe_Timestamp -File $File))
        } catch {
            & $script:MediaToolsLogger "DEBUG" "Could not get timestamp from FFprobe for $($File.Name): $($_.Exception.Message)"
        }
    }

    # 4. Filename (Lowest priority)
    try {
        $potentialTimestamps.Add($(Parse_DateTimeFromFilename -FilePath $File))
    } catch {
        & $script:MediaToolsLogger "DEBUG" "Could not get timestamp from filename for $($File.Name): $($_.Exception.Message)"
    }

    # Use the new Compare_TimeStamp to find the best one
    $bestTimestamp = Compare_TimeStamp -Timestamps $potentialTimestamps

    if ($null -ne $bestTimestamp) {
        & $script:MediaToolsLogger "INFO" "Determined valid timestamp: $bestTimestamp for $($File.Name)"
        return $bestTimestamp
    } else {
        # If no valid timestamp could be determined
        $noValidTimestampMsg = "No valid timestamp could be determined for file: $($File.FullName)"
        & $script:MediaToolsLogger "WARNING" $noValidTimestampMsg # Log as warning
        throw [System.FormatException]::new($noValidTimestampMsg) # Throw specific error
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
                    & $script:MediaToolsLogger  "WARNING" "Date format not recognized: $date"
                    continue
                }
            }

            # Normalize time formats
            $formattedTime = switch ($true) {
                ($time -match '\d{6}') { $time.Substring(0, 2) + ":" + $time.Substring(2, 2) + ":" + $time.Substring(4, 2) }
                ($time -match '\d{2}-\d{2}-\d{2}') { $time -replace '-', ':' }
                ($time -match '\d{2}:\d{2}:\d{2}') { $time }
                default {
                    & $script:MediaToolsLogger  "WARNING" "Time format not recognized: $time. Defaulting to 00:00:00."
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
    & $script:MediaToolsLogger  "WARNING" "No valid date-time found in filename: $filename" # Log the error
    throw [System.FormatException] "No valid date-time found in filename: $filename" # Re-throw the exception
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
        & $script:MediaToolsLogger  "ERROR" "$errorMessage"
        throw [System.IO.FileNotFoundException]$errorMessage
    }

    $extension = $File.Extension.ToLower()  # File extension (including the leading dot)

    # Validate the timestamp
    if ([string]::IsNullOrEmpty($TimeStamp)) { # This check is redundant with IsValid_TimeStamp
        $errorMessage = "No Timestamp provided."
        & $script:MediaToolsLogger  "ERROR" "$errorMessage"
        throw [System.ArgumentNullException]$errorMessage
    }

    if (-not (IsValid_TimeStamp -timestamp_in $TimeStamp)) {
        $errorMessage = "Invalid Timestamp provided: $TimeStamp"
        & $script:MediaToolsLogger  "ERROR" "$errorMessage"
        throw [System.FormatException]$errorMessage
    }

    # Get actions for the given extension
    $actions = Get_Field_By_Extension -Extension $extension -FieldDictionary $TimeStampFields

    if ($actions.Count -eq 0) {
        & $script:MediaToolsLogger  "WARNING" "No actions to execute for extension: $extension"
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
        & $script:MediaToolsLogger  "INFO" "Successfully wrote timestamp $FinalTimestamp"
    } catch {
        & $script:MediaToolsLogger  "WARNING" "Failed to write timestamp for file: $($File.basename)."
        throw
    }
    try {
        $FinalGeoTag = Find_and_Write_Valid_GeoTag -File $File
        & $script:MediaToolsLogger  "INFO" "Successfully wrote GeoTag $FinalGeoTag"
    } catch {
        & $script:MediaToolsLogger  "WARNING" "Failed to write geotag for file: $($File.basename)." # Corrected variable name
        throw
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
            New-Item -Path $desiredPath -ItemType Directory -Force | Out-Null # This log is not using the main Log function
            & $script:MediaToolsLogger  "INFO" "Created destination directory: $desiredPath"
        }
    } catch {
        $errorMessage = "Failed to create destination directory: $desiredPath. Error: $_"
        & $script:MediaToolsLogger  "ERROR" "$errorMessage"
        throw [System.IO.DirectoryNotFoundException]$errorMessage
    }

    # Move the file to the destination directory
    try {
        Move-Item -Path $File.FullName -Destination $destination -Force
        & $script:MediaToolsLogger  "INFO" "Successfully moved file to: $destination" # This log is not using the main Log function
    } catch {
        $errorMessage = "Failed to move file: $($File.FullName). Error: $_"
        & $script:MediaToolsLogger  "ERROR" "$errorMessage"
        throw
    }
}

function Merge-FileMetadata {
    param (
        [System.IO.FileInfo]$File
    )

    $timestampResult = $null
    $geotagResult = $null

    try {
        $timestampResult = Find-ValidTimestamp -File $File
    } catch {
        & $script:MediaToolsLogger "WARNING" "Could not determine a valid timestamp for $($File.FullName): $($_.Exception.Message)"
    }

    try {
        $geotagResult = Find-ValidGeotag -File $File
    } catch {
        & $script:MediaToolsLogger "WARNING" "Could not determine a valid geotag for $($File.FullName): $($_.Exception.Message)"
    }

    return [PSCustomObject]@{
        ConsolidatedTimestamp = $timestampResult
        ConsolidatedGeotag    = $geotagResult
    }
}

function Get_Json_Geotag {
    param (
        [System.IO.FileInfo]$JsonFile
    )

    # Check if the JSON file exists
    if (-not (Test-Path -Path $JsonFile.FullName)) {
        $errorMessage = "JSON file not found: $($JsonFile.FullName)"
        & $script:MediaToolsLogger  "ERROR" "$errorMessage"
        throw [System.IO.FileNotFoundException]$errorMessage
    }

    # Load the JSON file
    try {
        $jsonContent = Get-Content -Path $JsonFile.FullName | ConvertFrom-Json
    } catch { 
        $errorMessage = "Failed to read or parse JSON file: $($JsonFile.FullName). Error: $_" # This error message is not logged
        & $script:MediaToolsLogger  "ERROR" "$errorMessage"
        throw [System.FormatException]$errorMessage
    }

    # Extract latitude and longitude
    $latitude = $jsonContent.geoData?.latitude
    $longitude = $jsonContent.geoData?.longitude

    if ($latitude -and $longitude) {
        # Standardize and return the geotag
        return Standardize_GeoTag -InputGeoTag "${latitude}, ${longitude}"
    } else { # This warning is not using the main Log function
        & $script:MediaToolsLogger  "WARNING" "GeoData is missing or incomplete in JSON file: $($JsonFile.FullName)"
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

    # Step 5: Safely remove a spurious " 00:00:00" that sometimes appears after a valid time.
    # This pattern is more specific to avoid corrupting valid midnight timestamps.
    if ($InputTimestamp -match '(\s\d{2}:\d{2}:\d{2})\s+00:00:00$') {
        & $script:MediaToolsLogger  "INFO" "Removing spurious ' 00:00:00' from timestamp: $InputTimestamp"
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
            & $script:MediaToolsLogger  "WARNING" "Invalid or unrecognized time zone abbreviation: $timeZoneAbbreviation. Using default offset '+00:00'."
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
            # Log at DEBUG level to avoid clutter, but still provide info for troubleshooting.
            & $script:MediaToolsLogger "DEBUG" "Timestamp '$InputTimestamp' did not match format '$format'."
        }
    }

    # Log if parsing fails for all formats
    $errorMessage = "Failed to parse the input timestamp: $InputTimestamp. Returning default invalid timestamp."
    & $script:MediaToolsLogger  "WARNING" "$errorMessage"
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
            & $script:MediaToolsLogger  "ERROR" "$errorMessage"
            throw
        }
    }

    # Handle decimal format (e.g., "45.123")
    if ($sanitizedInputGeoTag -match "^[+-]?\d+(\.\d+)?$") {
        try {
            return [double]$sanitizedInputGeoTag
        } catch {
            $errorMessage = "Error converting geotag to decimal: $sanitizedInputGeoTag. Error: $_"
            & $script:MediaToolsLogger  "ERROR" "$errorMessage"
            throw
        }
    }

    # Handle degrees, minutes, seconds format (e.g., "45 deg 30' 15.5\")
    if ($sanitizedInputGeoTag -match "(\d+)\s*deg\s*(\d+)'\s*(\d+(\.\d+)?)>") {
        try {
            $degrees = [double]$matches[1]
            $minutes = [double]$matches[2]
            $seconds = [double]$matches[3]
            return $degrees + ($minutes / 60) + ($seconds / 3600)
        } catch { # This catch block is redundant
            $errorMessage = "Error parsing degrees, minutes, seconds format: $sanitizedInputGeoTag. Error: $_"
            & $script:MediaToolsLogger  "ERROR" "$errorMessage"
            throw
        }
    }

    # Log and throw error for invalid format
    $errorMessage = "Invalid geotag format: $InputGeoTag"
    & $script:MediaToolsLogger  "ERROR" "$errorMessage" # Log the error
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
                        & $script:MediaToolsLogger  "ERROR" "$errorMessage"
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
                        & $script:MediaToolsLogger  "ERROR" "$errorMessage"
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
                        & $script:MediaToolsLogger  "ERROR" "$errorMessage"
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
                        & $script:MediaToolsLogger  "ERROR" "$errorMessage"
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
                        & $script:MediaToolsLogger "ERROR" $errorMessage
                        throw [System.FormatException]$errorMessage
                    }
                }
            }
            default {
                & $script:MediaToolsLogger  "WARNING" "Unknown field: $field. No changes made."
            } # This warning is not using the main Log function
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
            & $script:MediaToolsLogger "ERROR" $errorMessage
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
        & $script:MediaToolsLogger "WARNING" $errorMessage
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
        & $script:MediaToolsLogger  "ERROR" "$errorMessage"
        throw [System.ArgumentNullException]$errorMessage
    }

    if ($null -eq $FieldDictionary) {
        $errorMessage = "FieldDictionary is null. Cannot retrieve fields."
        & $script:MediaToolsLogger  "ERROR" "$errorMessage"
        throw [System.ArgumentNullException]$errorMessage
    }

    $normalizedExtension = $Extension.ToLower()
    if ($FieldDictionary.ContainsKey($normalizedExtension)) {
        return $FieldDictionary[$normalizedExtension]
    } else { 
        & $script:MediaToolsLogger  "WARNING" "No fields defined for extension: $normalizedExtension" # This warning is not using the main Log function
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
        & $script:MediaToolsLogger  "ERROR" "$errorMessage"
        throw [System.IO.FileNotFoundException]$errorMessage
    }

    $extension = $File.Extension.ToLower()  # File extension (including the leading dot)

    # Get actions for the given extension
    $actions = Get_Field_By_Extension -Extension $extension -FieldDictionary $gpsFields
    if (-not $actions -or $actions.Count -eq 0) {
        & $script:MediaToolsLogger  "WARNING" "No actions to execute for file: $($File.FullName)"
        return $null
    }

    $geo_tag_fields = @()
    # Execute ExifTool commands for each action
    foreach ($action in $actions) {
        $exifArgs = @("-${action}", "-s3", "-m")
        try {
            $temp_GeoTag = Run_ExifToolCommand -Arguments $exifArgs -File $File -type "GeoTag"
            $geo_tag_fields += $temp_GeoTag
        } catch { # This catch block is redundant
            & $script:MediaToolsLogger  "ERROR" "Failed to execute ExifTool command for action: $action. Error: $_"
            throw
        }
    }
    try {
        $result_GeoTag = AddFields_GeoTags -fields $actions -values $geo_tag_fields
    } catch {
        & $script:MediaToolsLogger  "INFO" "No valid geotag found in: $($File.FullName)."
        throw
    }
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
        & $script:MediaToolsLogger  "ERROR" "$errorMessage"
        throw [System.IO.FileNotFoundException]$errorMessage
    }

    # Validate the GeoTag
    if ([string]::IsNullOrEmpty($GeoTag)) {
        $errorMessage = "No geotag provided."
        & $script:MediaToolsLogger  "ERROR" "$errorMessage"
        throw [System.ArgumentNullException]$errorMessage
    }

    if (-not (IsValid_GeoTag -GeoTag $GeoTag)) {
        $errorMessage = "Invalid geotag provided: $GeoTag"
        & $script:MediaToolsLogger  "ERROR" "$errorMessage"
        throw [System.FormatException]$errorMessage
    } # This check is redundant with IsValid_GeoTag

    # Parse GeoTag into latitude and longitude
    $geoParts = $GeoTag -split ","
    if ($geoParts.Count -ne 4) {
        $errorMessage = "GeoTag does not have exactly 4 parts: $GeoTag"
        & $script:MediaToolsLogger  "ERROR" "$errorMessage"
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
            "-GPSLatitude=`'$latitude`'",
            "-GPSLatitudeRef=`'$latitudeRef`'",
            "-GPSLongitude=`'$longitude`'",
            "-GPSLongitudeRef=`'$longitudeRef`'"
        )

        # Run ExifTool command
        $temp_GeoTag = Run_ExifToolCommand -Arguments $exifArgs -File $File
        return $temp_GeoTag
    } catch {
        & $script:MediaToolsLogger  "WARNING" "Failed to write geotag for file: $fullPath."
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
        [string[]]$GeoTags
    )

    foreach ($geotag in $GeoTags) {
        # With the refactored IsValid_GeoTag, no try/catch is needed here.
        if (IsValid_GeoTag -GeoTag $geotag) {
            # Return the first valid geotag found.
            return $geotag
        }
    }

    # If no valid geotag was found, return null.
    return $null
}

function Find-ValidGeotag {
    param (
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$File  # The media file path (image or video)
    )

    # Get the full path of the file
    $fullPath = $File.FullName
    $JsonPath = "${fullPath}.json"

    # Create an ordered list of potential geotag sources.
    # The order determines the priority.
    $potentialGeoTags = [System.Collections.Generic.List[string]]::new()

    # Get the geotag from the JSON metadata if the JSON file exists
    if (Test-Path -Path $JsonPath) {
        try {
            $JsonFile = [System.IO.FileInfo]$JsonPath
            $potentialGeoTags.Add($(Get_Json_Geotag -JsonFile $JsonFile))
        } catch {
            & $script:MediaToolsLogger "DEBUG" "Could not get geotag from JSON for $($File.Name): $($_.Exception.Message)"
        }
    }

    # Get the geotag from the Exif metadata
    try {
        $potentialGeoTags.Add($(Get_Exif_Geotag -File $File))
    } catch {
        & $script:MediaToolsLogger "DEBUG" "Could not get geotag from EXIF for $($File.Name): $($_.Exception.Message)"
    }

    # Get the geotag from the ffprobe
    try {
        $potentialGeoTags.Add($(Get_Ffprobe_Geotag -File $File))
    } catch {
        & $script:MediaToolsLogger "DEBUG" "Could not get geotag from FFprobe for $($File.Name): $($_.Exception.Message)"
    }

    # Use the new Compare_Geotag to find the best one
    $bestGeoTag = Compare_Geotag -GeoTags $potentialGeoTags

    if ($null -ne $bestGeoTag) {
        & $script:MediaToolsLogger "INFO" "Determined valid geotag: $bestGeoTag for $($File.Name)"
        return $bestGeoTag
    } else {
        # If no valid geotag could be determined
        $noValidGeotagMsg = "No valid geotag could be determined for file: $($File.FullName)"
        & $script:MediaToolsLogger "WARNING" $noValidGeotagMsg # Log as warning
        throw [System.FormatException]::new($noValidGeotagMsg) # Throw specific error
    }
}

function Get_Ffprobe_Timestamp {
    param (
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$File
    )
    $metadata = Run_FfprobeCommand -File $File
    if (-not $metadata) { return $null }

    # The 'creation_time' tag is the most common and reliable source for a timestamp.
    $timestampString = $metadata.format.tags.creation_time
    if ($timestampString) {
        try {
            return Standardize_TimeStamp -InputTimestamp $timestampString
        } catch {
            & $script:MediaToolsLogger "DEBUG" "Could not standardize ffprobe timestamp '$timestampString' for $($File.Name)."
        }
    }
    return $null # Return null if no valid timestamp was found
}

function Get_Ffprobe_Geotag {
    param (
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$File
    )
    $metadata = Run_FfprobeCommand -File $File
    if (-not $metadata) { return $null }

    try {
        # Location is often in an ISO 6709 string in one of these tags
        $locationString = $metadata.format.tags.'com.apple.quicktime.location.ISO6709' -or $metadata.format.tags.location

        if ($locationString -and $locationString -match '([+-]\d+\.\d+)([+-]\d+\.\d+)') {
            $latitude = [double]$matches[1]
            $longitude = [double]$matches[2]
            # Standardize the geotag using the helper functions
            return Standardize_GeoTag -InputGeoTag "$latitude,$longitude"
        }
    } catch {
        & $script:MediaToolsLogger "WARNING" "Could not parse ffprobe JSON or find geotag for '$($File.Name)'. Error: $($_.Exception.Message)"
    }
    return $null # Return null if no valid geotag was found
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
    & $script:MediaToolsLogger  "INFO" "Moved $($filePath.FullName) to $category"
    return $category
}

#===========================================================
#                 Categorization functions
#===========================================================
function Categorize_Media_Based_On_Metadata {
    param (
        [System.IO.FileInfo]$SrcFile
    )
    try {
        $timestamp = IsValid_TimeStamp -timestamp_in $(Get_Exif_Timestamp -File $SrcFile)
    } catch {
        & $script:MediaToolsLogger  "INFO" "Failed to get timestamp for file '$($SrcFile.FullName)': $_"
        $timestamp = $false
    }
    try {
        $geotag = IsValid_GeoTag -GeoTag $(Get_Exif_Geotag -File $SrcFile)
    } catch {
        & $script:MediaToolsLogger  "INFO" "Failed to get geotag for file '$($SrcFile.FullName)': $_"
        $geotag = $false
    }

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

Export-ModuleMember -Function * -Variable imageExtensions, videoExtensions