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
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
} else {
    # Clean the directory before the run
    Write-Host "Clearing previous output directory: $OutputDirectory"
    Get-ChildItem -Path $OutputDirectory -Recurse | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

# --- Logging Setup ---
$logDir = Join-Path $scriptDirectory "Logs"
$logFilePath = Join-Path $logDir "main_pipeline.log"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
} else {
    # Clean the directory before the run
    Write-Host "Clearing previous logs directory: $logDir"
    Get-ChildItem -Path $logDir -Recurse | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
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

# --- Initialize the Centralized Logger from the Utils module ---
Initialize-Logger -LogFilePath $logFilePath -ConsoleLogLevel $consoleLogLevel -FileLogLevel $fileLogLevel -LogLevelMap $logLevelMap

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
            & $pythonExe "$ScriptPath" 
        } else {
            # Use argument splatting (@Arguments) to pass array elements as separate arguments
            $argStringForLog = $Arguments | ForEach-Object { """$_""" } | Join-String -Separator ' ' # Quote args for logging
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

# --- Pipeline Definition ---
$pipelineSteps = @(
    @{ Name = "Initial File Count"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @("$scriptDirectory/Logs/FileReport_$($logger).txt", "$unzippedDirectory") },
    @{ Name = "Extract Zip Files"; Type = "PowerShell"; Path = "step1 - Extract\Extract.ps1"; Args = @{ unzippedDirectory = $unzippedDirectory; zippedDirectory = $zipDirectory; extractor = $7zip } },
    @{ Name = "File Count After Extract"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @("$scriptDirectory/Logs/FileReport_$($logger).txt", "$unzippedDirectory") },
    @{ Name = "Sanitize Directory Names"; Type = "PowerShell"; Path = "step2 - clean_json_names\CleanJsonNames.ps1"; Args = @{ unzippedDirectory = $unzippedDirectory } },
    @{ Name = "File Count After Sanitize"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @("$scriptDirectory/Logs/FileReport_$($logger).txt", "$unzippedDirectory") },
    @{ Name = "Clean JSON Filenames"; Type = "PowerShell"; Path = "step3 - clean_json\clean_json.ps1"; Args = @{ unzippedDirectory = $unzippedDirectory; zippedDirectory = $zipDirectory; ExifToolPath = $ExifToolPath } },
    @{ Name = "File Count After JSON Clean"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @("$scriptDirectory/Logs/FileReport_$($logger).txt", "$unzippedDirectory") },
    @{ Name = "Remove Orphaned JSON"; Type = "PowerShell"; Path = "step4 - ListandRemoveOrphanedJSON\remove_orphaned_json.ps1"; Args = @{ unzippedDirectory = $unzippedDirectory } },
    @{ Name = "File Count After Orphan-Removal"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @("$scriptDirectory/Logs/FileReport_$($logger).txt", "$unzippedDirectory") },
    @{ Name = "Convert Media to Standard Formats"; Type = "PowerShell"; Path = "step5 - converter\converter.ps1"; Args = @{ unzippedDirectory = $unzippedDirectory; ffmpeg = $ffmpeg; magickPath = $magickPath } },
    @{ Name = "File Count After Conversion"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @("$scriptDirectory/Logs/FileReport_$($logger).txt", "$unzippedDirectory") },
    @{ Name = "Consolidate Metadata"; Type = "PowerShell"; Path = "step6 - Consolidate_Meta\Consolidate_Meta.ps1"; Args = @{ unzippedDirectory = $unzippedDirectory; ExifToolPath = $ExifToolPath } },
    @{ Name = "File Count After Meta-Consolidation"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @("$scriptDirectory/Logs/FileReport_$($logger).txt", "$unzippedDirectory") },
    @{ Name = "Remove Recycle Bin"; Type = "PowerShell"; Path = "step7 - Remove_RecycleBin\RemoveRecycleBin.ps1"; Args = @{ unzippedDirectory = $unzippedDirectory } },
    @{ Name = "File Count After Recycle-Removal"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @("$scriptDirectory/Logs/FileReport_$($logger).txt", "$unzippedDirectory") },
    @{ Name = "Hash/Group Video Duplicates"; Type = "Python"; Path = "step8 - HashAndGroup\HashANDGroupPossibleVideoDuplicates.py"; Args = @("$unzippedDirectory\") },
    @{ Name = "Hash/Group Image Duplicates"; Type = "Python"; Path = "step8 - HashAndGroup\HashANDGroupPossibleImageDuplicates.py"; Args = @("$unzippedDirectory\") },
    @{ Name = "File Count After Hashing"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @("$scriptDirectory/Logs/FileReport_$($logger).txt", "$unzippedDirectory") },
    @{ Name = "Remove Exact Video Duplicates"; Type = "Python"; Path = "step9 - RemoveExactDuplicates\RemoveExactVideoDuplicate.py" },
    @{ Name = "Remove Exact Image Duplicates"; Type = "Python"; Path = "step9 - RemoveExactDuplicates\RemoveExactImageDuplicate.py" },
    @{ Name = "File Count After Exact-Dup-Removal"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @("$scriptDirectory/Logs/FileReport_$($logger).txt", "$unzippedDirectory") },
    @{ Name = "Review/Remove Potential Video Duplicates"; Type = "Python"; Path = "step10 - ShowANDRemoveDuplicate\ShowANDRemoveDuplicateVideo.py" },
    @{ Name = "Review/Remove Potential Image Duplicates"; Type = "Python"; Path = "step10 - ShowANDRemoveDuplicate\ShowANDRemoveDuplicateImage.py" },
    @{ Name = "File Count After Potential-Dup-Removal"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @("$scriptDirectory/Logs/FileReport_$($logger).txt", "$unzippedDirectory") },
    @{ Name = "Remove Junk Videos"; Type = "Python"; Path = "step11 - RemoveJunk\RemoveJunkVideo.py"; Args = @("$unzippedDirectory\") },
    @{ Name = "Remove Junk Images"; Type = "Python"; Path = "step11 - RemoveJunk\RemoveJunkImage.py"; Args = @("$unzippedDirectory\") },
    @{ Name = "File Count After Junk-Removal"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @("$scriptDirectory/Logs/FileReport_$($logger).txt", "$unzippedDirectory") },
    @{ Name = "Reconstruct Corrupt Videos"; Type = "PowerShell"; Path = "Step12 - Reconstruction\VideoReconstruction.ps1"; Args = @{ vlcpath = $vlcpath; reconstructListPath = (Join-Path $OutputDirectory "video_reconstruct_info.json"); ffmpeg = $ffmpeg; ffprobe = $ffprobe } },
    @{ Name = "Reconstruct Corrupt Images"; Type = "PowerShell"; Path = "Step12 - Reconstruction\ImageReconstruction.ps1"; Args = @{ magickPath = $magickPath; reconstructListPath = (Join-Path $OutputDirectory "image_reconstruct_info.json") } },
    @{ Name = "File Count After Reconstruction"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @("$scriptDirectory/Logs/FileReport_$($logger).txt", "$unzippedDirectory") },
    @{ Name = "Categorize Files"; Type = "PowerShell"; Path = "step13 - Categorization\Categorize.ps1"; Args = @{ unzippedDirectory = $unzippedDirectory; ExifToolPath = $ExifToolPath } },
    @{ Name = "File Count After Categorization"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @("$scriptDirectory/Logs/FileReport_$($logger).txt", "$unzippedDirectory") },
 #   @{ Name = "Estimate Location By Time"; Type = "PowerShell"; Path = "step14  - Estimate By Time\EstimateByTime.ps1"; Args = @{ unzippedDirectory = $unzippedDirectory; ExifToolPath = $ExifToolPath }; Enabled = $false },
     @{ Name = "Final File Count"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @("$scriptDirectory/Logs/FileReport_$($logger).txt", "$unzippedDirectory"); Enabled = $false }
)

try {
    # --- Main Pipeline Execution Loop ---
    foreach ($step in $pipelineSteps) {
        # Check if the step is explicitly disabled
        if ($step.ContainsKey('Enabled') -and -not $step.Enabled) {
            Log "INFO" "Skipping disabled step: $($step.Name)"
            continue
        }

        Log "INFO" "Executing Step: $($step.Name)"
        $fullPath = Join-Path -Path $scriptDirectory -ChildPath $step.Path

        if ($step.Type -eq "PowerShell") {
            # For PowerShell, add the step number to the arguments hashtable
            $step.Args.step = $logger.ToString()
            $psArgs = $step.Args # Assign to a temporary variable for splatting
            & $fullPath @psArgs
            # After the child script runs, re-initialize the logger for the main script
            Initialize-Logger -LogFilePath $logFilePath -ConsoleLogLevel $consoleLogLevel -FileLogLevel $fileLogLevel -LogLevelMap $logLevelMap
        } elseif ($step.Type -eq "Python") {
            $env:CURRENT_STEP = $logger.ToString()
            Invoke-PythonScript -ScriptPath $fullPath -Arguments $step.Args
        }
        $logger++
    }
} finally {
    # This block ensures the progress bar is closed even if an error occurs in the pipeline.
    Log "INFO" "Pipeline finished or stopped. Closing progress bar."
    Stop-GraphicalProgressBar
}

Log "INFO" "Media Organizer pipeline completed."
