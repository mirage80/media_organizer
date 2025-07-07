param(
    [Parameter(Mandatory=$true)]
    [string]$unzippedDirectory,
    [string]$step
)

$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

# Outputs Directory
$OutputDirectory = Join-Path $scriptDirectory "..\Outputs"
$finalOutputFile = Join-Path -Path $OutputDirectory -ChildPath 'Consolidate_Meta_Results.json'

# Utils Directory
$UtilDirectory = Join-Path $scriptDirectory "..\Utils"
$UtilFile = Join-Path $UtilDirectory "Utils.psm1"
Import-Module $UtilFile -Force

# Logging Setup
$childLogFilePath = Join-Path "$scriptDirectory\..\Logs" -ChildPath $("Step_$step" + "_" + "$scriptName.log")
$logLevelMap = $env:LOG_LEVEL_MAP_JSON | ConvertFrom-Json -AsHashtable
$consoleLogLevel = $logLevelMap[$env:DEDUPLICATOR_CONSOLE_LOG_LEVEL.ToUpper()]
$fileLogLevel    = $logLevelMap[$env:DEDUPLICATOR_FILE_LOG_LEVEL.ToUpper()]
$Log = {
    param([string]$Level, [string]$Message)
    Write-Log -Level $Level -Message $Message -LogFilePath $childLogFilePath -ConsoleLogLevel $consoleLogLevel -FileLogLevel $fileLogLevel -LogLevelMap $logLevelMap
}

& $Log "INFO" "--- Script Started: $scriptName ---"
& $Log "INFO" "Mapping Google Photos JSON data to media files."

# Create hashtable to store results
$metadataMap = @{}

# Step 1: Collect all JSON files
$jsonFiles = Get-ChildItem -Path $unzippedDirectory -Recurse -Filter "*.json" -File
$total = $jsonFiles.Count
$current = 0

if ($total -eq 0) {
    & $Log "INFO" "No JSON files found to process. Exiting."
    exit 0
}

foreach ($jsonFile in $jsonFiles) {
    $current++
    Show-ProgressBar -Current $current -Total $total -Message "Step $step: Processing JSON $($jsonFile.Name)"

    try {
        $jsonContent = Get-Content -Path $jsonFile.FullName -Raw | ConvertFrom-Json
        $title = $jsonContent.title

        if ([string]::IsNullOrWhiteSpace($title)) {
            & $Log "WARNING" "Skipping '$($jsonFile.FullName)' — missing title field."
            Remove-Item $jsonFile.FullName -Force
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
            & $Log "WARNING" "Orphaned JSON: Media file '$title' not found for '$($jsonFile.FullName)'"
            Remove-Item $jsonFile.FullName -Force
            continue
        }

        foreach ($mediaPath in $mediaPathsToUpdate) {
            $normalizedPath = $mediaPath -replace '\\', '/'
            if ($metadataMap.ContainsKey($normalizedPath)) {
                & $Log "WARNING" "Conflict: Media file '$normalizedPath' is being updated by a new JSON file. Current: '$($jsonFile.FullName)', Previous: '$($metadataMap[$normalizedPath].source_json_files -join ', ')'"
            }

            if (-not $metadataMap.ContainsKey($normalizedPath)) {
                $metadataMap[$normalizedPath] = @{
                    google_photoTakenTime_timestamp = $null
                    google_geoData = $null
                    google_description = $null
                    google_creationTime_timestamp = $null
                    google_modificationTime_timestamp = $null
                    google_favorited = $null
                    google_labels = @()
                    google_cameraMake = $null
                    google_cameraModel = $null
                    google_otherFields = @{}
                    source_json_files = @()
                }
            }

            $entry = $metadataMap[$normalizedPath]
            $entry.source_json_files += $jsonFile.FullName

            if ($jsonContent.photoTakenTime) { $entry.google_photoTakenTime_timestamp = $jsonContent.photoTakenTime.timestamp }
            if ($jsonContent.geoData.latitude -and $jsonContent.geoData.longitude) { $entry.google_geoData = $jsonContent.geoData }
            if ($jsonContent.description) { $entry.google_description = $jsonContent.description }
            if ($jsonContent.creationTime) { $entry.google_creationTime_timestamp = $jsonContent.creationTime.timestamp }
            if ($jsonContent.modificationTime) { $entry.google_modificationTime_timestamp = $jsonContent.modificationTime.timestamp }
            if ($null -ne $jsonContent.favorited) { $entry.google_favorited = [bool]$jsonContent.favorited }
            if ($jsonContent.labels) { $entry.google_labels += $jsonContent.labels }
            if ($jsonContent.cameraMake) { $entry.google_cameraMake = $jsonContent.cameraMake }
            if ($jsonContent.cameraModel) { $entry.google_cameraModel = $jsonContent.cameraModel }

            # Store unknown fields for audit
            $knownKeys = "title", "description", "creationTime", "modificationTime", "geoData", "photoTakenTime", "favorited", "labels", "cameraMake", "cameraModel"
            foreach ($key in $jsonContent.PSObject.Properties.Name) {
                if ($key -notin $knownKeys) {
                    $entry.google_otherFields[$key] = $jsonContent.$key
                }
            }
        }
        # Delete processed JSON
        Remove-Item -Path $jsonFile.FullName -Force
    } catch {
        & $Log "ERROR" "Failed to process '$($jsonFile.FullName)': $($_.Exception.Message)"
    }
}

# Output final JSON
try {
    $metadataMap | ConvertTo-Json -Depth 8 | Out-File -FilePath $finalOutputFile -Encoding utf8
    & $Log "INFO" "Saved Google metadata map to '$finalOutputFile' with $($metadataMap.Count) media entries."
} catch {
    & $Log "CRITICAL" "Failed to save the final JSON map to '$finalOutputFile'. Error: $($_.Exception.Message)"
    exit 1
}

Write-Host ""
& $Log "INFO" "--- Script Finished: $scriptName ---"