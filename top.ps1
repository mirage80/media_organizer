Clear-Host

# --- Path Setup ---
$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

# Utils Directory
$UtilDirectory = Join-Path $scriptDirectory "Utils"
$UtilFile = Join-Path $UtilDirectory "Utils.psm1"
$MediaToolsFile = Join-Path $UtilDirectory 'MediaTools.psm1'
Import-Module $UtilFile -Force
Import-Module $MediaToolsFile -Force

# --- Load Configuration from JSON ---
$configPath = Join-Path $UtilDirectory "config.json"
if (-not (Test-Path $configPath)) {
    Write-Error "FATAL: Configuration file not found at '$configPath'. Aborting."
    exit 1
}
$config = Get-Content $configPath -Raw | ConvertFrom-Json

# --- Standardize Paths and Set Environment Variables from Config ---
$zipDirectory      = ConvertTo-StandardPath -Path $config.paths.zipDirectory
$unzippedDirectory = ConvertTo-StandardPath -Path $config.paths.unzippedDirectory
$logDirectory      = ConvertTo-StandardPath -Path $config.paths.logDirectory
$outputDirectory   = ConvertTo-StandardPath -Path $config.paths.outputDirectory
$sevenZip          = ConvertTo-StandardPath -Path $config.paths.tools.sevenZip
$exifTool          = ConvertTo-StandardPath -Path $config.paths.tools.exifTool
$imageMagick       = ConvertTo-StandardPath -Path $config.paths.tools.imageMagick
$pythonExe         = ConvertTo-StandardPath -Path $config.paths.tools.python
$ffmpeg            = ConvertTo-StandardPath -Path $config.paths.tools.ffmpeg
$ffprobe           = ConvertTo-StandardPath -Path $config.paths.tools.ffprobe
$vlc               = ConvertTo-StandardPath -Path $config.paths.tools.vlc

# Create a hashtable of variables that can be substituted in step arguments.
# The keys must match the variable tokens used in config.json (e.g., '$unzippedDirectory').
# This makes the substitution process explicit and resolves PSScriptAnalyzer warnings.
$substitutableVars = @{
    '$zipDirectory'      = $zipDirectory
    '$unzippedDirectory' = $unzippedDirectory
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
$env:DEFAULT_PREFIX_LENGTH          = $config.settings.progressBar.defaultPrefixLength
$env:DEDUPLICATOR_CONSOLE_LOG_LEVEL = $config.settings.logging.defaultConsoleLevel
$env:DEDUPLICATOR_FILE_LOG_LEVEL    = $config.settings.logging.defaultFileLevel
$env:PYTHON_DEBUG_MODE              = if ($config.settings.enablePythonDebugging) { "1" } else { "0" }

$step = 0
$logLevelMap = @{
    "DEBUG"    = 0
    "INFO"     = 1
    "WARNING"  = 2
    "ERROR"    = 3
    "CRITICAL" = 4
}
$env:LOG_LEVEL_MAP_JSON = $logLevelMap | ConvertTo-Json -Compress

# --- Logging Setup ---
$Logger = Initialize-ScriptLogger -LogDirectory $logDirectory -ScriptName $scriptName -Step $step
$Log = $Logger.Logger

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
        [string[]]$Arguments,
        [ScriptBlock]$ProgressCallback,
        [Parameter(Mandatory = $true)]$Log
    )

    $outputEvent = $null
    $errorEvent = $null
    try {
        $processInfo = New-Object System.Diagnostics.ProcessStartInfo
        $processInfo.FileName = $pythonExe

        $pythonArgs = [System.Collections.Generic.List[string]]::new()
        $pythonArgs += "`"$ScriptPath`""
        $pythonArgs += [string[]]$Arguments
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

        $argStringForLog = $Arguments | ForEach-Object { """$_""" } | Join-String -Separator ' '
        & $Log "DEBUG" "Executing: $pythonExe `"$ScriptPath`" $argStringForLog"

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

$pipelineSteps = $config.pipelineSteps
$totalSteps = ($pipelineSteps | Where-Object { $_.Enabled }).Count
$currentStepIndex = 0

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
            & $Log "INFO" "Skipping disabled step: $($step.Name)"
            continue
        }

        $percentComplete = [int](($currentStepIndex / $totalSteps) * 100)
        Update-GraphicalProgressBar -OverallPercent $percentComplete -Activity "Step $currentStepIndex : $($step.Name) " -SubTaskPercent 0 -SubTaskMessage "Starting..."

        # Conditionally hide the progress bar for interactive steps
        if ($step.Interactive) {
            Send-ProgressBarToBack
        }

        & $Log "INFO" "Starting Step $currentStepIndex/$totalSteps : $($step.Name)"

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
            $resolvedArgs.step = $currentStepIndex.ToString()
            $command = Join-Path $scriptDirectory $step.Path
            & "$command" @resolvedArgs
        }
        elseif ($step.Type -eq "Python") {
            $env:CURRENT_STEP = $currentStepIndex.ToString()
            Invoke-PythonScript -ScriptPath (Join-Path $scriptDirectory $step.Path) `
                                -Arguments $resolvedArgs `
                                -ActivityName $step.Name `
                                -ProgressCallback $progressCallback `
                                -Log $Log
        }

        # Conditionally show the progress bar again after the step is complete
        if ($step.Interactive) {
            Bring-ProgressBarToFront
        }
    }
}
finally {
    & $Log "INFO" "Pipeline finished or stopped. Closing progress bar."
    Stop-GraphicalProgressBar
}

& $Log "INFO" "Media Organizer pipeline completed."
