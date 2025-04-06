
# Define the path to the input file containing the list of files to search for
$inputFilePath = Join-Path -Path $PSScriptRoot -ChildPath "list_of_files.txt"

# Define the output file path
$outputFilePath = Join-Path -Path $PSScriptRoot -ChildPath "output_file.txt"

# Define the output directory for extracted files
$outputDirectory = Join-Path -Path $PSScriptRoot -ChildPath "Results"

# Define the path to the directory containing the zip files
$zipDirectory = "D:"

# Read the list of files to search for from the input file
$filesToSearchFor = Get-Content -Path $inputFilePath

# Get all zip files from the specified directory
$zipFiles = Get-ChildItem -Path $zipDirectory -recurse -Filter "*.zip" -File

# Clear the output file if it exists
if (Test-Path -Path $outputFilePath) {
    Clear-Content -Path $outputFilePath
}

# Create the output directory if it does not exist
if (-not (Test-Path -Path $outputDirectory)) {
    New-Item -Path $outputDirectory -ItemType Directory | Out-Null
}

# Function to sanitize file names
function Sanitize-FileName {
    param (
        [string]$fileName
    )
    $invalidChars = [System.IO.Path]::GetInvalidFileNameChars()
    foreach ($char in $invalidChars) {
        $fileName = $fileName -replace [regex]::Escape($char), '_'
    }
    return $fileName
}

# Function to search for files inside a zip file and extract them
function Search-And-ExtractFilesInZip {
    param (
        [string]$zipFilePath,
        [array]$filesToSearchFor,
        [string]$outputDirectory
    )

    try {
        # Open the zip file
        $zip = [System.IO.Compression.ZipFile]::OpenRead($zipFilePath)

        # Search for the files inside the zip archive
        foreach ($fileToSearch in $filesToSearchFor) {
            # Replace backslashes with forward slashes in the search string
            $fileToSearch = $fileToSearch -replace '\\', '/'
            $foundEntries = $zip.Entries | Where-Object { $_.FullName -like "*$fileToSearch*" }
            foreach ($entry in $foundEntries) {
                $relativePath = $entry.FullName
                $sanitizedFileName = Sanitize-FileName -fileName (Split-Path -Leaf $relativePath)
                $sanitizedRelativePath = Join-Path -Path (Split-Path -Parent $relativePath) -ChildPath $sanitizedFileName
                $destinationPath = Join-Path -Path $outputDirectory -ChildPath $sanitizedRelativePath
                $destinationDir = Split-Path -Path $destinationPath -Parent

                # Create the destination directory if it does not exist
                if (-not (Test-Path -Path $destinationDir)) {
                    New-Item -Path $destinationDir -ItemType Directory | Out-Null
                }

                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $destinationPath, $true)
                Add-Content -Path $outputFilePath -Value "$($zipFilePath): $($entry.FullName) -> $destinationPath"
            }
        }

        # Close the zip file
        $zip.Dispose()
    }
    catch {
        Write-Warning "Failed to process zip file: $zipFilePath - $($_.Exception.Message)"
    }
}

# Search for the files inside each zip file and extract them
foreach ($zipFile in $zipFiles) {
    Search-And-ExtractFilesInZip -zipFilePath $zipFile.FullName -filesToSearchFor $filesToSearchFor -outputDirectory $outputDirectory
}

Write-Output "Search and extraction completed. Results are listed in $outputFilePath."