# --- Show-ProgressBar Function Definition ---
function Show-ProgressBar {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Current,

        [Parameter(Mandatory = $true)]
        [int]$Total,

        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    # Pad or truncate the message to exactly 10 characters
    $paddedMessage = $Message.PadRight($env:DEFAULT_PREFIX_LENGTH).Substring(0, $env:DEFAULT_PREFIX_LENGTH)

    # Check if running in a host that supports progress bars
    if ($null -eq $Host.UI.RawUI) {
        # Fallback for non-interactive environments or simplified hosts
        $percent = 0;
        if ($Total -gt 0) {
            $percent = [math]::Round(($Current / $Total) * 100)
        }
        # Use the padded message here
        Write-Host "$paddedMessage Progress: $percent% ($Current/$Total)"
        return
    }
    try {
        # Explicitly cast the environment variable string to an integer
        # Ensure PROGRESS_BAR_LENGTH has a default value if the env var is not set or invalid
        if ($env:PROGRESS_BAR_LENGTH -match '^\d+$') { # Check if it's a valid integer string
            $barLength = [int]$env:PROGRESS_BAR_LENGTH
        } else {
             # Optionally log a warning if the env var is invalid
             Write-Warning "PROGRESS_BAR_LENGTH environment variable is not set or invalid. Using default length $barLength."
        }

        $percent = 0;
        if ($Total -gt 0) {
             $percent = [math]::Round(($Current / $Total) * 100)
        }
        $filledLength = [math]::Round(($barLength * $percent) / 100)
        # Ensure filledLength doesn't exceed barLength due to rounding edge cases
        $filledLength = [math]::Min($filledLength, $barLength)
        $emptyLength = $barLength - $filledLength
        $filledBar = ('=' * $filledLength)
        $emptyBar = (' ' * $emptyLength)
        # Use the padded message here
        Write-Host -NoNewline "$paddedMessage [$filledBar$emptyBar] $percent% ($Current/$Total)`r"
    } catch {
        # Fallback calculation in case of errors during bar generation
        $percent = 0; if ($Total -gt 0) { $percent = [math]::Round(($Current / $Total) * 100) }
        # Use the padded message here as well
        Write-Host "$paddedMessage Progress: $percent% ($Current/$Total)"
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