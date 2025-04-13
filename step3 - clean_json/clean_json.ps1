$ErrorActionPreference = "Stop"
# Define the directory containing the zip files.
$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent

$level1_batch_file = Join-Path -Path $scriptDirectory -ChildPath 'level1_batch.txt'
$level2_batch_file = Join-Path -Path $scriptDirectory -ChildPath 'level2_batch.txt'
$level3_batch_file = Join-Path -Path $scriptDirectory -ChildPath 'level3_batch.txt'
$level5_batch_file = Join-Path -Path $scriptDirectory -ChildPath 'level5_batch.txt'

$level0_leftover_file = Join-Path -Path $scriptDirectory -ChildPath 'level0_leftover_file.txt'
$level1_leftover_file = Join-Path -Path $scriptDirectory -ChildPath 'level1_leftover_file.txt'
$level2_leftover_file = Join-Path -Path $scriptDirectory -ChildPath 'level2_leftover_file.txt'
$level3_leftover_file = Join-Path -Path $scriptDirectory -ChildPath 'level3_leftover_file.txt'
$level4_leftover_file = Join-Path -Path $scriptDirectory -ChildPath 'level4_leftover_file.txt'
$level5_leftover_file = Join-Path -Path $scriptDirectory -ChildPath 'level5_leftover_file.txt'
$level6_leftover_file = Join-Path -Path $scriptDirectory -ChildPath 'level6_leftover_file.txt'

# Generate all possible JSON suffixes dynamically
$suffixes = @("supplemental-metadata", "supplemental-metadat", "supplemental-metada", "supplemental-metad", "supplemental-meta",
    "supplemental-met", "supplemental-me", "supplemental-m", "supplemental-", "supplemental",
    "supplementa", "supplement", "supplemen", "suppleme", "supplem",
    "supple", "suppl", "supp", "sup", "su",
    "s", ".", "")

Remove-Item -Path $level1_batch_file,$level2_batch_file,$level3_batch_file,$level5_batch_file -ErrorAction SilentlyContinue
Remove-Item -Path $level0_leftover_file,$level1_leftover_file,$level2_leftover_file,$level3_leftover_file,$level4_leftover_file,$level5_leftover_file,$level6_leftover_file -ErrorAction SilentlyContinue

# --- Logging Setup ---
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)
$logDir = Join-Path $scriptDirectory "..\Logs"
$logFile = Join-Path $logDir "$scriptName.log"
$logFormat = "{0} - {1}: {2}"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

$env:DEDUPLICATOR_CONSOLE_LOG_LEVEL = $env:DEDUPLICATOR_CONSOLE_LOG_LEVEL ?? "INFO"
$env:DEDUPLICATOR_FILE_LOG_LEVEL = $env:DEDUPLICATOR_FILE_LOG_LEVEL ?? "DEBUG"
$logLevelMap = @{ "DEBUG" = 0; "INFO" = 1; "WARNING" = 2; "ERROR" = 3; "CRITICAL" = 4 }
$consoleLogLevel = $logLevelMap[$env:DEDUPLICATOR_CONSOLE_LOG_LEVEL.ToUpper()]
$fileLogLevel = $logLevelMap[$env:DEDUPLICATOR_FILE_LOG_LEVEL.ToUpper()]

function Log {
    param ([string]$Level, [string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $formatted = $logFormat -f $timestamp, $Level.ToUpper(), $Message
    $levelIndex = $logLevelMap[$Level.ToUpper()]
    if ($levelIndex -ge $consoleLogLevel) { Write-Host $formatted }
    if ($levelIndex -ge $fileLogLevel) { Add-Content -Path $logFile -Value $formatted -Encoding UTF8 }
}

function Write-JsonAtomic {
    param ([Parameter(Mandatory = $true)][object]$Data, [Parameter(Mandatory = $true)][string]$Path)
    try {
        $tempPath = "$Path.tmp"
        $json = $Data | ConvertTo-Json -Depth 10
        $json | Out-File -FilePath $tempPath -Encoding UTF8 -Force
        $null = Get-Content $tempPath -Raw | ConvertFrom-Json
        Move-Item -Path $tempPath -Destination $Path -Force
        Log "INFO" "✅ Atomic write succeeded: $Path"
    } catch {
        Log "ERROR" "❌ Atomic write failed for $Path : $_"
        if (Test-Path $tempPath) { Remove-Item $tempPath -Force -ErrorAction SilentlyContinue }
    }
}

function Sanitize_FileList {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$FilePaths
    )
    $currentItem = 0
    $totalItems = $FilePaths.count
    $temp_FilePaths = @() 
    foreach ($filePath in $FilePaths) {
        # Check if the file path is valid
        $currentItem++
        Show-ProgressBar -Current $currentItem -Total $totalItems -Message "$(Split-Path -Path $filePath -Leaf)"
        if ([string]::IsNullOrEmpty($filePath)) {
            Log "WARNING" "Invalid or non-existent file path: '$filePath'. Skipping."
            continue
        }

        # Check if the path is a drive root (e.g., "C:\")
        if (($filePath -match "^[a-zA-Z]:$") -or ($filePath -match "^[a-zA-Z]:\\$") -or ($filePath -match "^[a-zA-Z]:/$") ) {
            Log "WARNING" "Skipping drive root: '$filePath'"
            continue  # Exit the function without doing anything
        }

        # Extract the directory and file name
        $directory = Split-Path -Path $filePath -Parent
        $fileName = Split-Path -Path $filePath -Leaf

        # Sanitize the directory name

        # Check if directory is just a drive letter (e.g., "D:")
        if (($directory -match "^[a-zA-Z]:$") -or ($directory -match "^[a-zA-Z]:\\$") -or ($directory -match "^[a-zA-Z]:/$") ) {
            $sanitizedDirectoryName = $directory
            continue
        } else {
            # Trim leading/trailing spaces/tabs from each directory component
            $sanitizedDirectoryName = ($directory -replace '\\', '/') -split '/'
            $sanitizedDirectoryName = $sanitizedDirectoryName.Trim()
        }
        
        $sanitizedDirectoryName = $sanitizedDirectoryName -replace '[^\w\-\\\/]+', '_' # Replace non-alphanumeric/hyphen/slash/backslash with underscore
        $sanitizedDirectoryName = $sanitizedDirectoryName -replace '([\\\/])_+([\\\/])', '$1$2' #remove multiple underscores between slashes
        $sanitizedDirectoryName = $sanitizedDirectoryName -replace '^_+|_+([\\\/])', '$1' #remove leading or trailing underscores.
        $sanitizedDirectoryName = $sanitizedDirectoryName -replace '([\\\/])_+$', '$1' #remove trailing underscores.
        $sanitizedDirectoryName = $sanitizedDirectoryName -join '/' #remove trailing underscores.

        $newFilePath = Join-Path -Path $sanitizedDirectoryName -ChildPath $fileName
        $newFilePath = $newFilePath -replace '\\', '/'
        $temp_FilePaths += $newFilePath
    }
    return $temp_FilePaths
} 

# Create an empty array to store the results.
$level0_files = @()

# Get all zip files in the directory.
$zipFiles = Get-ChildItem -Path $zipDirectory -recurse -Filter "*.zip" -File

$currentItem = 0
$totalItems = $zipFiles.count
# Loop through each zip file.
foreach ($zipFile in $zipFiles) {
    $currentItem++
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message "Step 3 2"
    # Check if the file is a valid zip file
    try {
        [System.IO.Compression.ZipFile]::OpenRead($zipFile.FullName) | Out-Null
    } catch {
        Log "WARNING" "Skipping $($zipFile.FullName) as it is not a valid zip file."
        continue
    }

    # Open the zip file.
    $zipArchive = [System.IO.Compression.ZipFile]::OpenRead($zipFile.FullName)

    # Loop through each entry in the zip file.
    foreach ($entry in $zipArchive.Entries) {
        # Create a custom object to store the information.
        $zipContent = $entry.FullName

        # Add the object to the array.
        $level0_files += $zipContent
    }

    # Close the zip file.
    $zipArchive.Dispose()
}

# Check if any zip files were processed
if ($level0_files.Count -eq 0) {
    Log "WARNING" "No valid zip files found or no files inside zip files."
    exit 0
}

# Sanitize the file paths inside the zip files
$level0_files = Sanitize_FileList -FilePaths $level0_files

# Output the non-filtered file paths to a new file
$level0_files | Out-File -FilePath $level0_leftover_file -Encoding utf8
Log "INFO" "Wrote sanitized level 0 file list to '$level0_leftover_file'"

# Create a new collection to store updated file paths
$level1_files = @()
$currentItem = 0
$totalItems = $level0_files.count

# Loop through each file
foreach ($file in $level0_files) {
    $currentItem++
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message "Step 3 3"
    if (-not $file -match ".json$") {
        $level1_files += ,$file
    } else {
        $found = $false
        foreach ($suffix in $suffixes) {
            if ($file -match "\.$suffix\.json$") {
                $newfile = $file -replace "\.$suffix\.json$", ".json"
                "ren `"$unzipedDirectory`/$file`" `"$unzipedDirectory`/$newfile`" " | Out-File -FilePath $level1_batch_file -Append | Out-Null
                $level1_files += $newfile
                $found = $true
                break
            }
        }
        if (-not $found) {
            $level1_files += ,$file
        }
    }
}

# Output the non-filtered file paths to a new file
$level1_files | Out-File -FilePath $level1_leftover_file -Encoding utf8
Log "INFO" "Wrote sanitized level 1 file list to '$level1_leftover_file'"


# Create a new collection to store updated file paths
$level2_files = @()
$currentItem = 0
$totalItems = $level1_files.count
# Loop through each file
foreach ($file in $level1_files) {
    $currentItem++
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message "Step 3 4"

    # Check if the file name contains "-edited" or "-effects"
    if (-not($file -match ".json$") -and ($file -match "-edited" -or $file -match "-effects")) {
	 
        $newFileName = $file -replace "-edited", ""
        $newFileName = $newFileName -replace "-effects", ""
        if ($level1_files -contains "$file.json") {
            $level2_files += $file
        } else {
            if ($level1_files -contains "$newFileName.json") {
                "copy  `"$unzipedDirectory`/$file.json`" `"$unzipedDirectory`/$newFileName.json`" " | Out-File -FilePath $level2_batch_file -Append | Out-Null
                $level2_files += $file
                $level2_files += "$file.json"
            }
        }
    } else {
        # If the file is not renamed, add it to the updated collection as-is
        $level2_files += $file
    }
}

# Output the non-filtered file paths to a new file
$level2_files | Out-File -FilePath $level2_leftover_file -Encoding utf8
Log "INFO" "Wrote updated level 2 file list to '$level2_leftover_file'"

# Convert the array to a HashSet for O(1) lookups
$fileSet = @{}
$level2_files | ForEach-Object { $fileSet[$_] = $true }

$level3_pairs = @()
$level3_leftovers = @()
$currentItem = 0
$totalItems = $level2_files.count

foreach ($file in $level2_files) {
    # Skip JSON files since they are only checked as potential pairs
    if ($file -match '\.json$') {
        continue
    }
    $currentItem++
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message "Step 3 5"

    $filename = $file

    $with_parentheses = $false
    $json_file = "$filename.json"

    if ($fileSet.ContainsKey($json_file)) {
        $with_parentheses = $false
        $level3_pairs += $file, $json_file, $with_parentheses
        $fileSet.Remove($file)
        $fileSet.Remove($json_file)
        continue
    }

    $baseName = [System.IO.Path]::GetFileNameWithoutExtension($filename)
    $extension = [System.IO.Path]::GetExtension($filename)
    $directory = [System.IO.Path]::GetDirectoryName($filename)
    if ($baseName -match "\((\d+)\)$") {
        $digits = $matches[1]
        $with_parentheses = $true
        foreach ($suffix in $suffixes) {
            $newbaseName = $baseName -replace "\(\d+\)$", ""
            $json_file = "$directory/$newbaseName$extension.$suffix($digits).json"
            $json_file = $json_file | ForEach-Object { $_ -replace '\\', '/' }

            if ($fileSet.ContainsKey($json_file)) {
                $level3_pairs += $file, $json_file, $with_parentheses
                $fileSet.Remove($file)
                $fileSet.Remove($json_file)
                break
            }
        }
    }
}

$currentItem = 0
$totalItems = $level3_pairs.count
# Iterate over the array with a step of 3
for ($i = 0; $i -lt $level3_pairs.Length; $i += 3) {
    $currentItem++
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message "Step 3 6"
    $mainFilePath = $level3_pairs[$i]
    $jsonFilePath = $level3_pairs[$i + 1]
    $with_parentheses = $level3_pairs[$i + 2]

    # Extract the directory and base name of the main file
    $mainFileDirectory = Split-Path -Path $mainFilePath -Parent
    $mainFileDirectory = $mainFileDirectory -replace '\\', '/'
    $mainFileName = Split-Path -Path $mainFilePath -Leaf

    $JsonDirectory = Split-Path -Path $jsonFilePath -Parent
    $JsonDirectory = $JsonDirectory -replace '\\', '/'
    $JsonFileName = Split-Path -Path $jsonFilePath -Leaf
    $JsonbaseName = [System.IO.Path]::GetFileNameWithoutExtension($jsonFilePath)

    if ($with_parentheses -eq $true) {
        if ($JsonbaseName -match "\((\d+)\)$") {
            $digits = $matches[1]
            $no_paranthesis_baseName = $JsonbaseName -replace "\(\d+\)$", ""
            $firstDotIndex = $no_paranthesis_baseName.IndexOf(".")
            if ($firstDotIndex -ge 0) {
                $newJsonbaseName = $no_paranthesis_baseName.Insert($firstDotIndex, "($digits)")
            } else {
                $newJsonbaseName = "$no_paranthesis_baseName($digits)"
            }
            $newJsonFileName = "$newJsonbaseName.json"
            $newJsonFilePath = "$JsonDirectory/$newJsonFileName"
            "ren `"$unzipedDirectory/$jsonFilePath`" `"$unzipedDirectory/$newJsonFilePath`"" | Out-File -FilePath $level3_batch_file -Append | Out-Null
            $jsonFilePath = $newJsonFilePath
        } else {
			  
            Log "INFO" "No matching JSON file found for '$mainFilePath'"
            break
        }
    }
    # Check if the JSON file starts with the main file base name followed by a dot or is exactly the same as the main file name with .json extension
    if ($jsonFilePath -match "^$([regex]::Escape($mainFilePath))\..*\.json$" -or
        $jsonFilePath -match "^$([regex]::Escape($mainFilePath))\.json$") {
	 
        # Construct the new JSON file name by removing the extra string and redundant dot
        $newJsonFileName = "$mainFileName.json"
        $newJsonFilePath = "$mainFileDirectory/$newJsonFileName"

        if (!(Test-Path -Path $unzipedDirectory/$newJsonFilePath)) {
            "ren `"$unzipedDirectory/$jsonFilePath`" `"$unzipedDirectory/$newJsonFilePath`"" | Out-File -FilePath $level3_batch_file -Append | Out-Null
        }
    } else {
        Log "WARNING" "No matching JSON file found for '$mainFilePath'"
    }
}

$level2_files | ForEach-Object {
    if ($fileSet[$_] -eq $true) {
        $level3_leftovers += $_
    }
}

# Output the non-filtered file paths to a new file
$level3_leftovers | Out-File -FilePath $level3_leftover_file -Encoding utf8
Log "INFO" "Wrote updated level 3 file list to '$level3_leftover_file'"

# Initialize a hashtable to store files by their directory
$directoryFiles = @{}
$currentItem = 0
$totalItems = $level3_leftovers.count

# Populate the hashtable with files grouped by their directory
foreach ($file in $level3_leftovers) {
    $currentItem++
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message "Step 3 7"
    # Remove quotations from the file path
    try {
        $file = $file.Trim('"')
    } catch {
        Log "WARNING" "Error trimming file path"
    }

    $directory = Split-Path -Path $file -Parent
    if (-not $directoryFiles.ContainsKey($directory)) {
        $directoryFiles[$directory] = @()
    }
    $directoryFiles[$directory] += $file
}

# Initialize lists to store the filtered and non-filtered file paths
$level4_leftovers = @()
$level4_Junk = @()

$currentItem = 0
$totalItems = $directoryFiles.count

# Filter directories based on the presence of JSON files
foreach ($directory in $directoryFiles.Keys) {
    $currentItem++
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message "Step 3 8"
    $files = $directoryFiles[$directory]
    $containsJson = $false
    $containsNonJson = $false

    foreach ($file in $files) {
        if ($file -match "\.json$") {
            $containsJson = $true
        } else {
            $containsNonJson = $true
        }
    }

    # Only add files from directories that contain both JSON and non-JSON files
    if ($containsJson -and $containsNonJson) {
        $level4_leftovers += $files
    } else {
        $level4_Junk += $files
    }
}

# Convert the array to a HashSet for O(1) lookups
$fileSet = @{}
$level4_leftovers | ForEach-Object { $fileSet[$_] = $true }

# Initialize lists to store found and not found file paths
$level5_pairs = @()
$level5_leftovers = @()

$currentItem = 0
$totalItems = $level4_leftovers.count
# Group files by their base name (first 45 characters)
$truncNameFiles = @{}

foreach ($file in $level4_leftovers) {
    $currentItem++
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message "Step 3 9"
    $fileName = Split-Path -Path $file -Leaf
    $directory = [System.IO.Path]::GetDirectoryName($file)
    $directory = $directory -replace '\\', '/'
    $baseName = $fileName.Substring(0, [Math]::Min(43, $fileName.Length))
    $truncName = "$directory/$baseName"
    if (-not $truncNameFiles.ContainsKey($truncName)) {
        $truncNameFiles[$truncName] = @()
    }
    $truncNameFiles[$truncName] += $file
}
$currentItem = 0

$totalItems = $truncNameFiles.count
$foundFilePaths = @()
# Process each base name group
foreach ($truncName in $truncNameFiles.Keys) {
    $currentItem++
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message "Step 3 10"
    $files = $truncNameFiles[$truncName]
    $jsonFiles = $files | Where-Object { $_ -match "\.json$" }
    $nonJsonFiles = $files | Where-Object { $_ -notmatch "\.json$" }

    foreach ($jsonFile in $jsonFiles) {
        foreach ($nonJsonFile in $nonJsonFiles) {
            $Jsondirectory = [System.IO.Path]::GetDirectoryName($jsonFile)
            $NonJsondirectory = [System.IO.Path]::GetDirectoryName($nonJsonFile)
            if ($Jsondirectory -eq $NonJsondirectory) {
                $level5_pairs += $nonJsonFile
                $level5_pairs += $jsonFile
                $fileSet.Remove($nonJsonFile)
                $fileSet.Remove($jsonFile)
                $foundFilePaths += $nonJsonFile
                break
            }
        }
    }
}

$currentItem = 0
$totalItems = $level5_pairs.count
# Iterate over the array with a step of 2
for ($i = 0; $i -lt $level5_pairs.Length; $i += 2) {
    $currentItem++
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message "Step 3 11"
    $mainFilePath = $level5_pairs[$i]
    $jsonFilePath = $level5_pairs[$i + 1]

    # Extract the directory and base name of the main file
    $mainFileDirectory = Split-Path -Path $mainFilePath -Parent
    $mainFileDirectory = $mainFileDirectory -replace '\\', '/'
    $mainFileName = Split-Path -Path $mainFilePath -Leaf

    # Extract the JSON file name and base name
    $jsonFileName = Split-Path -Path $jsonFilePath -Leaf

    $mainFileBaseName = [System.IO.Path]::GetFileNameWithoutExtension($mainFileName)
    $jsonFileBaseName = [System.IO.Path]::GetFileNameWithoutExtension($jsonFileName)

    $mainFileBaseName = $mainFileBaseName -split '\.' | Select-Object -First 1
    $jsonFileBaseName = $jsonFileBaseName -split '\.' | Select-Object -First 1

    $mainFileExtension = [System.IO.Path]::GetExtension($mainFileName)

    # Determine the shorter base name length
    $mainFileBaseLength = $mainFileBaseName.Length
    $jsonFileBaseLength = $jsonFileBaseName.Length

    if ($mainFileBaseLength -lt $jsonFileBaseLength) {
        $shorterLength = $mainFileBaseLength
    } else {
        $shorterLength = $jsonFileBaseLength
    }

    # Truncate both base names to the shorter length
    $newMainFileBaseName = $mainFileBaseName.Substring(0, $shorterLength - 4)
    $newJsonFileBaseName = $jsonFileBaseName.Substring(0, $shorterLength - 4)

    # Check if the JSON file starts with the main file base name followed by a dot or is exactly the same as the main file name with .json extension
    if ( "$newMainFileBaseName" -match  "$newJsonFileBaseName" )
    {
        # Construct the new JSON file name by removing the extra string and redundant dot
        $newMainFilePath = "$mainFileDirectory/$newMainFileBaseName$mainFileExtension"
        $newJsonFilePath = "$newMainFilePath.json"

        # Write the rename command to the rename file
        "ren `"$unzipedDirectory`/$mainFilePath`" `"$unzipedDirectory`/$newMainFilePath`""  | Out-File -FilePath $level5_batch_file -Append | Out-Null
    } 
}

$level4_leftovers | ForEach-Object {
    if ($fileSet[$_] -eq $true) {
        $level5_leftovers += $_
    }
}

# Output the non-filtered file paths to a new file
$level5_leftovers | Out-File -FilePath $level5_leftover_file -Encoding utf8
Log "INFO" "Wrote updated level 5 file list to '$level5_leftover_file'"

$directoryFiles = @{}
$currentItem = 0
$totalItems = $level5_leftovers.count

# Populate the hashtable with files grouped by their directory
foreach ($file in $level5_leftovers) {
    $currentItem++
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message "Step 3 12"
    # Remove quotations from the file path
    $file = $file.Trim('"')
    $directory = Split-Path -Path $file -Parent
    if (-not $directoryFiles.ContainsKey($directory)) {
        $directoryFiles[$directory] = @()
    }
    $directoryFiles[$directory] += $file
}

# Initialize lists to store the filtered and non-filtered file paths
$level6_junk_files = @()
$level6_leftover_files = @()

$currentItem = 0
$totalItems = $directoryFiles.count

# Filter directories based on the presence of JSON files
foreach ($directory in $directoryFiles.Keys) {
    $currentItem++
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message "Step 3 13"
    $files = $directoryFiles[$directory]
    $containsJson = $false
    $containsNonJson = $false

    foreach ($file in $files) {
        if ($file -match "\.json$") {
            $containsJson = $true
        } else {
            $containsNonJson = $true
        }
    }

    # Only add files from directories that contain both JSON and non-JSON files
    if ($containsJson -and $containsNonJson) {
        $level6_leftover_files += $files
    } else {
        $level6_junk_files += $files
    }
}

# Output the non-filtered file paths to a new file
$level6_leftover_files | Out-File -FilePath $level6_leftover_file -Encoding utf8
Log "INFO" "Wrote updated level 6 file list to '$level6_leftover_file'"

