<#
param(
    [Parameter(Mandatory=$true)]
    [string]$zipDirectory = 'C:\Users\sawye\Downloads\test\input',
    [Parameter(Mandatory=$true)]
    [string]$unzippedDirectory = 'C:\Users\sawye\Downloads\test\output',
    [Parameter(Mandatory=$true)]
    [string]$7zip = 'C:\Program Files\7-Zip\7z.exe',
    [Parameter(Mandatory=$true)]
    [string]$ExifToolPath = 'C:\Program Files\exiftools\exiftool.exe',
    [Parameter(Mandatory=$true)]
    [string]$magickPath = 'C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe',
    [Parameter(Mandatory=$true)]
    [string]$pythonExe = 'C:\Program Files\Python313\python.exe',
    [Parameter(Mandatory=$true)]
    [string]$ffmpeg = 'C:\Program Files\ffmpeg\bin\ffmpeg.exe',
    [Parameter(Mandatory=$true)]
    [string]$ffprobe = 'C:\Program Files\ffmpeg\bin\ffprobe.exe',
    [Parameter(Mandatory=$true)]
    [string]$vlcpath = "C:\Program Files\VideoLAN\VLC\vlc.exe",
    [Parameter(Mandatory=$true)]
    [string]$DefaultConsoleLogLevelString = "WARNING",
    [Parameter(Mandatory=$true)]
    [string]$DefaultFileLogLevelString    = "WARNING"      
    [Parameter(Mandatory=$true)]
    [int]$DefaultPrefixLength    = 15 
)
#>
$zipDirectory = 'C:\Users\sawye\Downloads\test\input'
$unzippedDirectory = 'C:\Users\sawye\Downloads\test\output'
$7zip = 'C:\Program Files\7-Zip\7z.exe'
$ExifToolPath = 'C:\Program Files\exiftools\exiftool.exe'
$magickPath = 'C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe'
$pythonExe = 'C:\Program Files\Python313\python.exe'
$ffmpeg  = 'C:\Program Files\ffmpeg\bin\ffmpeg.exe'
$ffprobe = 'C:\Program Files\ffmpeg\bin\ffprobe.exe'
$vlcpath = "C:\Program Files\VideoLAN\VLC\vlc.exe"
$DefaultConsoleLogLevelString = "ERROR"
$DefaultFileLogLevelString    = "DEBUG"  
$DefaultPrefixLength  = 15

$default_width = 80 # Default if env var or terminal size fails
$screenWidth = $Host.UI.RawUI.WindowSize.Width - 30
$barLength = [math]::Min($screenWidth, $default_width)

$env:FFPROBE_PATH = $ffprobe
$env:MAGICK_PATH = $magickPath
$env:FFMPEG_PATH = $ffmpeg
$env:EXIFTOOL_PATH = $ExifToolPath
$env:PROGRESS_BAR_LENGTH = $barLength
$env:DEFAULT_PREFIX_LENGTH = $DefaultPrefixLength
$env:DEFAULT_CONSOLE_LEVEL_STR = $DefaultConsoleLogLevelString
$env:DEFAULT_FILE_LEVEL_STR = $DefaultFileLogLevelString
$env:ENABLE_PYTHON_DEBUG = '1'
Clear-Host
$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$logger = 0

#Utils Dirctory
$UtilDirectory = Join-Path $scriptDirectory "\Utils"
$UtilFile = Join-Path $UtilDirectory "Utils.psm1"
Import-Module $UtilFile -Force

#Outputs Dirctory
$OutputDirectory = Join-Path $scriptDirectory "\Outputs"
if (-not (Test-Path $OutputDirectory)) {
    New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
}

# --- Logging Setup ---
$logDir = Join-Path $scriptDirectory "Logs"
$logFilePath = Join-Path $logDir "main_pipeline.log"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

# Define the map ONCE
$logLevelMap = @{
    "DEBUG"    = 0
    "INFO"     = 1
    "WARNING"  = 2
    "ERROR"    = 3
    "CRITICAL" = 4
}

# --- Set the map in the environment variable for child scripts ---
$env:LOG_LEVEL_MAP_JSON = $logLevelMap | ConvertTo-Json -Compress

# --- Set Environment Variables for Children (if not already set externally) ---
# This ensures child scripts inherit the correct default if no override exists.
if ($null -eq $env:DEDUPLICATOR_CONSOLE_LOG_LEVEL) {
    $env:DEDUPLICATOR_CONSOLE_LOG_LEVEL = $DefaultConsoleLogLevelString
}
if ($null -eq $env:DEDUPLICATOR_FILE_LOG_LEVEL) {
    $env:DEDUPLICATOR_FILE_LOG_LEVEL = $DefaultFileLogLevelString
}

# --- Determine log levels for THIS script (top.ps1) ---
# Now, read the environment variables (which are guaranteed to be set by the logic above)
$EffectiveConsoleLogLevelString = $env:DEDUPLICATOR_CONSOLE_LOG_LEVEL
$EffectiveFileLogLevelString    = $env:DEDUPLICATOR_FILE_LOG_LEVEL

# Look up the numeric level using the effective string and the map
$consoleLogLevel = $logLevelMap[$EffectiveConsoleLogLevelString.ToUpper()]
$fileLogLevel    = $logLevelMap[$EffectiveFileLogLevelString.ToUpper()]

# --- Validation and fallback for THIS script's levels (in top.ps1) ---
if ($null -eq $consoleLogLevel) {
    Write-Error "FATAL: Invalid Console Log Level specified ('$EffectiveConsoleLogLevelString'). Check environment variable DEDUPLICATOR_CONSOLE_LOG_LEVEL or script default. Aborting."
    exit 1
}

if ($null -eq $fileLogLevel) {
    Write-Error "FATAL: Invalid File Log Level specified ('$EffectiveFileLogLevelString'). Check environment variable DEDUPLICATOR_FILE_LOG_LEVEL or script default. Aborting."
    exit 1
}

function Log {
    param (
        [string]$Level,
        [string]$Message
    )
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logFormat = "{0} - {1}: {2}"
    $formatted = $logFormat -f $timestamp, $Level.ToUpper(), $Message
    $levelIndex = $logLevelMap[$Level.ToUpper()]

    if ($null -ne $levelIndex) {
        if ($levelIndex -ge $consoleLogLevel) {
            Write-Host $formatted
        }
        if ($levelIndex -ge $fileLogLevel) {
            try {
                Add-Content -Path $logFilePath -Value $formatted -Encoding UTF8 -ErrorAction Stop
            } catch {
                Write-Warning "Failed to write to log file '$logFilePath': $_"
            }
        } 
    } else {
        Write-Warning "Invalid log level used: $Level"
    } 
}

if (-not (Test-Path -Path $ffmpeg -PathType Leaf)) {
    Log "CRITICAL" "FFmpeg executable not found at specified path: '$ffmpeg'. Aborting."
    exit 1
}

if (-not (Test-Path $7zip)) {
    Log "ERROR" "7-Zip not found at $7zip. Aborting."
    exit 1
}

if (-not (Test-Path $ExifToolPath)) {
    Log "ERROR" "Exiftools not found at $ExifToolPath. Aborting."
    exit 1
}

if (-not (Test-Path $magickPath)) {
    Log "ERROR" "magik not found at $magickPath. Aborting."
    exit 1
}

if (-not (Test-Path $ffmpeg)) {
    Log "ERROR" "ffmpeg not found at $ffmpeg. Aborting."
    exit 1
}

# Function to run a Python script with error handling
function Invoke-PythonScript {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath,

        # Change the type to accept an array of strings
        [string[]]$Arguments
    )

    # Ensure $pythonExe is accessible here (it should be if defined at script scope)
    if (-not $pythonExe) {
        Log "ERROR" "Python executable path variable `$pythonExe is not defined."
        exit 1
    }

    try {
        # Check if the Arguments array is null or empty
        if ($null -eq $Arguments -or $Arguments.Count -eq 0) {
            Log "DEBUG" "Executing: $pythonExe ""$ScriptPath"""
            # --- MODIFICATION: Redirect stderr (2>) to $null ---
            & $pythonExe "$ScriptPath" # Removed 2>$null
        } else {
            # Use argument splatting (@Arguments) to pass array elements as separate arguments
            $argStringForLog = $Arguments | ForEach-Object { """$_""" } | Join-String -Separator ' ' # Quote args for logging
            Log "DEBUG" "Executing: $pythonExe ""$ScriptPath"" $argStringForLog"
            # --- MODIFICATION: Redirect stderr (2>) to $null ---
            & $pythonExe "$ScriptPath" @Arguments # Removed 2>$null
        }

        # Check PowerShell's automatic variable $? for success AFTER the command
        if (-not $?) {
             # $LASTEXITCODE might contain the Python script's exit code if it wasn't 0
             $exitCode = $LASTEXITCODE
             throw "Python script '$ScriptPath' failed with exit code $exitCode."
        }

    } catch {
        # Log the error message constructed by the throw or other exceptions
        Log "ERROR" "Error running Python script '$ScriptPath'. Error: $_"
        # Consider if exiting immediately is always desired
        exit 1
    }
}

try {

    $pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
    Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/FileReport_$logger.txt", "$unzippedDirectory")
    $logger++

    # step 1 - Extract Zip Files
    Log "INFO" "step1 - Extract Zip Files"
    & "$scriptDirectory\step1 - Extract\Extract.ps1" -unzippedDirectory $unzippedDirectory -zippedDirectory $zipDirectory -extractor $7zip -step $logger.ToString()
    write-host ""

    #count
    $pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
    Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/FileReport_$logger.txt", "$unzippedDirectory")
    $logger++

    # step 2 - Sanetize the names
    Log "INFO" "step2 - Sanetize the names"
    & "$scriptDirectory\step2 - clean_json_names\CleanJsonNames.ps1" -unzippedDirectory $unzippedDirectory -step $logger.ToString()

    #count
    $pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
    Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/FileReport_$logger.txt", "$unzippedDirectory")
    $logger++

    #step3 - clean json names json files
    Log "INFO" "step3 - clean json names json files"
    & "$scriptDirectory\step3 - clean_json\clean_json.ps1"  -unzippedDirectory $unzippedDirectory -zippedDirectory $zippedDirectory -ExifToolPath $ExifToolPath -step $logger.ToString()
    write-host ""

    #count
    $pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
    Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/FileReport_$logger.txt", "$unzippedDirectory")
    $logger++

    #step 4 - remove orphaned json files
    Log "INFO" "step4 - remove orphaned json files"
    & "$scriptDirectory\step4 - ListandRemoveOrphanedJSON\remove_orphaned_json.ps1" -unzippedDirectory $unzippedDirectory -step $logger.ToString()
    write-host ""

    #count
    $pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
    Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/FileReport_$logger.txt", "$unzippedDirectory")
    $logger++

    # step 5 - use converter to change everything to mp4 & jpg
    Log "INFO" "step5 - use converter to change everything to mp4 & jpg"
    & "$scriptDirectory\step5 - converter\converter.ps1" -unzippedDirectory $unzippedDirectory -ffmpeg $ffmpeg -magickPath $magickPath -step $logger.ToString()

    #count
    $pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
    Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/FileReport_$logger.txt", "$unzippedDirectory")
    $logger++

    #step 6 use step6 - Consolidate_Meta to combine time stamps
    Log "INFO" "step6 use 6 - Consolidate_Meta to combine time stamps"
    & "$scriptDirectory\step6 - Consolidate_Meta\Consolidate_Meta.ps1" -unzippedDirectory "$unzippedDirectory" -ExifToolPath "$ExifToolPath" -step $logger.ToString()
    write-host ""

    #count
    $pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
    Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/FileReport_$logger.txt", "$unzippedDirectory")
    $logger++

    #step 7 - $RECYCLE.BIN
    Log "INFO" "Step 7 remove RECYCLE.BIN"
    & "$scriptDirectory\step7 - Remove_RecycleBin\RemoveRecycleBin.ps1" -unzippedDirectory $unzippedDirectory -step $logger.ToString()

    #count
    $pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
    Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/FileReport_$logger.txt", "$unzippedDirectory")
    $logger++

    #step 8-1 - Hash and Group Possible Video Duplicates
    $env:CURRENT_STEP = $logger.ToString()
    Log "INFO" "Step 8-1 Hash AND Group Possible Video Duplicates to extract groups"
    $pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step8 - HashAndGroup\HashANDGroupPossibleVideoDuplicates.py'
    Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments "$unzippedDirectory\"

    #step 8-2 - Hash and Group Possible Image Duplicates
    Log "INFO" "Step 8-2 Hash AND Group Possible Image Duplicates to extract groups"
    $pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step8 - HashAndGroup\HashANDGroupPossibleImageDuplicates.py'
    Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments "$unzippedDirectory\"

    #count
    $pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
    Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/FileReport_$logger.txt", "$unzippedDirectory")
    $logger++

    #step 9-1 Remove Exact Video Duplicate
    $env:CURRENT_STEP = $logger.ToString()
    Log "INFO" "step 9-1 Remove Exact Video Duplicate"
    $pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step9 - RemoveExactDuplicates\RemoveExactVideoDuplicate.py'
    Invoke-PythonScript -ScriptPath $pythonScriptPath

    #step 9-2 Remove Exact Image Duplicate
    Log "INFO" "step 9-2 Remove Exact Image Duplicate"
    $pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step9 - RemoveExactDuplicates\RemoveExactImageDuplicate.py'
    Invoke-PythonScript -ScriptPath $pythonScriptPath

    #count
    $pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
    Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/FileReport_$logger.txt", "$unzippedDirectory")
    $logger++

    #step 10-1 Show AND Remove Duplicate Video
    $env:CURRENT_STEP = $logger.ToString()
    Log "INFO" "step 10-1 Show AND Remove Duplicate Video"
    $pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step10 - ShowANDRemoveDuplicate\ShowANDRemoveDuplicateVideo.py'
    Invoke-PythonScript -ScriptPath $pythonScriptPath

    #step 10-2 Show AND Remove Duplicate Image
    Log "INFO" "step 10-1 Show AND Remove Duplicate Image"
    $pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step10 - ShowANDRemoveDuplicate\ShowANDRemoveDuplicateImage.py'
    Invoke-PythonScript -ScriptPath $pythonScriptPath

    #count
    $pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
    Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/FileReport_$logger.txt", "$unzippedDirectory")
    $logger++

    #step 11-1 Remove Junk Video
    $env:CURRENT_STEP = $logger.ToString()
    Log "INFO" "step 11-1 use RemoveJunkVideo.py to remove junk Videos"
    $pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step11 - RemoveJunk\RemoveJunkVideo.py'
    Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments "$unzippedDirectory\"

    #step 11-2 Remove Junk Image
    Log "INFO" "step 11-2 use RemoveJunkImage.py to remove junk Videos"
    $pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step11 - RemoveJunk\RemoveJunkImage.py'
    Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments "$unzippedDirectory\"

    #count
    $pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
    Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/FileReport_$logger.txt", "$unzippedDirectory")
    $logger++

    #step 12-1 Reconstruction of corrupt Videos
    $env:CURRENT_STEP = $logger.ToString()
    Log "INFO" "step 12-1 use VideoReconstruction.ps1 to Reconstruct of corrupt Videos" -ffmpeg $ffmpeg
    $videoReconList = Join-Path $scriptDirectory "Outputs\video_reconstruct_info.json"
    & "$scriptDirectory\step12 - Reconstruction\VideoReconstruction.ps1" -vlcpath $vlcpath -reconstructListPath $videoReconList -ffmpeg $ffmpeg -ffprobe $ffprobe

    #step 12-2 Reconstruction of corrupt Images
    Log "INFO" "step 12-2 use ImageReconstruction.ps1 to Reconstruct of corrupt Images" -magickPath $magickPath
    $imageReconList = Join-Path $scriptDirectory "Outputs\image_reconstruct_info.json" # Or wherever it's actually saved
    & "$scriptDirectory\step12 - Reconstruction\ImageReconstruction.ps1" -magickPath $magickPath -reconstructListPath $imageReconList

    #count
    $pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
    Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/FileReport_$logger.txt", "$unzippedDirectory")
    $logger++

    #step 13 Categorization
    $env:CURRENT_STEP = $logger.ToString()
    Log "INFO" "step 13 use Categorize.ps1 to categorize files based on the availability of meta data"
    & "$scriptDirectory\step13 - Categorization\Categorize.ps1" -unzippedDirectory $unzippedDirectory -ExifToolPath $ExifToolPath

    #count
    $pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
    Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/FileReport_$logger.txt", "$unzippedDirectory")
    $logger++

    #step 14 Estimate By Time
    Log "INFO" "step 14 use EstimateByTime.ps1 to Estimate Location of Files"
    & "$scriptDirectory\step14  - Estimate By Time\EstimateByTime.ps1" -unzippedDirectory $unzippedDirectory -ExifToolPath $ExifToolPath

    #count
    $pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
    Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/FileReport_$logger.txt", "$unzippedDirectory")
    $logger++

}
finally {
    # Ensure the progress bar is closed when the script finishes or errors out
    Log "INFO" "Pipeline finished or stopped. Closing progress bar."
    Stop-GraphicalProgressBar
}

Log "INFO" "Media Organizer pipeline completed."
