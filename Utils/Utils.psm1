# --- Logger Configuration (Script Scope) ---
# These variables are private to this module and are set by Initialize-Logger.
$script:S_LogFile = $null
$script:S_ConsoleLogLevel = 3 # Default to ERROR
$script:S_FileLogLevel = 1     # Default to INFO
$script:S_LogLevelMap = @{
    "DEBUG"    = 0
    "INFO"     = 1
    "WARNING"  = 2
    "ERROR"    = 3
    "CRITICAL" = 4
}

# --- Logger Initialization Function ---
function Initialize-Logger {
    param(
        [Parameter(Mandatory=$true)][string]$LogFilePath,
        [Parameter(Mandatory=$true)][int]$ConsoleLogLevel,
        [Parameter(Mandatory=$true)][int]$FileLogLevel,
        [hashtable]$LogLevelMap
    )
    $script:S_LogFile = $LogFilePath
    $script:S_ConsoleLogLevel = $ConsoleLogLevel
    $script:S_FileLogLevel = $FileLogLevel
    $script:S_LogLevelMap = $LogLevelMap # Overwrite the default map with the one from top.ps1
}

# --- Child Script Logger Initialization ---
function Initialize-ChildScriptLogger {
    param(
        [Parameter(Mandatory=$true)][string]$ChildLogFilePath
    )

    # This function encapsulates the boilerplate for initializing logging in a child script
    # It relies on environment variables set by the main 'top.ps1' script.
    $logDir = Split-Path -Path $ChildLogFilePath -Parent
    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force -ErrorAction Stop | Out-Null
    }

    # Deserialize the JSON back into a hashtable
    $logLevelMap = $null
    if (-not [string]::IsNullOrWhiteSpace($env:LOG_LEVEL_MAP_JSON)) {
        try {
            $logLevelMap = $env:LOG_LEVEL_MAP_JSON | ConvertFrom-Json -AsHashtable
        } catch {
            throw "FATAL: Failed to deserialize LOG_LEVEL_MAP_JSON. Error: $_"
        }
    }

    if ($null -eq $logLevelMap) { throw "FATAL: LOG_LEVEL_MAP_JSON environment variable not found or invalid." }
    if ($null -eq $env:DEDUPLICATOR_CONSOLE_LOG_LEVEL) { throw "FATAL: Environment variable DEDUPLICATOR_CONSOLE_LOG_LEVEL is not set." }
    if ($null -eq $env:DEDUPLICATOR_FILE_LOG_LEVEL) { throw "FATAL: Environment variable DEDUPLICATOR_FILE_LOG_LEVEL is not set." }

    $EffectiveConsoleLogLevelString = $env:DEDUPLICATOR_CONSOLE_LOG_LEVEL.Trim()
    $EffectiveFileLogLevelString    = $env:DEDUPLICATOR_FILE_LOG_LEVEL.Trim()

    $consoleLogLevel = $logLevelMap[$EffectiveConsoleLogLevelString.ToUpper()]
    $fileLogLevel    = $logLevelMap[$EffectiveFileLogLevelString.ToUpper()]

    if ($null -eq $consoleLogLevel) { throw "FATAL: Invalid Console Log Level specified ('$EffectiveConsoleLogLevelString')." }
    if ($null -eq $fileLogLevel) { throw "FATAL: Invalid File Log Level specified ('$EffectiveFileLogLevelString')." }

    # Call the main initializer with the derived settings
    Initialize-Logger -LogFilePath $ChildLogFilePath -ConsoleLogLevel $consoleLogLevel -FileLogLevel $fileLogLevel -LogLevelMap $logLevelMap
}

# --- Graphical Show-ProgressBar Function Definition ---
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

# Function to explicitly close the progress bar window
function Stop-GraphicalProgressBar {
    try {
        if ($null -ne $global:GProgressForm -and -not $global:GProgressForm.IsDisposed) {
            $global:GProgressForm.Close()
            $global:GProgressForm.Dispose() # Release resources
        }
    } catch {
        Write-Warning "Failed to close graphical progress bar: $($_.Exception.Message)"
    } finally {
        # Ensure variables are cleared even if closing fails
        Remove-Variable -Name GProgressForm, GProgressBar -Scope Global -ErrorAction SilentlyContinue
    }
}


# --- End Show-ProgressBar Function Definition ---
function Write-JsonAtomic {
    param (
        [Parameter(Mandatory = $true)][object]$Data,
        [Parameter(Mandatory = $true)][string]$Path
    )

    try {
        $tempPath = "$Path.tmp"
        $json = $Data | ConvertTo-Json -Depth 10
        $json | Out-File -FilePath $tempPath -Encoding UTF8 -Force

        # Validate JSON before replacing
        $null = Get-Content $tempPath -Raw | ConvertFrom-Json

        Move-Item -Path $tempPath -Destination $Path -Force
        Log "INFO" "✅ Atomic write succeeded: $Path"
    } catch {
        Log "ERROR" "❌ Atomic write failed for $Path : $_"
        if (Test-Path $tempPath) {
            Remove-Item $tempPath -Force -ErrorAction SilentlyContinue
        }
    }
}

# --- Log Function Definition ---
function Log {
    param (
        [string]$Level,
        [string]$Message
    )
    # This function now uses the script-scoped variables set by Initialize-Logger
    if ($null -eq $script:S_LogFile) {
        Write-Warning "Logger has not been initialized. Call Initialize-Logger first. Message: [$Level] $Message"
        return
    }

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $formatted = "$timestamp - $($Level.ToUpper()): $Message"
    $levelIndex = $script:S_LogLevelMap[$Level.ToUpper()]

    if ($null -ne $levelIndex) {
        if ($levelIndex -ge $script:S_ConsoleLogLevel) {
            Write-Host $formatted
        }
        if ($levelIndex -ge $script:S_FileLogLevel) {
            try {
                Add-Content -Path $script:S_LogFile -Value $formatted -Encoding UTF8 -ErrorAction Stop
            } catch {
                Write-Warning "Failed to write to log file '$($script:S_LogFile)': $_"
            }
        }
    } else {
        Write-Warning "Invalid log level used: $Level"
    }
}
 
# Export all public functions from this module.
Export-ModuleMember -Function Initialize-Logger, Initialize-ChildScriptLogger, Log, Show-ProgressBar, Stop-GraphicalProgressBar, Write-JsonAtomic
