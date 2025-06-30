param(
    [Parameter(Mandatory=$true)]
    [string]$unzippedDirectory,
    [string]$step
)


$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

$RecycleBinPath = Join-Path -Path $unzippedDirectory -ChildPath '$RECYCLE.BIN'

#Utils Dirctory
$UtilDirectory = Join-Path $scriptDirectory "..\Utils"
$UtilFile = Join-Path $UtilDirectory "Utils.psm1"
Import-Module $UtilFile -Force

# --- Centralized Logging Setup ---
try {
    $logFile = Join-Path $scriptDirectory "..\Logs" -ChildPath $("Step_$step" + "_" + "$scriptName.log")
    Initialize-ChildScriptLogger -ChildLogFilePath $logFile
} catch {
    Write-Error "FATAL: Failed to initialize logger. Error: $_"
    exit 1
}


# Ensure the Recycle Bin path exists before attempting to change attributes
if (Test-Path -Path $RecycleBinPath -PathType Container) {
    Log "INFO" "Found Recycle Bin at '$RecycleBinPath'. Attempting to clear it."
    try {
        # The attrib command is for Windows CMD, but it's effective here.
        attrib -H -R -S -A $RecycleBinPath | Out-Null
        Remove-Item -Path (Join-Path -Path $RecycleBinPath -ChildPath "*") -Recurse -Force -ErrorAction Stop
        Log "INFO" "Successfully cleared contents of '$RecycleBinPath'."
    } catch {
        Log "ERROR" "Failed to clear Recycle Bin at '$RecycleBinPath'. Error: $_"
    }
} else {
    Log "INFO" "No '$RECYCLE.BIN' directory found in '$unzippedDirectory'. Nothing to do."
}
