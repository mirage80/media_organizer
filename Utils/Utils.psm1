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

    # Check if running in a host that supports progress bars
    if ($null -eq $Host.UI.RawUI) {
        # Fallback for non-interactive environments or simplified hosts
        $percent = 0; 
        if ($Total -gt 0) { 
            $percent = [math]::Round(($Current / $Total) * 100) 
        }
        Write-Host "$Message Progress: $percent% ($Current/$Total)"
        return
    }
    try {
        $percent = [math]::Round(($Current / $Total) * 100)
        $screenWidth = $Host.UI.RawUI.WindowSize.Width - 30
        $barLength = [math]::Min($screenWidth, 80)
        $filledLength = [math]::Round(($barLength * $percent) / 100)
        $emptyLength = $barLength - $filledLength
        $filledBar = ('=' * $filledLength)
        $emptyBar = (' ' * $emptyLength)
        Write-Host -NoNewline "$Message [$filledBar$emptyBar] $percent% ($Current/$Total)`r"
    } catch {
        $percent = 0; if ($Total -gt 0) { $percent = [math]::Round(($Current / $Total) * 100) }
        Write-Host "$Message Progress: $percent% ($Current/$Total)"
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