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

Export-ModuleMember -Function *  # Export ALL functions

