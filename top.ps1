# Verbosity levels:
# 0 - Errors only
# 1 - Warnings and errors
# 2 - Detailed logs

$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$7zip = 'C:\Program Files\7-Zip\7z.exe'
$ExifToolPath = "'C:\Program Files\exiftools\exiftool.exe'"
$magickPath = "C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe"  # Update this path if needed
$ffmpeg = "ffmpeg.exe"

$DEDUPLICATOR_CONSOLE_LOG_LEVEL = "INFO"
$DEDUPLICATOR_FILE_LOG_LEVEL = "DEBUG"

$zipDirectory = 'D:'
$unzipedDirectory = 'E:'
$logger = 8

if (-not (Test-Path $7zip)) {
    Log "ERROR" "7-Zip not found at $7zip. Aborting."
    exit 1
}

if (-not (Test-Path $ExifToolPath)) {
    Log "ERROR" "Exiftools not found at $ExifToolPath. Aborting."
    exit 1
}

if (-not (Test-Path $magickPath)) {
    Log "ERROR" "magik not found at $magickPath. Aborting."
    exit 1
}

if (-not (Test-Path $ffmpeg)) {
    Log "ERROR" "ffmpeg not found at $ffmpeg. Aborting."
    exit 1
}


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

# --- Logging Setup ---
$logDir = Join-Path $scriptDirectory "Logs"
$logFilePath = Join-Path $logDir "main_pipeline.log"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$logLevelMap = @{
    "DEBUG"    = 0
    "INFO"     = 1
    "WARNING"  = 2
    "ERROR"    = 3
}
$env:DEDUPLICATOR_CONSOLE_LOG_LEVEL = $env:DEDUPLICATOR_CONSOLE_LOG_LEVEL ?? "INFO"
$env:DEDUPLICATOR_FILE_LOG_LEVEL    = $env:DEDUPLICATOR_FILE_LOG_LEVEL    ?? "DEBUG"
$consoleLogLevel = $logLevelMap[$env:DEDUPLICATOR_CONSOLE_LOG_LEVEL.ToUpper()]
$fileLogLevel = $logLevelMap[$env:DEDUPLICATOR_FILE_LOG_LEVEL.ToUpper()]

function Log {
    param (
        [string]$Level,
        [string]$Message
    )
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $formatted = "$timestamp - $Level - $Message"
    $levelIndex = $logLevelMap[$Level.ToUpper()]
    
    if ($levelIndex -ge $consoleLogLevel) {
        Write-Host $formatted
    }
    if ($levelIndex -ge $fileLogLevel) {
        Add-Content -Path $logFilePath -Value $formatted -Encoding UTF8
    }
}

# Add this atomic JSON write function near the top of your script (after logging setup)
function Write-JsonAtomic {
    param (
        [Parameter(Mandatory = $true)][object]$Data,
        [Parameter(Mandatory = $true)][string]$Path
    )

    try {
        $tempPath = "$Path.tmp"
        $json = $Data | ConvertTo-Json -Depth 10
        $json | Out-File -FilePath $tempPath -Encoding UTF8 -Force

        # Validate JSON before replacing
        $null = Get-Content $tempPath -Raw | ConvertFrom-Json

        Move-Item -Path $tempPath -Destination $Path -Force
        Log "INFO" "✅ Atomic write succeeded: $Path"
    } catch {
        Log "ERROR" "❌ Atomic write failed for $Path: $_"
        if (Test-Path $tempPath) {
            Remove-Item $tempPath -Force -ErrorAction SilentlyContinue
        }
    }
}

# Function to run a Python script with error handling
function Run-PythonScript {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath,

        [string]$Arguments
    )

    try {
        if ([string]::IsNullOrWhiteSpace($Arguments)) {
            & "python3.13.exe" "$ScriptPath"
        } else {
            & "python3.13.exe" "$ScriptPath" $Arguments
        }
    } catch {
        Log "ERROR" "Error running Python script '$ScriptPath': $_"
        exit 1
    }
}

 function Sanitize-DirectoryName {
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
            Log "INFO" "Renamed '$originalName' to '$sanitizedName'"
        } catch {
            Log "WARNING" "Failed to rename '$originalName': $_"
        }
    }
}

function Sanitize-DirectoriesRecursively {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RootDirectory
    )

    if (-not (Test-Path -Path $RootDirectory -PathType Container)) {
        Log "ERROR" "Root directory '$RootDirectory' does not exist."
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
Log "INFO" "step1 - Extract Zip Files"

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
	& "$7zip" x -aos "$zipFile" "-o$unzipedDirectory" | Out-Null
} 

#count 2
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$scriptDirectory/log_step_$logger.txt"
$logger++

# step 2 - Sanetize the names
Write-Host -NoNewline "`n"
Log "INFO" "step2 - Sanetize the names"
Sanitize-DirectoriesRecursively -RootDirectory $unzipedDirectory

#step3 - clean json names json files
Log "INFO" "step3 - clean json names json files"
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
        Log "WARNING" "File '$filePath' not found. Skipping..."
        continue
    }

    $contents = Get-Content -Path $filePath
    $currentItem = 0
	$totalItems = $contents.Count

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
            Log "WARNING" "Failed to execute: $command. Error: $_"
            $failed++
        }
    }
}

#count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$scriptDirectory/log_step_$logger.txt"
$logger++

#step 4 - remove orphaned json files
Log "INFO" "step4 - remove orphaned json files"
& "$scriptDirectory\step4 - ListandRemoveOrphanedJSON\remove_orphaned_json.ps1"
Get-Content -Path "$scriptDirectory\step4 - ListandRemoveOrphanedJSON\orphaned_json_files.txt" | ForEach-Object {
    $file = $_.Trim() # Remove any leading or trailing whitespace

    # Check if the file exists before attempting to delete it
    if (Test-Path -Path "$file" -PathType Leaf) {
        try {
            # Delete the file
            Remove-Item -Path "$file" -Force
        } catch {
            Log "WARNING" "Failed to delete '$file': $_"
        }
    } else {
        Log "WARNING" "File not found: $file"
    }
}

#count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$scriptDirectory/log_step_$logger.txt"
$logger++

# step 5 - use converter to change everything to mp4 & jpg
Log "INFO" "step5 - use converter to change everything to mp4 & jpg"
& "$scriptDirectory\step5 - converter\converter.ps1"


#count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$scriptDirectory/log_step_$logger.txt"
$logger++

#step 6 use step6 - Consolidate_Meta to combine time stamps
Log "INFO" "step6 use 6 - Consolidate_Meta to combine time stamps"
& "$scriptDirectory\step6 - Consolidate_Meta\Consolidate_Meta.ps1"

 #count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$scriptDirectory/log_step_$logger.txt"
$logger++

#step 7 - $RECYCLE.BIN
Log "INFO" "Step 7 RECYCLE.BIN"
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
Log "INFO" "Step 8-1 Hash AND Group Possible Video Duplicates to extract groups"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step8 - HashAndGroup\HashANDGroupPossibleVideoDuplicates.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$unzipedDirectory\"

#step 8-2 - Hash and Group Possible Image Duplicates
Log "INFO" "Step 8-2 Hash AND Group Possible Image Duplicates to extract groups"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step8 - HashAndGroup\HashANDGroupPossibleImageDuplicates.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$unzipedDirectory\"

#count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$scriptDirectory/log_step_$logger.txt"
$logger++

#step 9-1 Remove Exact Video Duplicate
Log "INFO" "step 9-1 Remove Exact Video Duplicate"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step9 - RemoveExactDuplicates\RemoveExactVideoDuplicate.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments '--dry-run'

#step 9-2 Remove Exact Image Duplicate
Log "INFO" "step 9-2 Remove Exact Image Duplicate"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step9 - RemoveExactDuplicates\RemoveExactImageDuplicate.py'
Run-PythonScript -ScriptPath $pythonScriptPath
#count

$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$scriptDirectory/log_step_$logger.txt"
$logger++

#step 10-1 Show AND Remove Duplicate Video
Log "INFO" "step 10-1 Show AND Remove Duplicate Video"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step10 - ShowANDRemoveDuplicate\ShowANDRemoveDuplicateVideo.py'
Run-PythonScript -ScriptPath $pythonScriptPath

#step 10-2 Show AND Remove Duplicate Image
Log "INFO" "step 10-1 Show AND Remove Duplicate Image"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step10 - ShowANDRemoveDuplicate\ShowANDRemoveDuplicateImage.py'
Run-PythonScript -ScriptPath $pythonScriptPath

#count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$scriptDirectory/log_step_$logger.txt"
$logger++

#step 11-1 Remove Junk Video
Log "INFO" "step 11-1 use RemoveJunkVideo.py to remove junk Videos"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step11 - RemoveJunk\RemoveJunkVideo.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$unzipedDirectory\"

#step 11-2 Remove Junk Image 
Log "INFO" "step 11-2 use RemoveJunkImage.py to remove junk Videos"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step11 - RemoveJunk\RemoveJunkImage.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$unzipedDirectory\"

#count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Run-PythonScript -ScriptPath $pythonScriptPath -Arguments "$scriptDirectory/log_step_$logger.txt"
$logger++

#step 12 Categorization 
Log "INFO" "step 12 use Categorize.ps1 to categorize files based on the availability of meta data"
& "$scriptDirectory\step12 - Categorization\Categorize.ps1"
