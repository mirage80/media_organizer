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

# --- Logging Setup for this script ---
# 1. Define the log file path
$childLogFilePath = Join-Path "$scriptDirectory\..\Logs" -ChildPath $("Step_$step" + "_" + "$scriptName.log")

# 2. Get logging configuration from environment variables
$logLevelMap = $env:LOG_LEVEL_MAP_JSON | ConvertFrom-Json -AsHashtable
$consoleLogLevel = $logLevelMap[$env:DEDUPLICATOR_CONSOLE_LOG_LEVEL.ToUpper()]
# For this high-frequency, multi-threaded step, we override the file log level to WARNING to improve performance.
# This avoids writing thousands of INFO/DEBUG messages to the log file, which can become a bottleneck.
# Errors and Warnings will still be logged.
$fileLogLevel    = $logLevelMap[$env:DEDUPLICATOR_FILE_LOG_LEVEL.ToUpper()]

# 3. Create a local, pre-configured logger for this script
$Log = {
    param([string]$Level, [string]$Message)
    Write-Log -Level $Level -Message $Message -LogFilePath $childLogFilePath -ConsoleLogLevel $consoleLogLevel -FileLogLevel $fileLogLevel -LogLevelMap $logLevelMap
}

# 4. Write initial log message to ensure file creation
& $Log "INFO" "--- Script Started: $scriptName ---"

# Inject logger for module functions that might be used by the main script itself
# (e.g., writing the results file at the end)
Set-UtilsLogger -Logger $Log

# Ensure the Recycle Bin path exists before attempting to change attributes
if (Test-Path -Path $RecycleBinPath -PathType Container) {
    & $Log "INFO" "Found Recycle Bin at '$RecycleBinPath'. Attempting to clear it."
    try {
        # Use native PowerShell to remove system/hidden attributes before deleting contents
        $recycleBinItem = Get-Item -Path $RecycleBinPath -Force
        $recycleBinItem.Attributes = 'Directory' # Resets attributes to a normal directory state
        
        Remove-Item -Path (Join-Path -Path $recycleBinItem.FullName -ChildPath "*") -Recurse -Force -ErrorAction Stop
        & $Log "INFO" "Successfully cleared contents of '$RecycleBinPath'."
    } catch {
        & $Log "ERROR" "Failed to clear Recycle Bin at '$RecycleBinPath'. Error: $_"
    }
} else {
    & $Log "INFO" "No '$RECYCLE.BIN' directory found in '$unzippedDirectory'. Nothing to do."
}
