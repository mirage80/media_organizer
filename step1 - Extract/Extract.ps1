param(
    [Parameter(Mandatory=$true)]
    $Config
)

# --- Path Setup ---
$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

# Utils Directory
$UtilDirectory = Join-Path $scriptDirectory "..\Utils"
$UtilFile = Join-Path $UtilDirectory "Utils.psm1"
$MediaToolsFile = Join-Path $UtilDirectory 'MediaTools.psm1'
Import-Module $UtilFile -Force
Import-Module $MediaToolsFile -Force

# Get paths from config
$processedDirectory = $Config.paths.processedDirectory
$rawDirectory = $Config.paths.rawDirectory
$extractor = $Config.paths.tools.sevenZip
$phase = $env:CURRENT_PHASE

# --- Logging Setup ---
$logDirectory = $Config.paths.logDirectory
$Logger = Initialize-ScriptLogger -LogDirectory $logDirectory -ScriptName $scriptName -Step $phase -Config $Config
$Log = $Logger.Logger

# Debug path values
& $Log "DEBUG" "processedDirectory = $processedDirectory"
& $Log "DEBUG" "rawDirectory = $rawDirectory"  
& $Log "DEBUG" "extractor = $extractor"
& $Log "DEBUG" "phase = $phase"

# Inject logger for module functions
Set-UtilsLogger -Logger $Log
Set-MediaToolsLogger -Logger $Log

& $Log "INFO" "--- Script Started: $scriptName ---"

# --- Robust Parameter Validation ---
if (-not (Test-Path -Path $processedDirectory -PathType Container)) {
    & $Log "INFO" "Output directory '$processedDirectory' does not exist. Creating it."
    try {
        New-Item -ItemType Directory -Path $processedDirectory -Force -ErrorAction Stop | Out-Null
    } catch {
        & $Log "CRITICAL" "Failed to create output directory '$processedDirectory'. Error: $_. Aborting."
        exit 1
    }
}

if ([string]::IsNullOrEmpty($rawDirectory)) {
    & $Log "CRITICAL" "rawDirectory is null or empty. Aborting."
    exit 1
}

if (-not (Test-Path -Path $rawDirectory -PathType Container)) {
    & $Log "CRITICAL" "Input directory with zip files '$rawDirectory' does not exist. Aborting."
    exit 1
}

if ([string]::IsNullOrEmpty($extractor)) {
    & $Log "CRITICAL" "extractor path is null or empty. Aborting."
    exit 1
}

if (-not (Test-Path -Path $extractor -PathType Leaf)) {
    & $Log "CRITICAL" "7-Zip executable not found at '$extractor'. Aborting."
    exit 1
}

if ($processedDirectory -like '* *') {
    & $Log "CRITICAL" "The configured output directory path for extraction ('$processedDirectory') contains spaces. This is not supported. Please use a path without spaces."
    Stop-GraphicalProgressBar
    exit 1
}

# Get all zip files in the directory.
$zipFiles = Get-ChildItem -Path $rawDirectory -recurse -Filter "*.zip" -File

if ($null -eq $zipFiles -or $zipFiles.Count -eq 0) {
    & $Log "INFO" "No .zip files found in '$rawDirectory'. Nothing to extract."
ee3e6800-8f13-410f-864f-68b59ba97c43    exit 0 # Exit gracefully
}

$currentItem = 0
$totalItems = $zipFiles.count
# Loop through each zip file and extract its contents.
foreach ($zipFile in $zipFiles) {
    $currentItem++
    $percent = if ($totalItems -gt 0) { [int](($currentItem / $totalItems) * 100) } else { 100 }

    Update-GraphicalProgressBar -SubTaskPercent $percent -SubTaskMessage  "Extracting: $($zipFile.Name)"
    try {
        # 7-Zip Arguments:
        #   x: Extract with full paths
        #   -aos: Skip Over Existing files (prevents re-extracting everything on a re-run)
        #   -o: Set Output directory (no space between -o and path)
        #   -bsp1: Redirect progress output to stdout for capture
        $7zipArgs = "x", "-aos", $zipFile.FullName, "-o$processedDirectory", "-bsp1"
        
        # Execute 7-Zip and capture all output (stdout and stderr)
        $output = & $extractor $7zipArgs 2>&1
        if ($LASTEXITCODE -ne 0) { throw "7-Zip failed with exit code $LASTEXITCODE. Output: $($output -join [System.Environment]::NewLine)" }
        & $Log "DEBUG" "Successfully extracted $($zipFile.FullName)"
    } catch {
        & $Log "ERROR" "Failed to extract '$($zipFile.FullName)'. Error: $_"
    }
}

# Copy non-archive (loose) files
& $Log "INFO" "Checking for non-archive files to copy..."
$allFiles = Get-ChildItem -Path $rawDirectory -File -Recurse
$archiveExtensions = @('.zip', '.7z', '.rar', '.tar', '.gz', '.bz2', '.xz')
$nonArchiveFiles = $allFiles | Where-Object { 
    $ext = $_.Extension.ToLower()
    $archiveExtensions -notcontains $ext
}

if ($nonArchiveFiles.Count -gt 0) {
    & $Log "INFO" "Found $($nonArchiveFiles.Count) non-archive files to copy"
    
    foreach ($file in $nonArchiveFiles) {
        try {
            # Preserve relative path structure
            $relativePath = $file.FullName.Substring($rawDirectory.Length + 1)
            $destPath = Join-Path $processedDirectory $relativePath
            $destDir = Split-Path $destPath -Parent
            
            # Create destination directory if needed
            if (!(Test-Path $destDir)) {
                New-Item -ItemType Directory -Path $destDir -Force | Out-Null
            }
            
            Copy-Item -Path $file.FullName -Destination $destPath -Force -ErrorAction Stop
            & $Log "INFO" "Copied: $relativePath"
        } catch {
            & $Log "ERROR" "Failed to copy '$($file.FullName)': $_"
        }
    }
} else {
    & $Log "INFO" "No non-archive files found to copy"
} 