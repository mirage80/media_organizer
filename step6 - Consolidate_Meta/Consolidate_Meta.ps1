# --- Logging Setup ---
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)
$logDir = Join-Path $scriptDirectory "..\Logs"
$logFile = Join-Path $logDir "$scriptName.log"
$logFormat = "{0} - {1}: {2}"

# Create the log directory if it doesn't exist
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

# Set default log levels if not present in environment
$env:DEDUPLICATOR_CONSOLE_LOG_LEVEL = $env:DEDUPLICATOR_CONSOLE_LOG_LEVEL ?? "INFO"
$env:DEDUPLICATOR_FILE_LOG_LEVEL    = $env:DEDUPLICATOR_FILE_LOG_LEVEL    ?? "DEBUG"

# Map log level strings to priorities
$logLevelMap = @{
    "DEBUG"    = 0
    "INFO"     = 1
    "WARNING"  = 2
    "ERROR"    = 3
    "CRITICAL" = 4
}

$consoleLogLevel = $logLevelMap[$env:DEDUPLICATOR_CONSOLE_LOG_LEVEL.ToUpper()]
$fileLogLevel = $logLevelMap[$env:DEDUPLICATOR_FILE_LOG_LEVEL.ToUpper()]

function Log {
    param (
        [string]$Level,
        [string]$Message
    )
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $formatted = $logFormat -f $timestamp, $Level.ToUpper(), $Message
    $levelIndex = $logLevelMap[$Level.ToUpper()]

    if ($null -ne $levelIndex) { # Check if the level is valid
        if ($levelIndex -ge $consoleLogLevel) {
            Write-Host $formatted # Use Write-Host directly
        }
        if ($levelIndex -ge $fileLogLevel) {
            try {
                Add-Content -Path $logFile -Value $formatted -Encoding UTF8
            } catch {
                Write-Warning "Failed to write to log file '$logFile': $_"
            }
        }
    } else {
        Write-Warning "Invalid log level used: $Level"
        Write-Host $formatted # Still write to host for invalid levels? Or handle differently.
    }
}

# === Logging Utilities ===
function Get-FileHashString {
    param (
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$File
    )
    if (-not (Test-Path $File.FullName)) {
        throw "File not found: $($File.FullName)"
    }
    $hash = Get-FileHash -Path $File.FullName -Algorithm SHA256
    return $hash.Hash
}


# Define the script directory
$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent

$modulePath = Join-Path $scriptDirectory 'MediaTools.psm1'
Import-Module $modulePath -Force

# Define Image extensions in lowercase
$imageExtensions = @(".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".heic")

# Define video extensions in lowercase
$videoExtensions = @(".mp4", ".mov", ".avi", ".mkv", ".flv", ".webm")

$hashLogPath = Join-Path $scriptDirectory "consolidation_log.json"  # << This line must come BEFORE functions
$processedLog = Get-ProcessedLog -LogPath $hashLogPath # Use the function from MediaTools.psm1

# Define max number of threads
$maxThreads = 8

# Prepare runspace-related types
Add-Type -AssemblyName System.Collections
Add-Type -AssemblyName System.Management.Automation

# Define where your media lives
if (-not (Test-Path $unzipedDirectory)) {
    Write-Warning "The variable 'unzipedDirectory' is not valid. Exiting..."
    exit
}

# Get media files
$files = Get-ChildItem -Path $unzipedDirectory -Recurse -File | Where-Object {
    $_.Extension.ToLower() -in $imageExtensions -or $_.Extension.ToLower() -in $videoExtensions
}

# Prepare collections
$runspacePool = [runspacefactory]::CreateRunspacePool(1, $maxThreads)
$runspacePool.Open()
$runspaces = @()
$syncErrors = [System.Collections.Concurrent.ConcurrentBag[string]]::new()

# Processed log (already loaded)
$syncLog = [System.Collections.Concurrent.ConcurrentBag[object]]::new()
$processedLog | ForEach-Object { $syncLog.Add($_) }

# Build a fast lookup hash set
$processedSet = New-Object 'System.Collections.Generic.HashSet[string]'
$processedLog | ForEach-Object { [void]$processedSet.Add($_.path) }

# Filter the files before runspace generation
$filesToProcess = $files | Where-Object { -not $processedSet.Contains($_.FullName) }

foreach ($file in $filesToProcess) {
    $filePathCopy = $file.FullName

    $ps = [powershell]::Create().AddScript({
        param($filePath, $modulePath)

        try {
            Import-Module $modulePath -Force

            $file = [System.IO.FileInfo]$filePath
            Write-Host "🧵 Thread ID: $([System.Threading.Thread]::CurrentThread.ManagedThreadId) - Processing: $filePath"

            Consolidate_Json_Exif_Data -File $file
            Write-Host "🧵 Thread ID: $([System.Threading.Thread]::CurrentThread.ManagedThreadId) - Processing: $filePath"

            # Clean up _original backup
            $originalBackup = "$($file.FullName)_original"
            if (Test-Path -Path $originalBackup) {
                Remove-Item -Path $originalBackup -Force
            }
            # Prepare result for main thread to handle logging
            return @{
                success = $true
                path    = $file.FullName
                timestamp = (Get-Date).ToUniversalTime().ToString("o")
            }
        } catch {
            return @{
                success = $false
                path    = $filePath
                error   = $_.Exception.Message
            }
        }

    }).AddArgument($filePathCopy).AddArgument($modulePath)

    $ps.RunspacePool = $runspacePool
    $handle = $ps.BeginInvoke()

    $runspaces += [PSCustomObject]@{
        Pipe   = $ps
        Handle = $handle
    }
}

$results = @()

foreach ($runspace in $runspaces) {
    $ps = $runspace.Pipe
    $handle = $runspace.Handle
    $result = $ps.EndInvoke($handle)
    $ps.Dispose()

    if ($result.success) {
        $newEntry = @{
            path      = $result.path
            timestamp = $result.timestamp
        }
    
        $results += $newEntry
        Show-ProgressBar -Message "step6: " -current $results.Count -Total $filesToProcess.Count
    
        # Update JSON log safely and atomically
        $jsonLockPath = "$hashLogPath.lock"
    
        for ($i = 0; $i -lt 10; $i++) {
            try {
                # Wait until no other process is writing
                $lockAcquired = $false
                if (!(Test-Path $jsonLockPath)) {
                    New-Item -Path $jsonLockPath -ItemType File -Force | Out-Null
                    $lockAcquired = $true
                }
    
                if ($lockAcquired) {
                    # Load current log
                    $existingLog = @()
                    if (Test-Path -Path $hashLogPath) {
                        try {
                            $existingLog = Get-Content -Path $hashLogPath -Raw | ConvertFrom-Json
                            if (-not ($existingLog -is [System.Collections.IEnumerable])) {
                                $existingLog = @($existingLog)
                            }
                        } catch {
                            $existingLog = @()
                        }
                    }
    
                    # Merge + dedupe + save
                    $updatedLog = $existingLog + $newEntry
                    $dedupedLog = $updatedLog | Sort-Object -Property path -Unique
                    $dedupedLog | ConvertTo-Json -Depth 3 | Set-Content -Path $hashLogPath -Encoding UTF8
                    Remove-Item $jsonLockPath -Force
                    break
                } else {
                    Start-Sleep -Milliseconds 200
                }
            } catch {
                if (Test-Path $jsonLockPath) {
                    Remove-Item $jsonLockPath -Force -ErrorAction SilentlyContinue
                }
                if ($i -eq 9) {
                    Write-Warning "❌ Failed to write log for $($newEntry.path): $_"
                } else {
                    Start-Sleep -Milliseconds 200
                }
            }
        }
    }
    else {
        $syncErrors.Add($result.error)
        Write-Warning "❌ Failed to process $($result.path): $($result.error)"
    }    
}

$runspacePool.Close()
$runspacePool.Dispose()

# Load previous log
$existingLog = @()
if (Test-Path -Path $hashLogPath) {
    try {
        $existingLog = Get-Content -Path $hashLogPath -Raw | ConvertFrom-Json
    } catch {
        Write-Warning "⚠️ Failed to read existing log. Starting fresh."
    }
}

# Deduplicate based on file path
$combinedLog = $existingLog + $results
$dedupedLog = $combinedLog | Sort-Object -Property path -Unique

# Save to disk
try {
    $dedupedLog | ConvertTo-Json -Depth 3 | Set-Content -Path $hashLogPath -Encoding UTF8
    
    Write-Host "✅ Saved updated log with $($dedupedLog.Count) entries."
} catch {
    Write-Warning "❌ Failed to write log file: $_"
}

$deletedCount = 0

Get-ChildItem -Path $unzipedDirectory -Filter *.json -Recurse -File | ForEach-Object {
    try {
        Remove-Item $_.FullName -Force
        $deletedCount++
    } catch {
        Write-Warning "Failed to delete: $($_.FullName) - $_"
    }
}