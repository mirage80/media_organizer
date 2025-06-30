param(
    [Parameter(Mandatory=$true)]
    [string]$unzippedDirectory,
    [string]$ExifToolPath,
    [Parameter(Mandatory = $true)] [string]$step
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

# Define Image and Video extensions (these are from MediaTools.psm1 and are available after import)
$imageExtensions = $imageExtensions
$videoExtensions = $videoExtensions


#===========================================================
#                 Main functions
#===========================================================
# Create a destination directory for categorized files
$dstDirectory = New-Item -Path "$unzippedDirectory\dst" -ItemType Directory -Force

Log "INFO" "Scanning for media files in '$unzippedDirectory'..."
# Get all media files recursively and make the extension check case-insensitive.
$files = Get-ChildItem -Path $unzippedDirectory -Recurse -File | Where-Object {
    $ext = $_.Extension.ToLower()
    $imageExtensions -contains $ext -or $videoExtensions -contains $ext
}

if (-not $files) {
    Log "WARNING" "No media files found to categorize in '$unzippedDirectory'."
    # Clean up the empty dst directory and exit gracefully
    Remove-Item -Path $dstDirectory.FullName -Force -ErrorAction SilentlyContinue
    exit 0
}

$currentItem = 0
$totalItems = $files.count
Log "INFO" "Found $totalItems media files to categorize."
$runspaces = @()

$totalItems = $files.Count
$runspacePool = [RunspaceFactory]::CreateRunspacePool(1, 20)
$runspacePool.Open()
$UtilDirectory = Join-Path $scriptDirectory "..\Utils"
$progressFile = Join-Path $env:TEMP "categorize_progress_$PID.txt"
if (Test-Path $progressFile) { Remove-Item $progressFile }

foreach ($file in $files) {
    $ps = [PowerShell]::Create()
    $ps.AddScript({
        param(
            $filePathStr, $rootDirStr, $targetPathStr, $progressFile, $utilDir,
            $logFile, # Only need this for the logger init
            $ExifToolPath
        )

        try {
            # Import the utils module first, which contains the logger
            $utilsPath = Join-Path $utilDir 'Utils.psm1'
            Import-Module $utilsPath -Force

            # Initialize the logger for this thread. It will read config from env vars.
            Initialize-ChildScriptLogger -ChildLogFilePath $logFile

            # Now import the media tools module
            $mediaPath = Join-Path $utilDir 'MediaTools.psm1'
            Import-Module $mediaPath -Force

            # Set the ExifToolPath in the script scope so MediaTools can find it
            $script:ExifToolPath = $ExifToolPath

            # Log start of categorization
            Log "INFO" "THREAD START $filePathStr"

            $filePath = Get-Item $filePathStr
            $rootDir = Get-Item $rootDirStr
            $targetPath = Get-Item $targetPathStr

            Log "INFO" "Categorizing $filePathStr"

            $category = categorize_bulk_media_based_on_metadata_keep_directory_structure `
                -filePath $filePath `
                -rootDir $rootDir `
                -targetPath $targetPath

            # Log success
            # The function already logs the move, this is just for thread completion confirmation.
            Log "INFO" "THREAD SUCCESS: Categorized $($filePath.FullName) into '$category'."
        } catch {
            Log "ERROR" "Thread failed for $filePathStr : $_"
        } finally {
            Log "DEBUG"  "THREAD END $filePathStr" 
            Add-Content -Path $progressFile -Value $filePathStr
        }
    }) | Out-Null
    $ps.AddArgument($file.FullName) | Out-Null
    $ps.AddArgument($unzippedDirectory) | Out-Null
    $ps.AddArgument($dstDirectory) | Out-Null
    $ps.AddArgument($progressFile) | Out-Null
    $ps.AddArgument($UtilDirectory) | Out-Null
    $ps.AddArgument($logFile) | Out-Null
    $ps.AddArgument($ExifToolPath) | Out-Null
    $ps.RunspacePool = $runspacePool
    $runspaces += [PSCustomObject]@{ Pipe = $ps; Handle = $ps.BeginInvoke() }
}


$currentItem = 0
$lastProgress = -1
$waitCounter = 0

while ($currentItem -lt $totalItems) {
    Start-Sleep -Milliseconds 100
while ((Get-Content $progressFile -ErrorAction SilentlyContinue).Count -gt $currentItem) {
        $currentItem++
        Show-ProgressBar -Current $currentItem -Total $totalItems -Message "Categorizing $currentItem of $totalItems"
        $waitCounter = 0
    }

    if ($lastProgress -eq $currentItem) {
        $waitCounter++
    } else {
        $lastProgress = $currentItem
        $waitCounter = 0
    }

    if ($waitCounter -gt 100) {
        Write-Warning "No progress in 10 seconds. Thread(s) might be stalled."
        break
    }
}

# Clean up runspaces
foreach ($rs in $runspaces) {
    $rs.Pipe.EndInvoke($rs.Handle)
    $rs.Pipe.Dispose()
}
$runspacePool.Close()
$runspacePool.Dispose()

# --- Move categorized content from dst back to the root ---
Log "INFO" "Moving categorized folders from '$($dstDirectory.FullName)' back to '$unzippedDirectory'..."

# Get the category folders inside 'dst'
$categoryFolders = Get-ChildItem -Path $dstDirectory.FullName -Directory -ErrorAction SilentlyContinue

if ($categoryFolders) {
    foreach ($folder in $categoryFolders) {
        $destinationPath = Join-Path -Path $unzippedDirectory -ChildPath $folder.Name
        Log "INFO" "Moving '$($folder.FullName)' to '$unzippedDirectory' (will become '$destinationPath')..."
        try {
            # Move the category folder itself up one level
            Move-Item -Path $folder.FullName -Destination $unzippedDirectory -Force
        } catch {
            Log "ERROR" "Failed to move '$($folder.FullName)': $_"
        }
    }

    # --- Clean up the now empty dst directory ---
    Log "INFO" "Cleaning up the empty destination directory: $($dstDirectory.FullName)"
    try {
        # Optional: Verify it's truly empty before removing
        if (-not (Get-ChildItem -Path $dstDirectory.FullName -ErrorAction SilentlyContinue)) {
            Remove-Item -Path $dstDirectory.FullName -Force
            Log "INFO" "Successfully removed empty destination directory."
        } else {
             Log "WARNING" "Destination directory '$($dstDirectory.FullName)' was not empty after moving category folders. Manual cleanup might be required."
        }
    } catch {
        Log "ERROR" "Failed to remove destination directory '$($dstDirectory.FullName)': $_"
    }
} else {
    Log "WARNING" "No category folders found in '$($dstDirectory.FullName)' to move. The 'dst' directory might be empty or categorization failed."
    # Optionally remove the empty dst directory even if no category folders were found
    try {
        if (Test-Path $dstDirectory.FullName -PathType Container) {
             Remove-Item -Path $dstDirectory.FullName -Force -ErrorAction SilentlyContinue
             Log "INFO" "Removed potentially empty destination directory."
        }
    } catch {
         Log "ERROR" "Failed to remove destination directory '$($dstDirectory.FullName)' even though no category folders were found: $_"
    }
}

# Correct the final log message
Log "INFO" "Categorization and final move complete."