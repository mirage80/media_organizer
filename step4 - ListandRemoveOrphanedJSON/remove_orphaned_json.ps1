# Define the output file path.
$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$outputFile = Join-Path -Path $scriptDirectory -ChildPath 'orphaned_json_files.txt'

# Create an empty array to store the list of orphaned JSON files.
$orphanedJsonFiles = @()

# Get all JSON files in the directory.
$jsonFiles = Get-ChildItem -Path $unzipedDirectory -Recurse -Filter "*.json" -File

$currentItem = 0
$totalItems = $jsonFiles.count

# Loop through each JSON file.
foreach ($jsonFile in $jsonFiles) {
    $currentItem++
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message "Remove Orphan Json"
    # Extract the base name of the JSON file (without the .json extension).
    $sourceFileName = $jsonFile.BaseName

    # Check if the corresponding JPG or MP4 file exists.
    $Exists = Test-Path -Path (Join-Path -Path $jsonFile.DirectoryName -ChildPath $sourceFileName)

    # If neither the JPG nor the MP4 file exists, add the JSON file to the array.
    if (-not $Exists ) {
   #     Write-Host "JSON file without corresponding JPG or MP4: $($jsonFile.FullName)"
        $orphanedJsonFiles += $jsonFile.FullName
    }
}

# Write the list of orphaned JSON files to the output file.
$orphanedJsonFiles | Out-File -FilePath $outputFile -Encoding UTF8

Write-Host "Script completed. List of orphaned JSON files written to: $outputFile"
