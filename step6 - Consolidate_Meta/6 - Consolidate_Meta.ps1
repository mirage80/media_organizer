# Define the script directory
$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent

$modulePath = Join-Path $scriptDirectory 'MediaTools.psm1'
Import-Module $modulePath -Force

# Define Image extensions in lowercase
$imageExtensions = @(".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".heic")

# Define video extensions in lowercase
$videoExtensions = @(".mp4", ".mov", ".avi", ".mkv", ".flv", ".webm")


# Define timestamp fields for different file extensions
$TimeStampFields = @{
    ".jpeg" = @("DateTimeOriginal", "CreateDate", "DateAcquired")
    ".jpg"  = @("DateTimeOriginal", "CreateDate", "DateAcquired")
    ".heic" = @("DateTimeOriginal", "DateCreated", "DateTime")
    ".mov"  = @("TrackCreateDate", "CreateDate", "MediaCreateDate")
    ".mp4"  = @("TrackCreateDate", "MediaModifyDate", "MediaCreateDate", "TrackModifyDate")
}

# Define GPS fields for different file extensions
$gpsFields = @{
    ".jpeg" = @("GPSLatitudeRef", "GPSLatitude", "GPSLongitudeRef", "GPSLongitude", "GPSPosition")
    ".jpg"  = @("GPSLatitudeRef", "GPSLatitude", "GPSLongitudeRef", "GPSLongitude", "GPSPosition")
    ".heic" = @("GPSLatitudeRef", "GPSLatitude", "GPSLongitudeRef", "GPSLongitude", "GPSPosition")
    ".mov"  = @("GPSLatitudeRef", "GPSLatitude", "GPSLongitudeRef", "GPSLongitude", "GPSPosition")
    ".mp4"  = @("GPSLatitudeRef", "GPSLatitude", "GPSLongitudeRef", "GPSLongitude", "GPSPosition")
}

# Define patterns for extracting timestamps from filenames
$patterns = @(
    '(?<date>\d{4}-\d{2}-\d{2})_(?<time>\d{2}-\d{2}-\d{2})_-\d+',  # Matches 2019-02-18_13-12-18_-_89373.jpg
    '(?<date>\d{4}-\d{2}-\d{2})_(?<time>\d{2}-\d{2}-\d{2})',       # Matches 2020-03-31_16-04-32.mp4
    '(?<date>\d{2}-\d{2}-\d{4})@(?<time>\d{2}-\d{2}-\d{2})',       # Matches 29-03-2023@12-34-56
    '(?<date>\d{4}_\d{4})_(?<time>\d{6})',                         # Matches 2023_0329_123456
    '(?<date>\d{8})_(?<time>\d{6})-\w+',                           # Matches 20240214_103148-4d0e
    '(?<date>\d{8})_(?<time>\d{6})',                               # Matches 20240122_175641
    '(?<date>\d{8})',                                              # Matches VID_20200311
    '(?<date>\d{4}-\d{2}-\d{2})\(\d+\)',                           # Matches 2023-07-27(10).jpg
    '(?<date>[A-Za-z]{3} \d{1,2}, \d{4}), (?<time>\d{1,2}:\d{2}:\d{2}(AM|PM))',  # Matches Mar 29, 2023, 12:34:56PM
    '(?<date>\d{4}/\d{2}/\d{2}) (?<time>\d{2}:\d{2}:\d{2})',       # Matches 2023/03/29 12:34:56
    '(?<date>\d{4}-\d{2}-\d{2}) (?<time>\d{2}:\d{2}:\d{2}\.\d{3})',  # Matches 2023-03-29 12:34:56.123
    '@(?<date>\d{2}-\d{2}-\d{4})_(?<time>\d{2}-\d{2}-\d{2})',      # Matches photo_1406@18-10-2016_06-50-25
    '(?<date>\d{4}:\d{2}:\d{2}) (?<time>\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:[+-]\d{2}:\d{2})?)',  # Matches 2023:03:29 12:34:56+00:00
    '(?<prefix>[A-Za-z]+)_(?<date>\d{8})_(?<time>\d{6})'           # Matches PREFIX_YYYYMMDD_HHMMSS
)

# Define time formats for validating timestamps
$time_formats = @(
    "yyyy:MM:dd HH:mm:sszzz",       # Standard format with timezone offset
    "yyyy:MM:dd HH:mm:ss zzz",      # Standard format with space before offset
    "yyyy:MM:dd HH:mm:ss.fffzzz",   # Format with milliseconds and timezone offset
    "yyyy-MM-ddTHH:mm:sszzz",       # ISO 8601 format
    "yyyy-MM-dd HH:mm:ss",          # Common format without timezone
    "yyyy-MM-ddTHH:mm:ss",          # ISO 8601 without timezone
    "yyyy-MM-dd HH:mm:ss.fff",      # Format with milliseconds
    "MM/dd/yyyy HH:mm:ss zzz",      # US format with timezone offset
    "MMM d, yyyy, h:mm:sstt",       # Format with month name and AM/PM
    "MMM d, yyyy, h:mm:ss tt",      # Format with month name, AM/PM, and space
    "MMM d, yyyy, h:mm:ssttzzz",    # **New format for Jan 23, 2024, 3:44:03PM+00:00**
    "yyyy:MM:dd HH:mm:ss.ff zzz",   # Format with fractional seconds
    "yyyy:MM:dd HH:mm:ss.fffzzz",   # Format with milliseconds
    "yyyy:MM:dd HH:mm:ss"           # Format without timezone
)

$hashLogPath = Join-Path $scriptDirectory "consolidation_log.json"  # << This line must come BEFORE functions



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