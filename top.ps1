# Verbosity levels:
# 0 - Errors only
# 1 - Warnings and errors
# 2 - Detailed logs

$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$7zip = 'C:\Program Files\7-Zip\7z.exe'
$ExifToolPath = "'C:\Program Files\exiftools\exiftool.exe'"
$verbosity = 0

$zipDirectory = 'D:'
$unzipedDirectory = 'E:'
$logger = 5

function Show-ProgressBar {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Current,

        [Parameter(Mandatory = $true)]
        [int]$Total,

        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    $percent = [math]::Round(($Current / $Total) * 100)
    $screenWidth = $Host.UI.RawUI.WindowSize.Width - 30 # Adjust for message and percentage display
    $barLength = [math]::Min($screenWidth, 80) # Limit to 80 characters, or screen width, whichever is smaller
    $filledLength = [math]::Round(($barLength * $percent) / 100)
    $emptyLength = $barLength - $filledLength

    $filledBar = ('=' * $filledLength)
    $emptyBar = (' ' * $emptyLength)

    Write-Host -NoNewline "$Message [$filledBar$emptyBar] $percent% ($Current/$Total)`r"
}

# Function to run a Python script with error handling
function Run-PythonScript {
    param(
        [string]$ScriptPath,
        [string]$Arguments
    )

    try {
        & "python3.13.exe" "$ScriptPath" $Arguments
    } catch {
        Write-Error "Error running Python script '$ScriptPath': $_"
        exit 1 # Exit with an error code
    }
}

<# function Sanitize-DirectoryName {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DirectoryPath
    )

    # Check if the path is a drive root (e.g., "C:\")
    if ($DirectoryPath -match "^[a-zA-Z]:$") {
        return  # Exit the function without doing anything
    }
    

    $originalName = (Get-Item -Path $DirectoryPath).Name
    $originalName = $originalName.Trim()    
    $sanitizedName = $originalName -replace '[^\w\-]+', '_' # Replace non-alphanumeric/hyphen with underscore
    $sanitizedName = $sanitizedName -replace '^_|_$','' #remove leading or trailing underscores.

    if ($originalName -ne $sanitizedName) {
        $newPath = Join-Path -Path (Split-Path -Path $DirectoryPath) -ChildPath $sanitizedName

        try {
            Rename-Item -Path $DirectoryPath -NewName $sanitizedName -Force
            Write-Host "Renamed '$originalName' to '$sanitizedName'"
        } catch {
            Write-Warning "Failed to rename '$originalName': $_"
        }
    }
}

function Sanitize-DirectoriesRecursively {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RootDirectory
    )

    if (-not (Test-Path -Path $RootDirectory -PathType Container)) {
        Write-Error "Root directory '$RootDirectory' does not exist."
        return
    }

    $directories = Get-ChildItem -Path $RootDirectory -Directory -Recurse

    foreach ($directory in $directories) {
        Sanitize-DirectoryName -DirectoryPath $directory.FullName
    }
    Sanitize-DirectoryName -DirectoryPath $RootDirectory #sanitize the root directory also.
}


#count 1
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$scriptDirectory/log_step_$logger.txt"
$logger++

# step 1 - Extract Zip Files
write-host "step1 - Extract Zip Files"

# Create an empty array to store the results.
$zipContents = @()

# Get all zip files in the directory.
$zipFiles = Get-ChildItem -Path $zipDirectory -recurse -Filter "*.zip" -File

$currentItem = 0
$totalItems = $zipFiles.count
# Loop through each zip file and extract its contents.
foreach ($zipFile in $zipFiles) {
    # Extract the contents of the zip file to the temporary directory.
    $currentItem++
    Show-ProgressBar -Current $currentItem -Total $totalItems -Message "$zipFile"
    & $7zip x -aos "$zipFile"  -o"$unzipedDirectory" >$null 2>&1
} 

#count 2
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$scriptDirectory/log_step_$logger.txt"
$logger++

# step 2 - Sanetize the names
Write-Host -NoNewline "`n"
write-host "`nstep2 - Sanetize the names"
Sanitize-DirectoriesRecursively -RootDirectory $unzipedDirectory

#step3 - clean json names json files
write-host "step3 - clean json names json files"
& "$scriptDirectory\step3 - clean_json\clean_json.ps1"

# Define the directory containing the rename files
$batchScriptDirectory = "$scriptDirectory\step3 - clean_json"

# List of rename files to process
$batchFiles = @(
    "level1_batch.txt",
    "level2_batch.txt",
    "level3_batch.txt",
    "level5_batch.txt"
)

$passed = 0
$failed = 0

# Loop through each rename file
foreach ($batchFile in $batchFiles) {
    # Construct the full path to the rename file
    $filePath = Join-Path -Path $batchScriptDirectory -ChildPath $batchFile


    # Check if the file exists
    if (!(Test-Path -Path $filePath -PathType Leaf)) {
        Write-Warning "File '$filePath' not found. Skipping..."
        continue
    }

    $contents = Get-Content -Path $filePath
    $currentItem = 0
    $totalItems = len($contents)

    # Read the file line by line and execute the commands
    Get-Content -Path $filePath | ForEach-Object {
        $currentItem++
        Show-ProgressBar -Current $currentItem -Total $totalItems -Message "$batchFile"

        $command = $_.Trim() # Remove any leading or trailing whitespace
		if ($command -match "(ren)\s+'(.*?)'\s+'(.*?)'") 
		{
			$src = $Matches[2]
			$dest = $Matches[3]
			if (Test-Path -Path $dest) {
				Remove-Item -Path $src -Force
				continue
			}
		}
        $command = $command -replace '\"', "'"
        # Execute the command if it starts with "ren"
        try {
            Invoke-Expression $command
            $passed++
        } catch {
            # Write-warning "Failed to execute: $command. Error: $_"
            $failed++
        }
    }
}

#count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$scriptDirectory/log_step_$logger.txt"
$logger++

#step 4 - remove orphaned json files
write-host "step4 - remove orphaned json files"
& "$scriptDirectory\step4 - ListandRemoveOrphanedJSON\remove_orphaned_json.ps1"
Get-Content -Path "$scriptDirectory\step4 - ListandRemoveOrphanedJSON\orphaned_json_files.txt" | ForEach-Object {
    $file = $_.Trim() # Remove any leading or trailing whitespace

    # Check if the file exists before attempting to delete it
    if (Test-Path -Path "$file" -PathType Leaf) {
        try {
            # Delete the file
            Remove-Item -Path "$file" -Force
        } catch {
            Write-Warning "Failed to delete '$file': $_"
        }
    } else {
        Write-Warning "File not found: $file"
    }
}

#count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$scriptDirectory/log_step_$logger.txt"
$logger++

# step 5 - use converter to change everything to mp4 & jpg
write-host "step5 - use converter to change everything to mp4 & jpg"
& "$scriptDirectory\step5 - converter\converter.ps1"

#>

#count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$logger.txt"
$logger++

#step 6 use step6 - Consolidate_Meta to combine time stamps
write-host "step6 use 6 - Consolidate_Meta to combine time stamps"
& "$scriptDirectory\step6 - Consolidate_Meta-parrallel\6 - Consolidate_Meta.ps1"
$logger = 5

<# #count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$scriptDirectory/log_step_$logger.txt"
$logger++

#step 7 - $RECYCLE.BIN
write-host "Step 7 RECYCLE.BIN"
$RecycleBinPath = Join-Path -Path $unzipedDirectory -ChildPath '$RECYCLE.BIN'
# Ensure the Recycle Bin path exists before attempting to change attributes
if (Test-Path -Path $RecycleBinPath -PathType Container) {
    attrib -H -R -S -A 'e:\$RECYCLE.BIN'
    Remove-Item -Path (Join-Path -Path $RecycleBinPath -ChildPath "*") -Recurse -Force
}

#count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$scriptDirectory/log_step_$logger.txt"
$logger++

#step 8-1 - Hash and Group Possible Video Duplicates
write-host "Step 8-1 Hash AND Group Possible Video Duplicates to extract groups"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step8 - HashAndGroup\HashANDGroupPossibleVideoDuplicates.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$unzipedDirectory\"

#step 8-2 - Hash and Group Possible Image Duplicates
write-host "Step 8-2 Hash AND Group Possible Image Duplicates to extract groups"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step8 - HashAndGroup\HashANDGroupPossibleImageDuplicates.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$unzipedDirepctory\"

#count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$scriptDirectory/log_step_$logger.txt"
$logger++

#step 9-1 Remove Exact Video Duplicate
write-host "step 9-1 Remove Exact Video Duplicate"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step9 - RemoveExactDuplicates\RemoveExactVideoDuplicate.py'
Run-PythonScript -ScriptPath $pythonScriptPath

#step 9-2 Remove Exact Image Duplicate
write-host "step 9-2 Remove Exact Image Duplicate"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step9 - RemoveExactDuplicates\RemoveExactImageDuplicate.py'
Run-PythonScript -ScriptPath $pythonScriptPath

#count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$scriptDirectory/log_step_$logger.txt"
$logger++

#step 10-1 Remove Exact Video Duplicate
write-host "step 10-1 Show AND Remove Duplicate Video"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step10 - ShowANDRemoveDuplicate\ShowANDRemoveDuplicateVideo.py'
Run-PythonScript -ScriptPath $pythonScriptPath

#step 10-2 Remove Exact Image Duplicate
write-host "step 10-1 Show AND Remove Duplicate Image"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step10 - ShowANDRemoveDuplicate\ShowANDRemoveDuplicateImage.py'
Run-PythonScript -ScriptPath $pythonScriptPath

#count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$scriptDirectory/log_step_$logger.txt"
$logger++

#step 11-1 Remove Junk Video
write-host "step 11-1 use RemoveJunkVideo.py to remove junk Videos"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step11 - RemoveJunk\RemoveJunkVideo.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$unzipedDirectory\"

#step 11-1 Remove Junk Image 
write-host "step 11-2 use RemoveJunkImage.py to remove junk Videos"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step11 - RemoveJunk\RemoveJunkImage.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$unzipedDirectory\"

#count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$scriptDirectory/log_step_$logger.txt"
$logger++

#step 12 Categorization 
write-host "step 12 use Categorize.ps1 to categorize files based on the availability of meta data"
& "$scriptDirectory\step12 - Categorization\Categorize.ps1"


 #>