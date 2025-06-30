# --- Start of Consolidate_Meta.ps1 ---
param(
    [Parameter(Mandatory=$true)]
    [string]$unzippedDirectory,
    [string]$ExifToolPath,
    [string]$step
)

$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

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

# --- Script Setup ---
$MediaToolsFile = Join-Path $UtilDirectory 'MediaTools.psm1'
try {
    Import-Module $MediaToolsFile -Force
} catch {
    Log "CRITICAL" "Failed to import MediaTools module from '$MediaToolsFile'. Error: $_. Aborting."
    exit 1
}


# Define Image extensions in lowercase
$imageExtensions = $module:imageExtensions

# Define video extensions in lowercase
$videoExtensions = $module:videoExtensions
$hashLogPath = Join-Path $scriptDirectory "consolidation_log.json"  # << This line must come BEFORE functions
# --- Get and Filter Files ---
Log "INFO" "Scanning for media files in '$unzippedDirectory'..."
if (-not (Test-Path $unzippedDirectory -PathType Container)) {
    Log "CRITICAL" "The media directory '$unzippedDirectory' is not valid or accessible. Aborting."
    exit 1
}
# Get media files
$files = Get-ChildItem -Path $unzippedDirectory -Recurse -File | Where-Object {
    $_.Extension.ToLower() -in $imageExtensions -or $_.Extension.ToLower() -in $videoExtensions
}
# For this script, we process all files to ensure metadata is correct, so we don't filter based on a previous log.
# If skipping is desired, a more robust mechanism would be needed.
$filesToProcess = $files

$totalFilesToProcess = $filesToProcess.Count
Log "INFO" "Found $($files.Count) total media files. $totalFilesToProcess files need processing."

if ($totalFilesToProcess -eq 0) {
    Log "INFO" "No new files to process. Proceeding to final cleanup."
    # We let the script continue to the cleanup phase to ensure any orphaned JSON files from a prior failed run are removed.
}

# Prepare collections
# --- Runspace Pool Setup ---
$maxThreads = [Math]::Max(1, [Environment]::ProcessorCount - 1)
Log "INFO" "Using up to $maxThreads worker threads."
$runspacePool = [RunspaceFactory]::CreateRunspacePool(1, $maxThreads)
$runspacePool.Open()
$runspaces = [System.Collections.Generic.List[object]]::new()
$syncErrors = [System.Collections.Concurrent.ConcurrentBag[string]]::new()
$progressFile = Join-Path $env:TEMP "consolidate_meta_progress_$PID.txt"
if (Test-Path $progressFile) {
    Remove-Item $progressFile -Force
}

# --- Start Threads ---
Log "INFO" "Starting runspace creation..."
foreach ($file in $filesToProcess) {
    $filePathCopy = $file.FullName

    # Define the script block for the runspace
    $scriptBlock = {
        param(
            [string]$filePath,
            [string]$mediaToolsModulePath,
            [string]$utilsModulePath,
            [string]$ExifToolPath,
            [string]$logFileForThread,
            [string]$progressFileForThread
        )
        try {
            # Import the utils module first, which contains the logger
            Import-Module $utilsModulePath -Force

            # Initialize the logger for this thread. It will read config from env vars.
            Initialize-ChildScriptLogger -ChildLogFilePath $logFileForThread

            # Set the ExifToolPath variable in the script scope *before* importing the module
            $script:ExifToolPath = $ExifToolPath
            # Import the module *after* setting script scope variables
            Import-Module $mediaToolsModulePath -Force

            $fileInfo = [System.IO.FileInfo]$filePath
            # Call the function from MediaTools.psm1
            Consolidate_Json_Exif_Data -File $fileInfo
            Log "INFO" "THREAD: Successfully processed $filePath"

            # Clean up _original backup
            $originalBackup = "$($fileInfo.FullName)_original"
            if (Test-Path -Path $originalBackup) {
                try {
                    Remove-Item -Path $originalBackup -Force -ErrorAction Stop
                    Log "DEBUG" "THREAD: Removed backup file: $originalBackup"
                } catch {
                    Log "WARNING" "THREAD: Failed to remove backup file '$originalBackup': $($_.Exception.Message)"
                }
            }

            # Prepare a simple result for the main thread
            return @{
                success   = $true
                path      = $fileInfo.FullName
                timestamp = (Get-Date).ToUniversalTime().ToString("o")
            }
        } catch {
            # Log the error using the standard Log function
            $errorMessage = "Error processing '$filePath': $($_.Exception.Message) - StackTrace: $($_.ScriptStackTrace)"
            Log "ERROR" "THREAD: $errorMessage"
            return @{ success = $false; path = $filePath; error = $errorMessage }
        } finally {
            # Clean up the imported modules from the runspace
            Remove-Module (Split-Path $mediaToolsModulePath -LeafBase) -ErrorAction SilentlyContinue
            Remove-Module (Split-Path $utilsModulePath -LeafBase) -ErrorAction SilentlyContinue
            Add-Content -Path $progressFileForThread -Value "done"
        }
    } # End ScriptBlock

    # Create PowerShell instance and add arguments
    $ps = [PowerShell]::Create().AddScript($scriptBlock)
    $ps.AddArgument($filePathCopy) | Out-Null
    $ps.AddArgument($MediaToolsFile) | Out-Null
    $ps.AddArgument($UtilFile) | Out-Null
    $ps.AddArgument($ExifToolPath) | Out-Null # Pass ExifTool path
    $ps.AddArgument($logFile) | Out-Null
    $ps.AddArgument($progressFile) | Out-Null

    $ps.RunspacePool = $runspacePool
    $handle = $ps.BeginInvoke()

    $runspaces += [PSCustomObject]@{
        Pipe   = $ps
        Handle = $handle
        Path   = $filePathCopy 
    }
}
Log "INFO" "All runspaces created ($($runspaces.Count)). Waiting for completion..."

# --- Wait for Completion & Show Progress ---
$currentItem = 0
while ($currentItem -lt $totalFilesToProcess) {
    $progressCount = 0
    if (Test-Path $progressFile) {
        try { $progressCount = (Get-Content $progressFile -ErrorAction SilentlyContinue).Count } catch {}
    }

    if ($progressCount -gt $currentItem) {
        $currentItem = $progressCount
        Show-ProgressBar -Message "Consolidating Meta:" -Current $currentItem -Total $totalFilesToProcess
    }
    Start-Sleep -Milliseconds 100
}

# --- Collect Results ---
foreach ($runspaceInfo in $runspaces) {
    try {
        # Wait for the job to finish and get the result
        $result = $runspaceInfo.Pipe.EndInvoke($runspaceInfo.Handle)

        if ($null -ne $result) {
            if (-not $result.success) {
                # The thread already logged the detailed error. This is a summary log.
                Log "ERROR" "MAIN: Thread for path '$($runspaceInfo.Path)' reported failure: $($result.error)"
                $syncErrors.Add($result.error)
            }
        } else {
            Log "WARNING" "MAIN: Runspace for path '$($runspaceInfo.Path)' returned a null result."
        }
    } catch {
        $errorMsg = "MAIN: Failed to get result from runspace for path '$($runspaceInfo.Path)': $($_.Exception.Message)"
        Log "ERROR" $errorMsg
        $syncErrors.Add($errorMsg)
    } finally {
        # Clean up the runspace resources
        $runspaceInfo.Pipe.Dispose()
    }
}
Write-Host "" # New line after progress bar

Log "INFO" "All runspaces finished. Closing pool..."
$runspacePool.Close()
$runspacePool.Dispose()

# --- Report Errors ---
if ($syncErrors.Count -gt 0) {
    Log "ERROR" "$($syncErrors.Count) errors occurred during processing:"
    $syncErrors | ForEach-Object { Log "ERROR" "- $_" }
} else {
    Log "INFO" "✅ Processing completed with no errors reported by threads."
}

# --- Final Cleanup ---
if (Test-Path $progressFile) {
    Remove-Item $progressFile -Force -ErrorAction SilentlyContinue
}

Log "INFO" "Step 6 - Consolidate_Meta finished."
# --- End of Consolidate_Meta.ps1 ---