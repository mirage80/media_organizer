param(
    [Parameter(Mandatory=$true)]
    [string]$unzippedDirectory,
    [Parameter(Mandatory=$true)]
    [string]$step
)

# --- Path Setup ---
$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

# --- Path Standardization ---
$unzippedDirectory = ConvertTo-StandardPath -Path $unzippedDirectory
$RecycleBinPath = Join-Path -Path $unzippedDirectory -ChildPath '$RECYCLE.BIN'

# Utils Directory
$UtilDirectory = Join-Path $scriptDirectory "..\Utils"
$UtilFile = Join-Path $UtilDirectory "Utils.psm1"
$MediaToolsFile = Join-Path $UtilDirectory 'MediaTools.psm1'
Import-Module $UtilFile -Force
Import-Module $MediaToolsFile -Force

# --- Logging Setup ---
$logDirectory = Join-Path $scriptDirectory "..\Logs"
$Logger = Initialize-ScriptLogger -LogDirectory $logDirectory -ScriptName $scriptName -Step $step
$Log = $Logger.Logger

# Inject logger for module functions
Set-UtilsLogger -Logger $Log
Set-MediaToolsLogger -Logger $Log

& $Log "INFO" "--- Script Started: $scriptName ---"

# Ensure the Recycle Bin path exists before attempting to change attributes
if (Test-Path -Path $RecycleBinPath -PathType Container) {
    & $Log "INFO" "Found Recycle Bin at '$RecycleBinPath'. Attempting to clear it."
    try {
        # Use native PowerShell to remove system/hidden attributes before deleting contents
        $recycleBinItem = Get-Item -Path $RecycleBinPath -Force
        $recycleBinItem.Attributes = 'Directory' # Resets attributes to a normal directory state
        
        # Remove all items *inside* the recycle bin folder.
        Remove-Item -Path "$($recycleBinItem.FullName)/*" -Recurse -Force -ErrorAction Stop
        & $Log "INFO" "Successfully cleared contents of '$RecycleBinPath'."
    } catch {
        & $Log "ERROR" "Failed to clear Recycle Bin at '$RecycleBinPath'. Error: $_"
    }
} else {
    & $Log "INFO" "No '$RECYCLE.BIN' directory found in '$unzippedDirectory'. Nothing to do."
}
