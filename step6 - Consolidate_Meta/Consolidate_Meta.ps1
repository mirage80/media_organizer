# --- Start of Consolidate_Meta.ps1 ---
param(
    [Parameter(Mandatory=$true)]
    [string]$unzipedDirectory,
    [string]$ExifToolPath = 'C:\Program Files\exiftools\exiftool.exe'
)

$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

# --- Logging Setup ---
$logDir = Join-Path $scriptDirectory "..\Logs"
$logFile = Join-Path $logDir "$scriptName.log"
$logFormat = "{0} - {1}: {2}"

# Create the log directory if it doesn't exist
if (-not (Test-Path $logDir)) {
    try {
        New-Item -ItemType Directory -Path $logDir -Force -ErrorAction Stop | Out-Null
    } catch {
        Write-Error "FATAL: Failed to create log directory '$logDir'. Aborting. Error: $_"
        exit 1
    }
}

# Deserialize the JSON back into a hashtable
$logLevelMap = $null
$logLevelMap = $env:LOG_LEVEL_MAP_JSON

if (-not [string]::IsNullOrWhiteSpace($logLevelMap)) {
    try {
        # --- FIX IS HERE ---
        # Use -AsHashtable to ensure the correct object type
        $logLevelMap = $logLevelMap | ConvertFrom-Json -AsHashtable -ErrorAction Stop
        # --- END FIX ---
    } catch {
        # Log a fatal error and exit immediately if deserialization fails
        Write-Error "FATAL: Failed to deserialize LOG_LEVEL_MAP_JSON environment variable. Check the variable's content is valid JSON. Aborting. Error: $_"
        exit 1
    }
}
if ($null -eq $logLevelMap) {
    # This case should ideally not happen if top.ps1 ran, but handle defensively
    Write-Error "FATAL: LOG_LEVEL_MAP_JSON environment variable not found or invalid. Aborting."
    exit 1
}

# Check if required environment variables are set (by top.ps1 or externally)
if ($null -eq $env:DEDUPLICATOR_CONSOLE_LOG_LEVEL) {
    Write-Error "FATAL: Environment variable DEDUPLICATOR_CONSOLE_LOG_LEVEL is not set. Run via top.ps1 or set externally. Aborting."
    exit 1
}
if ($null -eq $env:DEDUPLICATOR_FILE_LOG_LEVEL) {
    Write-Error "FATAL: Environment variable DEDUPLICATOR_FILE_LOG_LEVEL is not set. Run via top.ps1 or set externally. Aborting."
    exit 1
}

# Read the environment variables directly and trim whitespace (NOW SAFE)
$EffectiveConsoleLogLevelString = $env:DEDUPLICATOR_CONSOLE_LOG_LEVEL.Trim()
$EffectiveFileLogLevelString    = $env:DEDUPLICATOR_FILE_LOG_LEVEL.Trim()

# Look up the numeric level using the effective string and the map
$consoleLogLevel = $logLevelMap[$EffectiveConsoleLogLevelString.ToUpper()]
$fileLogLevel    = $logLevelMap[$EffectiveFileLogLevelString.ToUpper()]

# --- Validation for THIS script's levels ---
if ($null -eq $consoleLogLevel) {
    Write-Error "FATAL: Invalid Console Log Level specified ('$EffectiveConsoleLogLevelString'). Check environment variable or script default. Aborting."
    exit 1
}
if ($null -eq $fileLogLevel) {
    Write-Error "FATAL: Invalid File Log Level specified ('$EffectiveFileLogLevelString'). Check environment variable or script default. Aborting."
    exit 1
}

# --- Log Function Definition ---
function Log {
    param (
        [string]$Level,
        [string]$Message
    )
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $formatted = $logFormat -f $timestamp, $Level.ToUpper(), $Message
    $levelIndex = $logLevelMap[$Level.ToUpper()]

    if ($null -ne $levelIndex) {
        if ($levelIndex -ge $consoleLogLevel) {
            Write-Host $formatted
        }
        if ($levelIndex -ge $fileLogLevel) {
            try {
                Add-Content -Path $logFile -Value $formatted -Encoding UTF8 -ErrorAction Stop
            } catch {
                Write-Warning "Failed to write to log file '$logFile': $_"
            }
        }
    } else {
        Write-Warning "Invalid log level used: $Level"
    }
}

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

# --- Script Setup ---
$modulePath = Join-Path $scriptDirectory 'MediaTools.psm1'
try {
    Import-Module $modulePath -Force
} catch {
    Log "CRITICAL" "Failed to import MediaTools module from '$modulePath'. Error: $_. Aborting."
    exit 1
}

# Define Image extensions in lowercase
$imageExtensions = $module:imageExtensions

# Define video extensions in lowercase
$videoExtensions = $module:videoExtensions
$hashLogPath = Join-Path $scriptDirectory "consolidation_log.json"  # << This line must come BEFORE functions
$processedLog = Get-ProcessedLog -LogPath $hashLogPath # Use the function from MediaTools.psm1

# Build a fast lookup hash set from the initial log
$processedSet = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
$processedLog | ForEach-Object {
    if ($_.path) { [void]$processedSet.Add($_.path) }
}
Log "INFO" "Loaded $($processedSet.Count) paths from initial log '$hashLogPath'."

# --- Get and Filter Files ---
Log "INFO" "Scanning for media files in '$unzipedDirectory'..."
if (-not (Test-Path $unzipedDirectory -PathType Container)) {
    Log "CRITICAL" "The media directory '$unzipedDirectory' is not valid or accessible. Aborting."
    exit 1
}
# Get media files
$files = Get-ChildItem -Path $unzipedDirectory -Recurse -File | Where-Object {
    $_.Extension.ToLower() -in $imageExtensions -or $_.Extension.ToLower() -in $videoExtensions
}
$filesToProcess = $files | Where-Object { -not $processedSet.Contains($_.FullName) }
$totalFilesToProcess = $filesToProcess.Count
Log "INFO" "Found $($files.Count) total media files. $totalFilesToProcess files need processing."

if ($totalFilesToProcess -eq 0) {
    Log "INFO" "No new files to process. Exiting."
    exit 0
}
Log "INFO" "Found $($files.Count) total media files. $($filesToProcess.Count) files need processing." # Log count

# Prepare collections
# --- Runspace Pool Setup ---
$maxThreads = [Math]::Max(1, [Environment]::ProcessorCount - 1)
Log "INFO" "Using up to $maxThreads worker threads."
$runspacePool = [runspacefactory]::CreateRunspacePool(1, $maxThreads)
$runspacePool.Open()
$runspaces = [System.Collections.Generic.List[object]]::new()
$syncErrors = [System.Collections.Concurrent.ConcurrentBag[string]]::new()
$results = [System.Collections.Generic.List[object]]::new() # Collect successful results IN MEMORY

# --- Start Threads ---
Log "INFO" "Starting runspace creation..."
foreach ($file in $filesToProcess) {
    $filePathCopy = $file.FullName
    Log "INFO" "MAIN: Preparing runspace for: $filePathCopy"

    # Define the script block for the runspace
    $scriptBlock = {
        param(
            $filePath,
            $modulePath,
            $ExifToolPath
        )
        # --- Create the thread-local list ---
        $LocalThreadLogs = [System.Collections.Generic.List[string]]::new()
        # --- Store the list in script scope for the module to access ---
        $script:ThreadLogList = $LocalThreadLogs
        try {
            # Set the ExifToolPath variable in the script scope *before* importing the module
            $script:ExifToolPath = $ExifToolPath
            # Import the module *after* setting script scope variables
            Import-Module $modulePath -Force
            $fileInfo = [System.IO.FileInfo]$filePath
            # Call the function from MediaTools.psm1
            Consolidate_Json_Exif_Data -File $fileInfo
            Add-ThreadLog "INFO" "Successfully processed $filePath" # Use Add-ThreadLog

            # Clean up _original backup
            $originalBackup = "$($fileInfo.FullName)_original"
            if (Test-Path -Path $originalBackup) {
                try {
                    Remove-Item -Path $originalBackup -Force -ErrorAction Stop
                    Add-ThreadLog "DEBUG" "Removed backup file: $originalBackup" # Calls module's func
                } catch {
                    Add-ThreadLog "WARNING" "Failed to remove backup file '$originalBackup': $($_.Exception.Message)" # Calls module's func
                }
            }

            # Prepare result for main thread, including logs
            return @{
                success   = $true
                path      = $fileInfo.FullName
                timestamp = (Get-Date).ToUniversalTime().ToString("o")
                # Return the list object itself
                logs      = $LocalThreadLogs
            }
        } catch {
            # Log the error using the module's Add-ThreadLog
            $errorMessage = "Error processing '$filePath': $($_.Exception.Message) - StackTrace: $($_.ScriptStackTrace)"
            # Ensure Add-ThreadLog is available even in catch block (module should be imported)
            try { Add-ThreadLog "ERROR" $errorMessage } catch { Write-Warning "Failed to log error via Add-ThreadLog in catch block: $_" }

            # Return failure result, including logs
            return @{
                success = $false
                path    = $filePath
                error   = $errorMessage
                # Return the list object itself
                logs    = $LocalThreadLogs
            }
        } finally {
            Remove-Module (Split-Path $modulePath -LeafBase) -ErrorAction SilentlyContinue
        }
    } # End ScriptBlock

    # Create PowerShell instance and add arguments
    $ps = [powershell]::Create().AddScript($scriptBlock)
    $ps.AddArgument($filePathCopy) | Out-Null
    $ps.AddArgument($modulePath) | Out-Null
    $ps.AddArgument($ExifToolPath) | Out-Null # Pass ExifTool path

    $ps.RunspacePool = $runspacePool
    $handle = $ps.BeginInvoke()
    Log "INFO" "MAIN: Runspace started for: $filePathCopy" # <-- ADD THIS (Optional)

    $runspaces += [PSCustomObject]@{
        Pipe   = $ps
        Handle = $handle
        Path   = $filePathCopy 
    }
    Log "INFO" "MAIN: Runspace Ended for: $filePathCopy" # <-- ADD THIS (Optional)
}
Log "INFO" "All runspaces created ($($runspaces.Count)). Waiting for completion..."

$results = @()

# --- Collect Results ---
$progressCounter = 0
foreach ($runspaceInfo in $runspaces) {
    $ps = $runspaceInfo.Pipe
    $handle = $runspaceInfo.Handle
    $runspacePath = $runspaceInfo.Path # Get path for context
    $result = $null
    try {
        $result = $ps.EndInvoke($handle) # Wait for this specific job
    } catch {
        $errorMsg = "Failed to get result from runspace for path '$runspacePath': $($_.Exception.Message)"
        Log "ERROR" $errorMsg
        $syncErrors.Add($errorMsg)
    } finally {
        $ps.Dispose()
    }
    # Process the result if EndInvoke succeeded
    if ($null -ne $result) {
        $progressCounter++
        # --- Log Messages FIRST ---
        if ($result.logs -is [System.Collections.IList] -and $result.logs.Count -gt 0) {
            Log "DEBUG" "MAIN: Processing $($result.logs.Count) log entries for path: $($result.path)"
            foreach ($logEntry in $result.logs) {
                if ($logEntry -match '^\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\s-\s(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s-\s(?:\(Thread\s\d+\)\s-\s)?(.*)$') {
                    $logLevel = $matches[1]
                    $logMessage = $matches[2]
                    Log $logLevel $logMessage # Call main thread's Log function
                } else {
                    Log "INFO" $logEntry 
                }
            }
        } else {
            Log "DEBUG" "MAIN: No logs returned for path: $($result.path)"
		}
        # --- END Log Messages ---

        if ($result.success) {
            $newEntry = @{
                path      = $result.path
                timestamp = $result.timestamp
            }
            # Add to in-memory list for final consolidation
            $results += $newEntry
            # --- Per-Thread Log Write (Crash Recovery Mechanism) ---
            # This block writes the result immediately for crash recovery.
            # It reads/writes the whole file, which is less efficient but saves progress.
            Log "DEBUG" "Attempting incremental log write for $($newEntry.path) (Crash Recovery)"
            $jsonLockPath = "$hashLogPath.lock"
            $lockRetryCount = 10
            $lockAcquired = $false
            for ($i = 0; $i -lt $lockRetryCount; $i++) {
                try {
                    if (-not (Test-Path $jsonLockPath)) {
                        # Attempt atomic creation
                        $fs = [System.IO.File]::Open($jsonLockPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
                        $fs.Close() # Close immediately after creation
                        $lockAcquired = $true
                        Log "DEBUG" "Acquired lock file $jsonLockPath for $($newEntry.path)"

                        # Load current log (within lock)
                        $existingLog = @()
                        if (Test-Path -Path $hashLogPath) {
                            try {
                                # Use StreamReader for potentially large files
                                $logContent = Get-Content -Path $hashLogPath -Raw -Encoding UTF8 -ErrorAction Stop
                                if (-not [string]::IsNullOrWhiteSpace($logContent)) {
									$existingLog = $logContent | ConvertFrom-Json -ErrorAction Stop
									if ($null -ne $existingLog -and -not ($existingLog -is [System.Collections.IEnumerable])) {
										$existingLog = @($existingLog)
									}
                                }
                            } catch {
                                Log "WARNING" "Failed to read or parse existing log '$hashLogPath' during incremental write for '$($newEntry.path)': $_. Treating as empty."
                                $existingLog = @()
                            }
                        }

                        # Merge + dedupe + save incrementally
                        $updatedLog = $existingLog + $newEntry
                        $dedupedLog = $updatedLog | Sort-Object -Property path -Unique -CaseSensitive # Paths are case-sensitive usually
                        # Consider Write-JsonAtomic if available, otherwise direct write:
                        $dedupedLog | ConvertTo-Json -Depth 5 | Set-Content -Path $hashLogPath -Encoding UTF8 -Force
                        Log "INFO" "Incrementally updated log for $($newEntry.path) (Crash Recovery)"
                        break # Exit retry loop
                    }
                } catch [System.IO.IOException] {
                    # Catch specific IO exception if lock file creation failed because it exists
                    Log "DEBUG" "Lock file $jsonLockPath busy, retrying incremental write ($($i+1)/$lockRetryCount)..."
                    Start-Sleep -Milliseconds (Get-Random -Minimum 100 -Maximum 300)
                } catch {
                    Log "ERROR" "Error during incremental log update for $($newEntry.path) on attempt $($i+1): $_"
                } finally {
                    if ($lockAcquired) {
                        Remove-Item $jsonLockPath -Force -ErrorAction SilentlyContinue
                        Log "DEBUG" "Released lock file $jsonLockPath for $($newEntry.path)"
                    }
                }

                # Wait before next retry if lock wasn't acquired
                if (-not $lockAcquired) {
                     Start-Sleep -Milliseconds (Get-Random -Minimum 100 -Maximum 300) # Add jitter
                }
            } # End for loop (retries)

            if (-not $lockAcquired) {
                 Log "ERROR" "Failed to acquire lock for incremental write for $($newEntry.path) after $lockRetryCount attempts."
                 $syncErrors.Add("Failed to write incremental log for $($newEntry.path)")
            }
            # --- End Per-Thread Log Write ---

        } else {
            # Log error from the failed thread
            Log "ERROR" "Thread failed for $($result.path): $($result.error)"
            $syncErrors.Add($result.error) # Add error to the concurrent bag
        }
        # Update main progress bar
        Show-ProgressBar -Message "Consolidating Meta:" -Current $progressCounter -Total $totalFilesToProcess
    } else {
        # Handle case where EndInvoke returned null but didn't throw
        $progressCounter++ # Still count it?
        Log "WARNING" "Runspace for path '$runspacePath' returned null result."
        Show-ProgressBar -Message "Consolidating Meta:" -Current $progressCounter -Total $totalFilesToProcess
    }
} # End foreach runspaceInfo
Write-Host "" # New line after progress bar

Log "INFO" "All runspaces finished. Closing pool..."
$runspacePool.Close()
$runspacePool.Dispose()

# --- Final Log Consolidation (Ensures clean state on SUCCESSFUL completion) ---
# This combines the log state from BEFORE the script started ($processedLog)
# with ALL successful results collected during this run ($results).
# This corrects any inconsistencies potentially introduced by concurrent per-thread writes.
Log "INFO" "Performing final log consolidation..."

# Combine initial log state with results collected in memory during this run
# DO NOT re-read the file here, as it might be messy from concurrent writes.
$combinedLog = $processedLog + $results # Use initial log + in-memory results
$dedupedLog = $combinedLog | Sort-Object -Property path -Unique -CaseSensitive

# Save the final deduplicated log (atomically if possible)
try {
    # Use Write-JsonAtomic if available and defined in top.ps1 or here
    # Write-JsonAtomic -Data $dedupedLog -Path $hashLogPath
    # OR direct write:
    $dedupedLog | ConvertTo-Json -Depth 5 | Set-Content -Path $hashLogPath -Encoding UTF8 -Force
    Log "INFO" "✅ Final log consolidation successful. Saved $($dedupedLog.Count) unique entries."
} catch {
    Log "ERROR" "❌ Failed to write final consolidated log file '$hashLogPath': $_"
    $syncErrors.Add("Failed to write final log file: $($_.Exception.Message)")
}

# --- Report Errors ---
if ($syncErrors.Count -gt 0) {
    Log "ERROR" "$($syncErrors.Count) errors occurred during processing:"
    $syncErrors | ForEach-Object { Log "ERROR" "- $_" }
} else {
    Log "INFO" "✅ Processing completed with no errors reported by threads or final save."
}

# --- Delete JSON files ---
Log "INFO" "Deleting JSON sidecar files..."
$deletedCount = 0
$deletionErrors = 0
# Ensure $unzipedDirectory is valid before proceeding
if (Test-Path $unzipedDirectory -PathType Container) {
    try {
        Get-ChildItem -Path $unzipedDirectory -Filter *.json -Recurse -File | ForEach-Object {
            Log "DEBUG" "Attempting to delete $($_.FullName)"
            try {
                Remove-Item $_.FullName -Force -ErrorAction Stop
                $deletedCount++
            } catch {
                Log "WARNING" "Failed to delete: $($_.FullName) - $_"
                $deletionErrors++
            }
        }
        Log "INFO" "Deleted $deletedCount JSON files."
        if ($deletionErrors -gt 0) {
            Log "WARNING" "Encountered $deletionErrors errors while deleting JSON files."
        }
    } catch {
         Log "ERROR" "Error enumerating JSON files for deletion in '$unzipedDirectory': $_"
    }
} else {
     Log "ERROR" "Cannot delete JSON files because directory '$unzipedDirectory' does not exist."
}
Remove-Item $hashLogPath -Force
Log "INFO" "Step 6 - Consolidate_Meta finished."
# --- End of Consolidate_Meta.ps1 ---