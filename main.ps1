param(
    [Parameter(Mandatory=$true)]
    [string]$Config
)

Clear-Host

# --- Path Setup ---
$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

# --- Load Configuration FIRST, before any modules ---
$configPath = Join-Path $scriptDirectory $Config
Write-Host "DEBUG: Script directory: $scriptDirectory"
Write-Host "DEBUG: Config parameter: $Config"
Write-Host "DEBUG: Config path: $configPath"
Write-Host "DEBUG: Config path exists: $(Test-Path $configPath)"
if (-not (Test-Path $configPath)) {
    Write-Error "FATAL: Configuration file not found at '$configPath'. Aborting."
    exit 1
}
# BYPASS CONFIG OBJECT - Direct variable assignment
Write-Host "DEBUG: Using direct variable assignment to bypass config object issues"

# Load the pipelineSteps from the JSON file for later use
try {
    $jsonContent = Get-Content $configPath -Raw | ConvertFrom-Json
    $pipelineSteps = $jsonContent.pipelineSteps
    Write-Host "DEBUG: Successfully loaded pipelineSteps from JSON"
} catch {
    Write-Host "DEBUG: Failed to load pipelineSteps, creating minimal config"
    # Create a minimal pipelineSteps array with just the Sanitize step enabled
    $pipelineSteps = @(
        @{ Name = "Sanitize Names"; Type = "PowerShell"; Path = "phase2 - SanitizeNames/SanitizeNames.ps1"; Interactive = $false; Enabled = $true }
    )
}

# Utils Directory - Load modules AFTER config is loaded
$UtilDirectory = Join-Path $scriptDirectory "Utils"
$UtilFile = Join-Path $UtilDirectory "Utils.psm1"
$MediaToolsFile = Join-Path $UtilDirectory 'MediaTools.psm1'
Import-Module $UtilFile -Force
Import-Module $MediaToolsFile -Force

# --- Direct variable assignment (bypassing config object) ---
$rawDirectory      = ConvertTo-StandardPath -Path "C:/Users/sawye/Downloads/test/input"
$processedDirectory = ConvertTo-StandardPath -Path "C:/Users/sawye/Downloads/test/Processed_ps"
$logDirectory      = ConvertTo-StandardPath -Path "C:/Users/sawye/Codes/media_organizer/Logs_ps"
$outputDirectory   = ConvertTo-StandardPath -Path "C:/Users/sawye/Codes/media_organizer/Results_ps"
$sevenZip          = ConvertTo-StandardPath -Path "C:/Program Files/7-Zip/7z.exe"
$exifTool          = ConvertTo-StandardPath -Path "C:/tools/exiftool.exe"
$imageMagick       = ConvertTo-StandardPath -Path "C:/Program Files/ImageMagick-7.1.2-Q16-HDRI/magick.exe"
$pythonExe         = ConvertTo-StandardPath -Path "C:/Users/sawye/AppData/Local/Microsoft/WindowsApps/python.exe"
$ffmpeg            = ConvertTo-StandardPath -Path "C:/tools/ffmpeg.exe"
$ffprobe           = ConvertTo-StandardPath -Path "C:/tools/ffprobe.exe"
$vlc               = ConvertTo-StandardPath -Path "C:/Program Files/VideoLAN/VLC/vlc.exe"

Write-Host "DEBUG: Direct paths assigned successfully"
Write-Host "DEBUG: rawDirectory = $rawDirectory"
Write-Host "DEBUG: processedDirectory = $processedDirectory"

# Create a hashtable of variables that can be substituted in step arguments.
# The keys must match the variable tokens used in config.json (e.g., '$unzippedDirectory').
# This makes the substitution process explicit and resolves PSScriptAnalyzer warnings.
$substitutableVars = @{
    '$rawDirectory'      = $rawDirectory
    '$processedDirectory' = $processedDirectory
    '$logDirectory'      = $logDirectory
    '$outputDirectory'   = $outputDirectory
    '$sevenZip'          = $sevenZip
    '$exifTool'          = $exifTool
    '$imageMagick'       = $imageMagick
    '$ffmpeg'            = $ffmpeg
    '$ffprobe'           = $ffprobe
    '$vlc'               = $vlc
}

$env:FFPROBE_PATH                   = $ffprobe
$env:MAGICK_PATH                    = $imageMagick
$env:FFMPEG_PATH                    = $ffmpeg
$env:EXIFTOOL_PATH                  = $exifTool
$env:DEFAULT_PREFIX_LENGTH          = 15
$env:DEDUPLICATOR_CONSOLE_LOG_LEVEL = "INFO"
$env:DEDUPLICATOR_FILE_LOG_LEVEL    = "DEBUG"
$env:PYTHON_DEBUG_MODE              = "1"

$phase = 0
$logLevelMap = @{
    "DEBUG"    = 0
    "INFO"     = 1
    "WARNING"  = 2
    "ERROR"    = 3
    "CRITICAL" = 4
}
$env:LOG_LEVEL_MAP_JSON = $logLevelMap | ConvertTo-Json -Compress

Write-Host "DEBUG: Environment variables set:"
Write-Host "DEBUG: DEDUPLICATOR_CONSOLE_LOG_LEVEL = $env:DEDUPLICATOR_CONSOLE_LOG_LEVEL"
Write-Host "DEBUG: DEDUPLICATOR_FILE_LOG_LEVEL = $env:DEDUPLICATOR_FILE_LOG_LEVEL"
Write-Host "DEBUG: LOG_LEVEL_MAP_JSON = $env:LOG_LEVEL_MAP_JSON"

# --- Simplified Logging Setup ---
# Bypass complex logger since there are issues with it
$Log = {
    param([string]$Level, [string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "$timestamp - $Level : $Message"
    
    # Also write to log file
    $logFile = Join-Path $logDirectory "main.log"
    if (-not (Test-Path $logDirectory)) { New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null }
    "$timestamp - $Level : $Message" | Add-Content -Path $logFile -Encoding UTF8 -ErrorAction SilentlyContinue
}

Write-Host "DEBUG: Simple logger created successfully"

# Ensure log/output directories exist before starting
if (-not (Test-Path $outputDirectory)) { New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null }
if (-not (Test-Path $logDirectory)) { New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null }

& $Log "INFO" "--- Main Pipeline Started ---"

# --- Tool Validation ---
$requiredTools = @(
    @{ Name = "7-Zip"; Path = $sevenZip; PathType = 'Leaf' },
    @{ Name = "ExifTool"; Path = $exifTool; PathType = 'Leaf' },
    @{ Name = "ImageMagick"; Path = $imageMagick; PathType = 'Leaf' },
    @{ Name = "FFmpeg"; Path = $ffmpeg; PathType = 'Leaf' },
    @{ Name = "FFprobe"; Path = $ffprobe; PathType = 'Leaf' },
    @{ Name = "VLC"; Path = $vlc; PathType = 'Leaf' },
    @{ Name = "Python"; Path = $pythonExe; PathType = 'Leaf' }
)

foreach ($tool in $requiredTools) {
    if (-not (Test-Path -Path $tool.Path -PathType $tool.PathType)) {
        & $Log "CRITICAL" "Required tool '$($tool.Name)' not found at '$($tool.Path)'. Aborting."
        Stop-GraphicalProgressBar
        exit 1
    }
}

# --- Python script invocation with progress callback support ---
function Invoke-PythonScript {
    param(
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [Parameter(Mandatory = $true)][string]$ActivityName,
        [Parameter(Mandatory = $true)]$Config,
        [ScriptBlock]$ProgressCallback,
        [Parameter(Mandatory = $true)]$Log
    )

    $outputEvent = $null
    $errorEvent = $null
    try {
        $processInfo = New-Object System.Diagnostics.ProcessStartInfo
        $processInfo.FileName = $pythonExe

        # Convert config to proper JSON (compressed to avoid command line issues)
        $configJson = $Config | ConvertTo-Json -Depth 10 -Compress
        $tempConfigFile = [System.IO.Path]::GetTempFileName()
        [System.IO.File]::WriteAllText($tempConfigFile, $configJson, [System.Text.Encoding]::UTF8)
        
        # Escape the JSON properly for command line
        $escapedJson = (Get-Content $tempConfigFile -Raw).Replace('"', '\"')
        
        $pythonArgs = [System.Collections.Generic.List[string]]::new()
        $pythonArgs += "`"$ScriptPath`""
        $pythonArgs += "--config-json"
        $pythonArgs += "`"$escapedJson`""
        $processInfo.Arguments = $pythonArgs -join ' '

        $processInfo.RedirectStandardOutput = $true
        $processInfo.RedirectStandardError = $true
        $processInfo.UseShellExecute = $false
        $processInfo.CreateNoWindow = $true
        $processInfo.StandardOutputEncoding = [System.Text.Encoding]::UTF8
        $processInfo.StandardErrorEncoding = [System.Text.Encoding]::UTF8

        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $processInfo
        $stdErrLines = [System.Collections.ArrayList]::Synchronized((New-Object System.Collections.ArrayList))

        $outputEvent = Register-ObjectEvent -InputObject $process -EventName 'OutputDataReceived' -MessageData @($ProgressCallback, $Log) -Action {
            $callback = $event.MessageData[0]
            $logFn    = $event.MessageData[1]

            try {
                $line = $EventArgs.Data
                if ($null -ne $line) {
                    if ($line -match '^PROGRESS:(\d{1,3})\|(.*)$') {
                        $percent = [int]$matches[1]
                        $status = $matches[2].Trim()
                        if ($callback -is [ScriptBlock]) {
                            & $callback $percent $status
                        }
                    }
                    elseif ($line -match '^(\d+)\s+(\d+)\s+(.+)$') {
                        $current = [int]$matches[1]
                        $total = [int]$matches[2]
                        $status = $matches[3].Trim()
                        $percent = [int](($current / [math]::Max($total,1)) * 100)
                        if ($callback -is [ScriptBlock]) {
                            & $callback $percent $status
                        }
                    }
                    else {
                        & $logFn "DEBUG" "PY_STDOUT: $line"
                    }
                }
            } catch {
                & $logFn "ERROR" "Exception in OutputDataReceived: $_"
            }
        }

        $errorEvent = Register-ObjectEvent -InputObject $process -EventName 'ErrorDataReceived' -MessageData $Log -Action {
            $logFn = $event.MessageData
            try {
                $line = $EventArgs.Data
                if ($null -ne $line) {
                    & $logFn "ERROR" "PY_STDERR: $line"
                }
            } catch {
                & $logFn "ERROR" "Exception in ErrorDataReceived: $_"
            }
        }

        & $Log "DEBUG" "Executing: $pythonExe $($processInfo.Arguments)"

        [void]$process.Start()
        $process.BeginOutputReadLine()
        $process.BeginErrorReadLine()
        $process.WaitForExit()

        if ($outputEvent) { Unregister-Event -SourceIdentifier $outputEvent.Name; $outputEvent = $null }
        if ($errorEvent)  { Unregister-Event -SourceIdentifier $errorEvent.Name;  $errorEvent  = $null }

        if ($process.ExitCode -ne 0) {
            $errorOutput = $stdErrLines -join "`n"
            throw "Python script '$ScriptPath' failed with exit code $($process.ExitCode). Output:`n$errorOutput"
        }
        
        # Clean up temp file
        if ($tempConfigFile -and (Test-Path $tempConfigFile)) {
            Remove-Item $tempConfigFile -Force
        }
    }
    catch {
        & $Log "ERROR" "Error running Python script '$ScriptPath'. Error: $_"
        exit 1
    }
    finally {
        if ($outputEvent) { Unregister-Event -SourceIdentifier $outputEvent.Name }
        if ($errorEvent)  { Unregister-Event -SourceIdentifier $errorEvent.Name }
    }
}

# $pipelineSteps already loaded from JSON above
$enabledSteps = $pipelineSteps | Where-Object { $_.Enabled -eq $true }
$totalSteps = $enabledSteps.Count
$currentStepIndex = 0

Write-Host "DEBUG: Total pipeline steps: $($pipelineSteps.Count)"
Write-Host "DEBUG: Enabled steps: $totalSteps"
foreach ($step in $enabledSteps) {
    Write-Host "DEBUG: Enabled step: $($step.Name) ($($step.Type))"
}

# --- Define a progress callback for Python scripts ---
$progressCallback = {
    param($percent, $status)
    Update-GraphicalProgressBar -SubTaskPercent $percent -SubTaskMessage $status
}

# --- Show two-level progress bar GUI ---
Show-GraphicalProgressBar -EnableSecondLevel

try {
    foreach ($step in $pipelineSteps) {
        $currentStepIndex++
        if (-not $step.Enabled) {
            & $Log "INFO" "Skipping disabled phase: $($step.Name)"
            continue
        }

        $percentComplete = if ($totalSteps -gt 0) { [int](($currentStepIndex / $totalSteps) * 100) } else { 0 }
        Update-GraphicalProgressBar -OverallPercent $percentComplete -Activity "Phase $currentStepIndex : $($step.Name) " -SubTaskPercent 0 -SubTaskMessage "Starting..."

        # Conditionally hide the progress bar for interactive steps
        if ($step.Interactive) {
            Send-ProgressBarToBack
        }

        & $Log "INFO" "Starting Phase $currentStepIndex/$totalSteps : $($step.Name)"

        # --- Resolve Arguments ---
        # This block substitutes variables like '$unzippedDirectory' in the config with their actual values.
        $resolvedArgs = $null
        if ($step.Args) {
            if ($step.Type -eq 'PowerShell') {
                $resolvedArgs = @{}
                foreach ($key in $step.Args.psobject.Properties.Name) {
                    $value = $step.Args.$key
                    foreach ($var in $substitutableVars.GetEnumerator()) {
                        $value = $value -replace [regex]::Escape($var.Name), $var.Value
                    }
                    $resolvedArgs[$key] = $value
                }
            } else { # Python
                $resolvedArgs = @()
                foreach ($arg in $step.Args) {
                    $value = $arg
                    foreach ($var in $substitutableVars.GetEnumerator()) {
                        $value = $value -replace [regex]::Escape($var.Name), $var.Value
                    }
                    $resolvedArgs += $value
                }
            }
        }

        if ($step.Type -eq "PowerShell") {
            # Use the 0-based array index as the Step Number.
            $zeroBasedIndex = $currentStepIndex - 1
            $env:CURRENT_STEP = $zeroBasedIndex.ToString()

            $command = Join-Path $scriptDirectory $step.Path
            
            # Create a minimal config object just for PowerShell scripts
            $configForPS = [PSCustomObject]@{
                paths = [PSCustomObject]@{
                    rawDirectory = $rawDirectory
                    processedDirectory = $processedDirectory
                    logDirectory = $logDirectory
                    outputDirectory = $outputDirectory
                    tools = $jsonContent.paths.tools
                }
                settings = $jsonContent.settings
            }
            & "$command" -Config $configForPS
        }
        elseif ($step.Type -eq "Python") {
            # Use the 0-based array index as the Step Number.
            $zeroBasedIndex = $currentStepIndex - 1
            $env:CURRENT_STEP = $zeroBasedIndex.ToString()
            $configForPython = [PSCustomObject]@{
                paths = [PSCustomObject]@{
                    rawDirectory = $rawDirectory
                    processedDirectory = $processedDirectory
                    logDirectory = $logDirectory
                    outputDirectory = $outputDirectory
                }
                settings = [PSCustomObject]@{
                    enablePythonDebugging = $true
                    logging = [PSCustomObject]@{
                        defaultConsoleLevel = "INFO"
                        defaultFileLevel = "DEBUG"
                    }
                    progressBar = [PSCustomObject]@{
                        defaultPrefixLength = 15
                    }
                }
            }
            Invoke-PythonScript -ScriptPath (Join-Path $scriptDirectory $step.Path) `
                                -Config $configForPython `
                                -ActivityName $step.Name `
                                -ProgressCallback $progressCallback `
                                -Log $Log
        }

        # Conditionally show the progress bar again after the step is complete
        if ($step.Interactive) {
            Show-ProgressBarInFront
        }
    }
}
finally {
    & $Log "INFO" "Pipeline finished or stopped. Closing progress bar."
    Stop-GraphicalProgressBar
}

& $Log "INFO" "Media Organizer pipeline completed."
