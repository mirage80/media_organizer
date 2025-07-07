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

#Utils Dirctory
$UtilDirectory = Join-Path $scriptDirectory "Utils"
$UtilFile = Join-Path $UtilDirectory "Utils.psm1"
Import-Module $UtilFile -Force

# --- Logging Setup ---
# Initialize logging early to capture all setup actions.
$logDir = Join-Path $scriptDirectory "Logs"
$logFilePath = Join-Path $logDir "main_pipeline.log"

# Define the map ONCE
$logLevelMap = @{
    "DEBUG"    = 0
    "INFO"     = 1
    "WARNING"  = 2
    "ERROR"    = 3
    "CRITICAL" = 4
}

#Outputs Dirctory
$OutputDirectory = Join-Path $scriptDirectory "Outputs"
if (-not (Test-Path $OutputDirectory)) {
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
} 

if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
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
# Create a local, pre-configured logger for this script. This is a "closure" that captures the logging config.
$Log = {
    param([string]$Level, [string]$Message)
    # Call the master, stateless logger from the module with all required configuration
    Write-Log -Level $Level -Message $Message -LogFilePath $logFilePath -ConsoleLogLevel $consoleLogLevel -FileLogLevel $fileLogLevel -LogLevelMap $logLevelMap
}
# Ensure the log file is created at the start
& $Log "INFO" "--- Main Pipeline Started ---"

# --- Consolidated Tool Validation ---
$requiredTools = @(
    @{ Name = "7-Zip"; Path = $7zip; PathType = 'Leaf' }
    @{ Name = "ExifTool"; Path = $ExifToolPath; PathType = 'Leaf' }
    @{ Name = "ImageMagick"; Path = $magickPath; PathType = 'Leaf' }
    @{ Name = "FFmpeg"; Path = $ffmpeg; PathType = 'Leaf' }
    @{ Name = "FFprobe"; Path = $ffprobe; PathType = 'Leaf' }
    @{ Name = "VLC"; Path = $vlcpath; PathType = 'Leaf' }
    @{ Name = "Python"; Path = $pythonExe; PathType = 'Leaf' }
)

foreach ($tool in $requiredTools) {
    if (-not (Test-Path -Path $tool.Path -PathType $tool.PathType)) {
        & $Log "CRITICAL" "Required tool '$($tool.Name)' not found at specified path: '$($tool.Path)'. Aborting."
        exit 1
    }
}

function Invoke-PythonScript { # Event-driven implementation
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath,
        [Parameter(Mandatory = $true)]
        [string]$ActivityName,
        [string[]]$Arguments
    )

    $outputEvent = $null
    $errorEvent = $null

    try {
        $processInfo = New-Object System.Diagnostics.ProcessStartInfo
        $processInfo.FileName = $pythonExe
        $processInfo.Arguments = @("`"$ScriptPath`"") + $Arguments -join ' '
        $processInfo.RedirectStandardOutput = $true
        $processInfo.RedirectStandardError = $true
        $processInfo.UseShellExecute = $false
        $processInfo.CreateNoWindow = $true
        $processInfo.StandardOutputEncoding = [System.Text.Encoding]::UTF8
        $processInfo.StandardErrorEncoding = [System.Text.Encoding]::UTF8

        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $processInfo

        $stdErrLines = [System.Collections.ArrayList]::Synchronized((New-Object System.Collections.ArrayList))
        $localStdErrLines = $stdErrLines

        $onOutputDataReceived = {
            if ($null -ne $EventArgs.Data) {
                $line = $EventArgs.Data
                # Accept both formats: PROGRESS:<percent>|status OR current total message
                if ($line -match '^PROGRESS:(\d{1,3})\|(.*)$') {
                    $percent = [int]$matches[1]
                    $status = $matches[2].Trim()
                    Write-Progress -Activity $using:ActivityName -Status $status -PercentComplete $percent
                } elseif ($line -match '^(\d+)\s+(\d+)\s+(.+)$') {
                    $current = [int]$matches[1]
                    $total = [int]$matches[2]
                    $status = $matches[3].Trim()
                    $percent = [int](($current / [math]::Max($total,1)) * 100)
                    Write-Progress -Activity $using:ActivityName -Status $status -PercentComplete $percent
                } else {
                    & $using:Log "DEBUG" "PY_STDOUT: $line"
                }
            }
        }

        $onErrorDataReceived = {
            if ($null -ne $EventArgs.Data) {
                $line = $EventArgs.Data
                & $using:Log "ERROR" "PY_STDERR: $line"
                [void]$localStdErrLines.Add($line)
            }
        }

        $outputEvent = Register-ObjectEvent -InputObject $process -EventName 'OutputDataReceived' -Action $onOutputDataReceived
        $errorEvent = Register-ObjectEvent -InputObject $process -EventName 'ErrorDataReceived' -Action $onErrorDataReceived

        $argStringForLog = $Arguments | ForEach-Object { """$_""" } | Join-String -Separator ' '
        & $Log "DEBUG" "Executing: $pythonExe ""$ScriptPath"" $argStringForLog"
        
        [void]$process.Start()
        $process.BeginOutputReadLine()
        $process.BeginErrorReadLine()
        $process.WaitForExit()

        if ($process.ExitCode -ne 0) {
            $errorOutput = $stdErrLines -join "`n"
            throw "Python script '$ScriptPath' failed with exit code $($process.ExitCode). Output:`n$errorOutput"
        }
        Write-Progress -Activity $ActivityName -Status "Completed" -Completed
    } catch {
        & $Log "ERROR" "Error running Python script '$ScriptPath'. Error: $_"
        Write-Progress -Activity $ActivityName -Status "Failed" -Completed
        exit 1
    } finally {
        if ($outputEvent) { Unregister-Event -SourceIdentifier $outputEvent.Name }
        if ($errorEvent) { Unregister-Event -SourceIdentifier $errorEvent.Name }
    }
}

# --- Pipeline Definition ---
$pipelineSteps = @(
    @{ Name = "Initial File Count"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @((Join-Path $scriptDirectory 'Logs' "FileReport_0.txt"), $unzippedDirectory); Enabled = $true },
    @{ Name = "Extract Zip Files"; Type = "PowerShell"; Path = "step1 - Extract\Extract.ps1"; Args = @{ unzippedDirectory = $unzippedDirectory; zippedDirectory = $zipDirectory; extractor = $7zip } ; Enabled = $true},
    @{ Name = "File Count After Extract"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @((Join-Path $scriptDirectory 'Logs' "FileReport_1.txt"), $unzippedDirectory) ; Enabled = $true},
    @{ Name = "Sanitize Names"; Type = "PowerShell"; Path = "step2 - SanitizeNames\SanitizeNames.ps1"; Args = @{ unzippedDirectory = $unzippedDirectory }; Enabled = $true },
    @{ Name = "File Count After Sanitize"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @((Join-Path $scriptDirectory 'Logs' "FileReport_2.txt"), $unzippedDirectory) ; Enabled = $true},
    @{ Name = "Map Google Photos JSON Data"; Type = "PowerShell"; Path = "step3 - MapGoogleJson\MapGoogleJson.ps1"; Args = @{ unzippedDirectory = $unzippedDirectory }; Enabled = $true },
    @{ Name = "File Count After JSON-Mapping"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @((Join-Path $scriptDirectory 'Logs' "FileReport_3.txt"), $unzippedDirectory) ; Enabled = $true },
    @{ Name = "Convert Media to Standard Formats"; Type = "PowerShell"; Path = "step4 - converter\converter.ps1"; Args = @{ unzippedDirectory = $unzippedDirectory; ffmpeg = $ffmpeg; magickPath = $magickPath } ; Enabled = $true},
    @{ Name = "File Count After Conversion"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @((Join-Path $scriptDirectory 'Logs' "FileReport_4.txt"), $unzippedDirectory) ; Enabled = $true},
    @{ Name = "Expand Metadata with EXIF/FFprobe"; Type = "PowerShell"; Path = "step5 - ExpandMetaData\ExpandMetadata.ps1"; Args = @{ unzippedDirectory = $unzippedDirectory; ExifToolPath = $ExifToolPath; ffprobe = $ffprobe }; Enabled = $true },
    @{ Name = "File Count After Metadata Expansion"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @((Join-Path $scriptDirectory 'Logs' "FileReport_5.txt"), $unzippedDirectory) ; Enabled = $true },
    @{ Name = "Consolidate Best Metadata"; Type = "PowerShell"; Path = "step6 - Consolidate_Meta\Consolidate_Meta.ps1"; Args = @{ unzippedDirectory = $unzippedDirectory; ExifToolPath = $ExifToolPath; ffprobe = $ffprobe }; Enabled = $true },
    @{ Name = "File Count After Meta Consolidation"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @((Join-Path $scriptDirectory 'Logs' "FileReport_6.txt"), $unzippedDirectory) ; Enabled = $true },
    @{ Name = "Remove Recycle Bin"; Type = "PowerShell"; Path = "step7 - Remove_RecycleBin\RemoveRecycleBin.ps1"; Args = @{ unzippedDirectory = $unzippedDirectory } ; Enabled = $false },
    @{ Name = "File Count After Recycle-Removal"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @((Join-Path $scriptDirectory 'Logs' "FileReport_7.txt"), $unzippedDirectory); Enabled = $false },
    @{ Name = "Hash/Group Video Duplicates"; Type = "Python"; Path = "step8 - HashAndGroup\HashANDGroupPossibleVideoDuplicates.py"; Args = @($unzippedDirectory) ; Enabled = $true},
    @{ Name = "Hash/Group Image Duplicates"; Type = "Python"; Path = "step8 - HashAndGroup\HashANDGroupPossibleImageDuplicates.py"; Args = @($unzippedDirectory) ; Enabled = $true},
    @{ Name = "File Count After Hashing"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @((Join-Path $scriptDirectory 'Logs' "FileReport_8.txt"), $unzippedDirectory); Enabled = $true },
    @{ Name = "Remove Exact Video Duplicates"; Type = "Python"; Path = "step9 - RemoveExactDuplicates\RemoveExactVideoDuplicate.py"; Args = @(); Enabled = $true },
    @{ Name = "Remove Exact Image Duplicates"; Type = "Python"; Path = "step9 - RemoveExactDuplicates\RemoveExactImageDuplicate.py"; Args = @(); Enabled = $true },
    @{ Name = "File Count After Exact-Dup-Removal"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @((Join-Path $scriptDirectory 'Logs' "FileReport_9.txt"), $unzippedDirectory); Enabled = $true },
    @{ Name = "Review/Remove Potential Video Duplicates"; Type = "Python"; Path = "step10 - ShowANDRemoveDuplicate\ShowANDRemoveDuplicateVideo.py"; Enabled = $false },
    @{ Name = "Review/Remove Potential Image Duplicates"; Type = "Python"; Path = "step10 - ShowANDRemoveDuplicate\ShowANDRemoveDuplicateImage.py"; Enabled = $false },
    @{ Name = "File Count After Potential-Dup-Removal"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @((Join-Path $scriptDirectory 'Logs' "FileReport_10.txt"), $unzippedDirectory); Enabled = $false },
    @{ Name = "Remove Junk Videos"; Type = "Python"; Path = "step11 - RemoveJunk\RemoveJunkVideo.py"; Args = @($unzippedDirectory); Enabled = $false },
    @{ Name = "Remove Junk Images"; Type = "Python"; Path = "step11 - RemoveJunk\RemoveJunkImage.py"; Args = @($unzippedDirectory); Enabled = $false },
    @{ Name = "File Count After Junk-Removal"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @((Join-Path $scriptDirectory 'Logs' "FileReport_11.txt"), $unzippedDirectory); Enabled = $false },
    @{ Name = "Reconstruct Corrupt Videos"; Type = "PowerShell"; Path = "Step12 - Reconstruction\VideoReconstruction.ps1"; Args = @{ vlcpath = $vlcpath; reconstructListPath = (Join-Path $OutputDirectory "video_reconstruct_info.json"); ffmpeg = $ffmpeg; ffprobe = $ffprobe } ; Enabled = $false},
    @{ Name = "Reconstruct Corrupt Images"; Type = "PowerShell"; Path = "Step12 - Reconstruction\ImageReconstruction.ps1"; Args = @{ magickPath = $magickPath; reconstructListPath = (Join-Path $OutputDirectory "image_reconstruct_info.json") } ; Enabled = $false},
    @{ Name = "File Count After Reconstruction"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @((Join-Path $scriptDirectory 'Logs' "FileReport_12.txt"), $unzippedDirectory); Enabled = $false },
    @{ Name = "Categorize Files"; Type = "PowerShell"; Path = "step13 - Categorization\Categorize.ps1"; Args = @{ unzippedDirectory = $unzippedDirectory; ExifToolPath = $ExifToolPath }; Enabled = $false },
    @{ Name = "File Count After Categorization"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @((Join-Path $scriptDirectory 'Logs' "FileReport_13.txt"), $unzippedDirectory); Enabled = $false },
    @{ Name = "Estimate Location By Time"; Type = "PowerShell"; Path = "step14  - Estimate By Time\EstimateByTime.ps1"; Args = @{ unzippedDirectory = $unzippedDirectory; ExifToolPath = $ExifToolPath }; Enabled = $false },
    @{ Name = "Final File Count"; Type = "Python"; Path = "Step0 - Tools\counter\counter.py"; Args = @((Join-Path $scriptDirectory 'Logs' "FileReport_14.txt"), $unzippedDirectory); Enabled = $false }
)

try {
    # --- Main Pipeline Execution Loop ---
    foreach ($step in $pipelineSteps) {
        # Check if the step is explicitly disabled
        if ($step.ContainsKey('Enabled') -and -not $step.Enabled) {
            & $Log "INFO" "Skipping disabled step: $($step.Name)"
            continue
        }

        # --- Extract step number from the relative path ---
        if ($step.Path -match 'step(\d+)\s*-') {
            $stepNumber = $matches[1]
        } elseif ($step.Path -match 'Step(\d+)\s*-') {
            $stepNumber = $matches[1]
        } else {
            $stepNumber = "NA"
        }

        & $Log "INFO" "Executing Step: $($step.Name)"
        $fullPath = Join-Path -Path $scriptDirectory -ChildPath $step.Path

        if ($step.Type -eq "PowerShell") {
            # For PowerShell, add the step number to the arguments hashtable
            $step.Args.step = $stepNumber.ToString()
            $psArgs = $step.Args # Assign to a temporary variable for splatting
            & $fullPath @psArgs
            
        } elseif ($step.Type -eq "Python") {
            $env:CURRENT_STEP = $stepNumber.ToString()
            Invoke-PythonScript -ScriptPath $fullPath -Arguments $step.Args -ActivityName $step.Name
        }
    }
} finally {
    # This block ensures the progress bar is closed even if an error occurs in the pipeline.
    & $Log "INFO" "Pipeline finished or stopped. Closing progress bar."
    Stop-GraphicalProgressBar
}

& $Log "INFO" "Media Organizer pipeline completed."
