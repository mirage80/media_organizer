# --- Module-level Logger ---
# This variable will hold the logger script block passed in from a calling script.
$script:UtilsLogger = $null

# --- Thread-safe logging lock ---
$script:LogFileLock = [System.Object]::new()

function Set-UtilsLogger {
    param(
        [Parameter(Mandatory=$true)]$Logger
    )
    $script:UtilsLogger = $Logger
}

function ConvertTo-StandardPath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$Path
    )
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $Path
    }
    # Replace all backslashes with forward slashes for consistency.
    return $Path -replace '\\', '/'
}

# --- Standalone, Stateless Logging Function ---
# It is completely stateless and requires all configuration on every call.
function Write-Log {
    param(
        [Parameter(Mandatory=$true)][string]$Level,
        [Parameter(Mandatory=$true)][string]$Message,
        [Parameter(Mandatory=$true)][string]$LogFilePath,
        [Parameter(Mandatory=$true)][int]$ConsoleLogLevel,
        [Parameter(Mandatory=$true)][int]$FileLogLevel,
        [Parameter(Mandatory=$true)][hashtable]$LogLevelMap,
        [object]$LockObject = $null
    )

    $normalizedLogPath = ConvertTo-StandardPath -Path $LogFilePath
    # Ensure log directory exists. This check is fast and safe to run on every call.
    $logDir = Split-Path -Path $normalizedLogPath -Parent
    if (-not (Test-Path $logDir)) {
        try {
            New-Item -ItemType Directory -Path $logDir -Force -ErrorAction Stop | Out-Null
        } catch {
            Write-Warning "FATAL: Could not create log directory '$logDir'. Error: $_"
            return # Stop further processing if directory can't be made
        }
    }

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $formatted = "$timestamp - $($Level.ToUpper()): $Message"
    $levelIndex = $LogLevelMap[$Level.ToUpper()]

    if ($null -ne $levelIndex) {
        if ($levelIndex -ge $ConsoleLogLevel) { Write-Host $formatted }
        if ($levelIndex -ge $FileLogLevel) {
            $effectiveLock = if ($null -ne $LockObject) { $LockObject } else { $script:LogFileLock }
            $lockTaken     = $false
            try {
                [System.Threading.Monitor]::Enter($effectiveLock, [ref]$lockTaken)
                if ($lockTaken) {
                    Add-Content -Path $normalizedLogPath -Value $formatted -Encoding UTF8 -ErrorAction Stop
                }
            }
            catch { Write-Warning "Failed to write to log file '$normalizedLogPath': $_" }
            finally {
                if ($lockTaken) { [System.Threading.Monitor]::Exit($effectiveLock) }
            }
        }
    } else { Write-Warning "Invalid log level used: $Level" }
}

# --- Graphical ProgressBar Function Definition ---
function Show-ProgressBar {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Current,
        [Parameter(Mandatory = $true)]
        [int]$Total,
        [string]$Message
    )

    try {
        # Ensure Forms assembly is loaded
        # Check if it's already loaded to avoid errors on subsequent calls
        if (-not ([System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms"))) {
            Add-Type -AssemblyName System.Windows.Forms
            # Add-Type throws an error if it fails, which will be caught below
        }

        # Initialize form on first call or if it was closed/disposed
        if ($null -eq $global:GProgressForm -or $global:GProgressForm.IsDisposed) {
            $global:GProgressForm = New-Object System.Windows.Forms.Form
            # Properties set here are for initial creation
            $global:GProgressForm.Size = New-Object System.Drawing.Size(430, 45) # Made window shorter
            $global:GProgressForm.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
            $global:GProgressForm.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog # Prevent resizing
            $global:GProgressForm.ControlBox = $false # Hide minimize/maximize/close buttons
            $global:GProgressForm.TopMost = $true # Keep it on top
            # Key line — use system default colors
            $global:GProgressForm.BackColor = [System.Drawing.SystemColors]::Control # Use standard dialog background color
            $global:GProgressForm.ForeColor = [System.Drawing.SystemColors]::ControlText # Use system text color
            $global:GProgressForm.Font      = [System.Drawing.SystemFonts]::DefaultFont # Corrected typo: DefaultFont

            # Progress Bar setup - Use $global scope consistently
            $global:GProgressBar = New-Object System.Windows.Forms.ProgressBar
            # Use the previously determined good position/size
            $global:GProgressBar.Location = New-Object System.Drawing.Point(10, 5)
            $global:GProgressBar.Size = New-Object System.Drawing.Size(400, 20)
            $global:GProgressBar.Minimum = 0
            $global:GProgressBar.Style = [System.Windows.Forms.ProgressBarStyle]::Continuous # Ensure solid bar
            $global:GProgressBar.ForeColor = [System.Drawing.Color]::LimeGreen  # Set the bar color
            $global:GProgressForm.Controls.Add($global:GProgressBar) # Add the GLOBAL progress bar to the GLOBAL form

            # Show the form non-modally
            $global:GProgressForm.Show()
        } # End of form creation block

        # Flag to track if an update actually happened
        $updateNeeded = $false

        # --- Update form properties regardless of creation or reuse ---
        # Update Title
        if ($global:GProgressForm.Text -ne $Message) { # Check if title needs changing
            $global:GProgressForm.Text = $Message
            $updateNeeded = $true # Mark that an update happened
        }

        # Ensure values are within bounds before updating
        $global:GProgressBar.Maximum = [math]::Max(1, $Total) # Update max in case Total changes (though unlikely)
        $clampedValue = [math]::Min([math]::Max(0, $Current), $global:GProgressBar.Maximum) # Clamp current value

        # Check if progress bar value needs changing
        if ($global:GProgressBar.Value -ne $clampedValue) {
            $global:GProgressBar.Value = $clampedValue
            $updateNeeded = $true # Mark that an update happened
        }

        # Only force UI update if something actually changed
        if ($updateNeeded) {
            $global:GProgressForm.Refresh()
            [System.Windows.Forms.Application]::DoEvents() # Allow UI events to process
        }

        # --- REMOVED: Automatic closing when $Current >= $Total ---

    } catch {
        # Fallback to console output if GUI fails
        Write-Warning "Graphical progress bar failed: $($_.Exception.Message). Falling back to console."
        # Original console progress logic (simplified)
        $percent = 0; if ($Total -gt 0) { $percent = [math]::Round(($Current / $Total) * 100) }
        # Use original message, no padding needed/available easily here
        Write-Host "$Message Progress: $percent% ($Current/$Total)"
    }
}

function Show-GraphicalProgressBar {
    param(
        [string]$Title = "Progress",
        [switch]$EnableSecondLevel
    )

    # If form already exists, just bring to front
    if ($global:ProgressForm -and -not $global:ProgressForm.IsDisposed) {
        $global:ProgressForm.Show()
        return
    }

    Add-Type -AssemblyName System.Windows.Forms

    $form = New-Object System.Windows.Forms.Form
    $form.Text = $Title
    $form.Width = 500
    $form.Height = if ($EnableSecondLevel) { 180 } else { 120 }
    $form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.StartPosition = 'CenterScreen'
    $form.TopMost = $true

    # Overall progress bar and label
    $overallBar = New-Object System.Windows.Forms.ProgressBar
    $overallBar.Width = 460
    $overallBar.Height = 25
    $overallBar.Top = 20
    $overallBar.Left = 15
    $overallBar.Style = 'Continuous'
    $overallBar.Maximum = 100
    $overallBar.Value = 0

    $stepLabel = New-Object System.Windows.Forms.Label
    $stepLabel.Width = 460
    $stepLabel.Height = 20
    $stepLabel.Top = 55
    $stepLabel.Left = 15
    $stepLabel.Text = "Step: Not started"

    $form.Controls.AddRange(@($overallBar, $stepLabel))

    # Optional second-level progress bar and label
    if ($EnableSecondLevel) {
        $stepBar = New-Object System.Windows.Forms.ProgressBar
        $stepBar.Width = 460
        $stepBar.Height = 25
        $stepBar.Top = 80
        $stepBar.Left = 15
        $stepBar.Style = 'Continuous'
        $stepBar.Maximum = 100
        $stepBar.Value = 0

        $subTaskLabel = New-Object System.Windows.Forms.Label
        $subTaskLabel.Width = 460
        $subTaskLabel.Height = 20
        $subTaskLabel.Top = 115
        $subTaskLabel.Left = 15
        $subTaskLabel.Text = "Subtask: Not started"

        $form.Controls.AddRange(@($stepBar, $subTaskLabel))

        # Store second-level controls in global vars
        $global:StepProgressBar = $stepBar
        $global:SubTaskLabel = $subTaskLabel
    }
    else {
        $global:StepProgressBar = $null
        $global:SubTaskLabel = $null
    }

    # Store first-level controls
    $global:ProgressForm = $form
    $global:OverallProgressBar = $overallBar
    $global:StepLabel = $stepLabel

    $form.Show()
    [System.Windows.Forms.Application]::DoEvents()
}

function Write-JsonAtomic {
    param (
        [Parameter(Mandatory = $true)][object]$Data,
        [Parameter(Mandatory = $true)][string]$Path
    )

    if ($null -eq $Data) {
        throw "Data parameter cannot be null."
    }

    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "Path parameter cannot be null or empty."
    }

    $normalizedPath = ConvertTo-StandardPath -Path $Path
    try {
        $tempPath = "$normalizedPath.tmp"
        $json = $Data | ConvertTo-Json -Depth 10
        $json | Out-File -FilePath $tempPath -Encoding UTF8 -Force

        # Validate JSON before replacing
        Get-Content $tempPath -Raw | ConvertFrom-Json | Out-Null

        Move-Item -Path $tempPath -Destination $normalizedPath -Force
        & $script:UtilsLogger "INFO" "✅ Atomic write succeeded: $normalizedPath"
    } catch {
        & $script:UtilsLogger "ERROR" "❌ Atomic write failed for $normalizedPath : $_"
        if (Test-Path $tempPath) {
            Remove-Item $tempPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Update-GraphicalProgressBar {
    param(
        # Use -1 as a sentinel to indicate "do not update"
        [int]$OverallPercent = -1,
        [string]$Activity,
        [int]$SubTaskPercent = -1,
        [string]$SubTaskMessage = $null
    )

    if ($null -eq $global:ProgressForm) {
        # If called without being initialized, create it. Enable second level if subtask info is present.
        Show-GraphicalProgressBar -EnableSecondLevel:($SubTaskPercent -ge 0 -or $null -ne $SubTaskMessage)
    }

    if ($null -ne $global:ProgressForm -and -not $global:ProgressForm.IsDisposed) {
        if ($OverallPercent -ge 0) {
            $global:OverallProgressBar.Value = [Math]::Min($OverallPercent, 100)
        }
        # Only update the Activity label if the -Activity parameter was explicitly passed in the call.
        # This prevents the label from being cleared when other parameters (like for the sub-task) are updated.
        if ($PSBoundParameters.ContainsKey('Activity')) {
            $global:StepLabel.Text = $Activity
        }

        if ($null -ne $global:StepProgressBar) {
            if ($SubTaskPercent -ge 0) {
                $global:StepProgressBar.Value = [Math]::Min($SubTaskPercent, 100)
            }
            if ($null -ne $SubTaskMessage) {
                $global:SubTaskLabel.Text = $SubTaskMessage
            }
        }

        [System.Windows.Forms.Application]::DoEvents()
    }
}

function Stop-GraphicalProgressBar {
    if ($null -ne $global:ProgressForm -and -not $global:ProgressForm.IsDisposed) {
        $global:ProgressForm.Close()
        $global:ProgressForm.Dispose()
    }

    # Clear all global variables related to progress bars and labels
    $global:ProgressForm = $null
    $global:OverallProgressBar = $null
    $global:StepLabel = $null
    $global:StepProgressBar = $null
    $global:SubTaskLabel = $null
}

function Initialize-ScriptLogger {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$LogDirectory,
        [Parameter(Mandatory=$true)]
        [string]$ScriptName,
        [Parameter(Mandatory=$true)]
        [string]$Step
    )

    # 1. Define the log file path using the absolute log directory provided.
    $logDir = ConvertTo-StandardPath -Path $LogDirectory
    $logFileName = "Step_{0}_{1}.log" -f $Step, $ScriptName
    $childLogFilePath = Join-Path $logDir -ChildPath $logFileName

    # 2. Get logging configuration from environment variables
    try {
        $logLevelMap = $env:LOG_LEVEL_MAP_JSON | ConvertFrom-Json -AsHashtable
        $consoleLogLevel = $logLevelMap[$env:DEDUPLICATOR_CONSOLE_LOG_LEVEL.ToUpper()]
        $fileLogLevel    = $logLevelMap[$env:DEDUPLICATOR_FILE_LOG_LEVEL.ToUpper()]
    } catch {
        Write-Error "Failed to initialize logger: Could not parse logging environment variables. Ensure top.ps1 has run."
        # Return a no-op logger to prevent crashes in case of misconfiguration
        return { param([string]$Level, [string]$Message) }
    }

    # 3. Ensure the log directory exists
    if (-not (Test-Path -Path $logDir)) {
        try {
            New-Item -ItemType Directory -Path $logDir -Force -ErrorAction Stop | Out-Null
        } catch {
            Write-Error "Failed to create log directory '$logDir'. Error: $_"
            return { param([string]$Level, [string]$Message) } # Return a no-op logger
        }
    }

    # 4. Delete the log file if it already exists
    if (Test-Path -Path $childLogFilePath) {
        try {
            Remove-Item -Path $childLogFilePath -Force -ErrorAction Stop
        } catch {
            Write-Error "Failed to delete existing log file '$childLogFilePath'. Error: $_"
            return { param([string]$Level, [string]$Message) } # Return a no-op logger
        }
    }   
    # 5. Create an empty log file to start fresh
    try { 
        New-Item -ItemType File -Path $childLogFilePath -Force -ErrorAction Stop | Out-Null
    } catch {
        Write-Error "Failed to create log file '$childLogFilePath'. Error: $_"
        return { param([string]$Level, [string]$Message) } # Return a no-op logger
    }

    # 6. Create and return a pre-configured logger script block for the calling script
    $scriptBlock = {
        param([string]$Level, [string]$Message)
        # These variables are captured from the parent scope by GetNewClosure()
        Write-Log -Level $Level -Message $Message -LogFilePath $childLogFilePath -ConsoleLogLevel $consoleLogLevel -FileLogLevel $fileLogLevel -LogLevelMap $logLevelMap
    }
    return [PSCustomObject]@{
        Logger          = $scriptBlock.GetNewClosure()
        LogFilePath     = $childLogFilePath
    }

}

function Convert-HashtableToStringKey {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [hashtable]$InputHashtable
    )

    $newHashtable = [ordered]@{}
    foreach ($entry in $InputHashtable.GetEnumerator()) {
        $key = $entry.Key
        $stringKey = if ($key -is [string]) {
            $key
        } elseif ($key -is [System.IO.FileInfo]) {
            $key.FullName
        } else {
            $key.ToString()
        }
        
        $standardizedKey = ConvertTo-StandardPath -Path $stringKey
        $newHashtable[$standardizedKey] = $entry.Value
    }
    return $newHashtable
}

function Send-ProgressBarToBack {
    if ($global:ProgressForm -and -not $global:ProgressForm.IsDisposed) {
        $global:ProgressForm.TopMost = $false
    }
}

function Bring-ProgressBarToFront {
    if ($global:ProgressForm -and -not $global:ProgressForm.IsDisposed) {
        $global:ProgressForm.TopMost = $true
    }
}

# Export all public functions from this module.
Export-ModuleMember -Function Write-Log, Show-ProgressBar, Stop-GraphicalProgressBar, Show-GraphicalProgressBar, Update-GraphicalProgressBar, Write-JsonAtomic, Set-UtilsLogger, ConvertTo-StandardPath, Initialize-ScriptLogger, Convert-HashtableToStringKey, Send-ProgressBarToBack, Bring-ProgressBarToFront
