param(
    [Parameter(Mandatory=$true)]
    $Config
)

# --- Path Setup ---
$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

# Get paths from config
$processedDirectory = $Config.paths.processedDirectory
$outputDirectory = $Config.paths.resultsDirectory
$phase = $env:CURRENT_PHASE

# Outputs Directory
$metaPath = Join-Path $outputDirectory "Consolidate_Meta_Results.json"

# Utils Directory
$UtilDirectory = Join-Path $scriptDirectory "..\Utils"
$UtilFile = Join-Path $UtilDirectory "Utils.psm1"
$MediaToolsFile = Join-Path $UtilDirectory 'MediaTools.psm1'
Import-Module $UtilFile -Force
Import-Module $MediaToolsFile -Force

# --- Logging Setup ---
$logDirectory = $Config.paths.logDirectory
$Logger = Initialize-ScriptLogger -LogDirectory $logDirectory -ScriptName $scriptName -Step $phase -Config $Config
$Log = $Logger.Logger

# Inject logger for module functions
Set-UtilsLogger -Logger $Log
Set-MediaToolsLogger -Logger $Log

& $Log "INFO" "--- Script Started: $scriptName ---"

# Create hashtable to store results
$metadataMap = @{}

# Step 1: Collect all JSON files
$jsonFiles = Get-ChildItem -Path $processedDirectory -Recurse -Filter "*.json" -File
$total = $jsonFiles.Count
$current = 0

if ($total -eq 0) {
    & $Log "INFO" "No JSON files found to process. Exiting."
    exit 0
}

foreach ($jsonFile in $jsonFiles) {
    $current++
    $percent = if ($total -gt 0) { [int](($current / $total) * 100) } else { 100 }
    # Update only the second-level progress bar with this step's specific progress
    Update-GraphicalProgressBar -SubTaskPercent $percent -SubTaskMessage "Processing JSON: $($jsonFile.Name)"

    try {
        $jsonContent = Get-Content -Path $jsonFile.FullName -Raw | ConvertFrom-Json
        $title = $jsonContent.title

        # A valid media JSON has a single, non-empty string for a title.
        # Album metadata JSONs might have an array, be empty, or have no title at all.
        if ($null -eq $title -or $title -isnot [string] -or [string]::IsNullOrWhiteSpace($title)) {
            & $Log "INFO" "Skipping non-media JSON '$($jsonFile.FullName)' (title is missing, not a string, or empty)."
            if ($jsonFile.FullName -like "*.json") {
                Remove-Item $jsonFile.FullName -Force
                & $Log "DEBUG" "Deleted non-media JSON file: $($jsonFile.FullName)"
            } else {
                & $Log "ERROR" "SAFETY CHECK: Attempted to delete non-JSON file: $($jsonFile.FullName)"
            }
            continue
        }

        # --- Key Improvement: Find both original and edited files for this JSON ---
        $originalMediaPath = Join-Path $jsonFile.DirectoryName $title
        $baseName = [System.IO.Path]::GetFileNameWithoutExtension($title)
        $extension = [System.IO.Path]::GetExtension($title)
        $editedMediaPath = Join-Path $jsonFile.DirectoryName "$($baseName)-edited$($extension)"

        $mediaPathsToUpdate = @()
        if (Test-Path $originalMediaPath -PathType Leaf) { $mediaPathsToUpdate += $originalMediaPath }
        if (Test-Path $editedMediaPath -PathType Leaf) { $mediaPathsToUpdate += $editedMediaPath }

        if ($mediaPathsToUpdate.Count -eq 0) {
            & $Log "INFO" "Orphaned JSON: Media file '$title' not found for '$($jsonFile.FullName)'"
            if ($jsonFile.FullName -like "*.json") {
                Remove-Item $jsonFile.FullName -Force
                & $Log "DEBUG" "Deleted orphaned JSON file: $($jsonFile.FullName)"
            } else {
                & $Log "ERROR" "SAFETY CHECK: Attempted to delete non-JSON file: $($jsonFile.FullName)"
            }
            continue
        }

        foreach ($mediaPath in $mediaPathsToUpdate) {
            $normalizedPath = ConvertTo-StandardPath -Path $mediaPath
            if (-not $metadataMap.ContainsKey($normalizedPath)) {
                $metadataMap[$normalizedPath] = New-DefaultMetadataObject -filepath $normalizedPath
            }
            # Add metadata from the JSON file
            $metadataMap[$normalizedPath].json += $jsonContent
        }
        # Delete processed JSON
        if ($jsonFile.FullName -like "*.json") {
            Remove-Item -Path $jsonFile.FullName -Force
            & $Log "DEBUG" "Deleted processed JSON file: $($jsonFile.FullName)"
        } else {
            & $Log "ERROR" "SAFETY CHECK: Attempted to delete non-JSON file: $($jsonFile.FullName)"
        }
    } catch {
        & $Log "ERROR" "Failed to process '$($jsonFile.FullName)': $($_.Exception.Message)"
    }
}

# Output final JSON
try {
    # Use the robust atomic write function to prevent data corruption.
    Write-JsonAtomic -Data $metadataMap -Path $metaPath
} catch {
    & $Log "CRITICAL" "Failed to save the final JSON map to '$metaPath'. Error: $($_.Exception.Message)"
    exit 1
}

Write-Host ""
& $Log "INFO" "--- Script Finished: $scriptName ---"