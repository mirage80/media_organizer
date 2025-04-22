param(
    [Parameter(Mandatory=$true)]
    [string]$zipDirectory = 'D:',
    [Parameter(Mandatory=$true)]
    [string]$unzipedDirectory = 'C:\Users\sawye\Downloads\Telegram Desktop\ChatExport_2025-04-18',
    [Parameter(Mandatory=$true)]
    [string]$7zip = 'C:\Program Files\7-Zip\7z.exe',
    [Parameter(Mandatory=$true)]
    [string]$ExifToolPath = 'C:\Program Files\exiftools\exiftool.exe',
    [Parameter(Mandatory=$true)]
    [string]$magickPath = 'C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe',
    [Parameter(Mandatory=$true)]
    [string]$pythonExe = 'C:\Program Files\Python313\python.exe',
    [Parameter(Mandatory=$true)]
    [string]$ffmpeg = 'C:\Program Files\ffmpeg\bin\ffmpeg.exe',
    [Parameter(Mandatory=$true)]
    [string]$ffprobe = 'C:\Program Files\ffmpeg\bin\ffprobe.exe',
    [Parameter(Mandatory=$true)]
    [string]$DefaultConsoleLogLevelString = "WARNING",
    [Parameter(Mandatory=$true)]
    [string]$DefaultFileLogLevelString    = "WARNING"      
)

$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$RecycleBinPath = Join-Path -Path $unzipedDirectory -ChildPath '$RECYCLE.BIN'
$logger = 0

#Utils Dirctory
$UtilDirectory = Join-Path $scriptDirectory "..\Utils"
$UtilFile = Join-Path $UtilDirectory "Utils.psm1"
Import-Module $UtilFile -Force

# --- Logging Setup ---
$logDir = Join-Path $scriptDirectory "Logs"
$logFilePath = Join-Path $logDir "main_pipeline.log"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

# Define the map ONCE
$logLevelMap = @{
    "DEBUG"    = 0
    "INFO"     = 1
    "WARNING"  = 2
    "ERROR"    = 3
    "CRITICAL" = 4
}

# --- Set the map in the environment variable for child scripts ---
$env:LOG_LEVEL_MAP_JSON = $logLevelMap | ConvertTo-Json -Compress

# --- Set Environment Variables for Children (if not already set externally) ---
# This ensures child scripts inherit the correct default if no override exists.
if ($null -eq $env:DEDUPLICATOR_CONSOLE_LOG_LEVEL) {
    $env:DEDUPLICATOR_CONSOLE_LOG_LEVEL = $DefaultConsoleLogLevelString
}
if ($null -eq $env:DEDUPLICATOR_FILE_LOG_LEVEL) {
    $env:DEDUPLICATOR_FILE_LOG_LEVEL = $DefaultFileLogLevelString
}

# --- Determine log levels for THIS script (top.ps1) ---
# Now, read the environment variables (which are guaranteed to be set by the logic above)
$EffectiveConsoleLogLevelString = $env:DEDUPLICATOR_CONSOLE_LOG_LEVEL
$EffectiveFileLogLevelString    = $env:DEDUPLICATOR_FILE_LOG_LEVEL

# Look up the numeric level using the effective string and the map
$consoleLogLevel = $logLevelMap[$EffectiveConsoleLogLevelString.ToUpper()]
$fileLogLevel    = $logLevelMap[$EffectiveFileLogLevelString.ToUpper()]

# --- Validation and fallback for THIS script's levels (in top.ps1) ---
if ($null -eq $consoleLogLevel) {
    Write-Error "FATAL: Invalid Console Log Level specified ('$EffectiveConsoleLogLevelString'). Check environment variable DEDUPLICATOR_CONSOLE_LOG_LEVEL or script default. Aborting."
    exit 1
}

if ($null -eq $fileLogLevel) {
    Write-Error "FATAL: Invalid File Log Level specified ('$EffectiveFileLogLevelString'). Check environment variable DEDUPLICATOR_FILE_LOG_LEVEL or script default. Aborting."
    exit 1
}

function Log {
    param (
        [string]$Level,
        [string]$Message
    )
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $formatted = "$timestamp - $Level - $Message"
    $levelIndex = $logLevelMap[$Level.ToUpper()]

    if ($null -ne $levelIndex) {
        if ($levelIndex -ge $consoleLogLevel) {
            Write-Host $formatted
        }
        if ($levelIndex -ge $fileLogLevel) {
            try {
                Add-Content -Path $logFilePath -Value $formatted -Encoding UTF8 -ErrorAction Stop
            } catch { Write-Warning "Failed to write to log file '$logFilePath': $_" }
        }
    } else { Write-Warning "Invalid log level used in top.ps1: '$Level'. Message: $Message" }
}

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

# Function to run a Python script with error handling
function Invoke-PythonScript {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath,

        # Change the type to accept an array of strings
        [string[]]$Arguments
    )

    # Ensure $pythonExe is accessible here (it should be if defined at script scope)
    if (-not $pythonExe) {
        Log "ERROR" "Python executable path variable `$pythonExe is not defined."
        exit 1
    }

    try {
        # Check if the Arguments array is null or empty
        if ($null -eq $Arguments -or $Arguments.Count -eq 0) {
            Log "DEBUG" "Executing: $pythonExe ""$ScriptPath"""
            & $pythonExe "$ScriptPath"
        } else {
            # Use argument splatting (@Arguments) to pass array elements as separate arguments
            $argStringForLog = $Arguments | ForEach-Object { """$_""" } | Join-String -Separator ' ' # Quote args for logging
            Log "DEBUG" "Executing: $pythonExe ""$ScriptPath"" $argStringForLog"
            & $pythonExe "$ScriptPath" @Arguments
        }
    } catch {
        Log "ERROR" "Error running Python script '$ScriptPath' with command: '$pythonExe ""$ScriptPath"" $($Arguments -join ' ')'. Error: $_"
        # Consider if exiting immediately is always desired, or if you should just log and continue
        exit 1
    }
}

 function Use-ValidDirectoryName {
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

        try {
            Rename-Item -Path $DirectoryPath -NewName $sanitizedName -Force
            Log "INFO" "Renamed '$originalName' to '$sanitizedName'"
        } catch {
            Log "WARNING" "Failed to rename '$originalName': $_"
        }
    }
}

function Use-ValidDirectoriesRecursively {
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
        Use-ValidDirectoryName -DirectoryPath $directory.FullName
    }
    Use-ValidDirectoryName -DirectoryPath $RootDirectory #sanitize the root directory also.
}


#count 1
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/log_step_$logger.txt", "$unzipedDirectory")
$logger++

# step 1 - Extract Zip Files
Log "INFO" "step1 - Extract Zip Files"

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
Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/log_step_$logger.txt", "$unzipedDirectory")
$logger++

# step 2 - Sanetize the names
Write-Host -NoNewline "`n"
Log "INFO" "step2 - Sanetize the names"
Use-ValidDirectoriesRecursively -RootDirectory $unzipedDirectory

#step3 - clean json names json files
Log "INFO" "step3 - clean json names json files"
& "$scriptDirectory\step3 - clean_json\clean_json.ps1"  -unzipedDirectory $unzipedDirectory -zipedDirectory $zipedDirectory -ExifToolPath $ExifToolPath

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
Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/log_step_$logger.txt", "$unzipedDirectory")
$logger++

#step 4 - remove orphaned json files
Log "INFO" "step4 - remove orphaned json files"
& "$scriptDirectory\step4 - ListandRemoveOrphanedJSON\remove_orphaned_json.ps1" -unzipedDirectory $unzipedDirectory
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
Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/log_step_$logger.txt", "$unzipedDirectory")
$logger++

# step 5 - use converter to change everything to mp4 & jpg
Log "INFO" "step5 - use converter to change everything to mp4 & jpg"
& "$scriptDirectory\step5 - converter\converter.ps1" -unzipedDirectory $unzipedDirectory -ffmpeg $ffmpeg -magickPath $magickPath

#count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/log_step_$logger.txt", "$unzipedDirectory")
$logger++

#step 6 use step6 - Consolidate_Meta to combine time stamps
Log "INFO" "step6 use 6 - Consolidate_Meta to combine time stamps"
& "$scriptDirectory\step6 - Consolidate_Meta\Consolidate_Meta.ps1" -unzipedDirectory "$unzipedDirectory" -ExifToolPath "$ExifToolPath"

 #count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/log_step_$logger.txt", "$unzipedDirectory")
$logger++

#step 7 - $RECYCLE.BIN
Log "INFO" "Step 7 RECYCLE.BIN"
# Ensure the Recycle Bin path exists before attempting to change attributes
if (Test-Path -Path $RecycleBinPath -PathType Container) {
    attrib -H -R -S -A $RecycleBinPath
    Remove-Item -Path (Join-Path -Path $RecycleBinPath -ChildPath "*") -Recurse -Force
}

#count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/log_step_$logger.txt", "$unzipedDirectory")
$logger++


#step 8-1 - Hash and Group Possible Video Duplicates
Log "INFO" "Step 8-1 Hash AND Group Possible Video Duplicates to extract groups"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step8 - HashAndGroup\HashANDGroupPossibleVideoDuplicates.py'
Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments "$unzipedDirectory\"

#step 8-2 - Hash and Group Possible Image Duplicates
Log "INFO" "Step 8-2 Hash AND Group Possible Image Duplicates to extract groups"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step8 - HashAndGroup\HashANDGroupPossibleImageDuplicates.py'
Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments "$unzipedDirectory\"

#count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/log_step_$logger.txt", "$unzipedDirectory")
$logger++

#step 9-1 Remove Exact Video Duplicate
Log "INFO" "step 9-1 Remove Exact Video Duplicate"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step9 - RemoveExactDuplicates\RemoveExactVideoDuplicate.py'
Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments '--dry-run'

#step 9-2 Remove Exact Image Duplicate
Log "INFO" "step 9-2 Remove Exact Image Duplicate"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step9 - RemoveExactDuplicates\RemoveExactImageDuplicate.py'
Invoke-PythonScript -ScriptPath $pythonScriptPath
#count

$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/log_step_$logger.txt", "$unzipedDirectory")
$logger++

#step 10-1 Show AND Remove Duplicate Video
Log "INFO" "step 10-1 Show AND Remove Duplicate Video"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step10 - ShowANDRemoveDuplicate\ShowANDRemoveDuplicateVideo.py'
Invoke-PythonScript -ScriptPath $pythonScriptPath


#step 10-2 Show AND Remove Duplicate Image
Log "INFO" "step 10-1 Show AND Remove Duplicate Image"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step10 - ShowANDRemoveDuplicate\ShowANDRemoveDuplicateImage.py'
Invoke-PythonScript -ScriptPath $pythonScriptPath

#count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/log_step_$logger.txt", "$unzipedDirectory")
$logger++

#step 11-1 Remove Junk Video
Log "INFO" "step 11-1 use RemoveJunkVideo.py to remove junk Videos"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step11 - RemoveJunk\RemoveJunkVideo.py'
Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments "$unzipedDirectory\"

#step 11-2 Remove Junk Image 
Log "INFO" "step 11-2 use RemoveJunkImage.py to remove junk Videos"
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'step11 - RemoveJunk\RemoveJunkImage.py'
Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments "$unzipedDirectory\"

#count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/log_step_$logger.txt", "$unzipedDirectory")
$logger++

#step 12-1 Reconstruction of corrupt Videos
Log "INFO" "step 12-1 use VideoReconstruction.ps1 to Reconstruct of corrupt Videos" -ffmpeg $ffmpeg
$videoReconList = Join-Path $scriptDirectory "Output\video_reconstruct_info.json" # Or wherever it's actually saved
& "$scriptDirectory\step12 - Reconstruction\VideoReconstruction.ps1" -ffmpeg $ffmpeg -ffprob $ffprobe -reconstructListPath $videoReconList

#step 12-2 Reconstruction of corrupt Images
Log "INFO" "step 12-2 use ImageReconstruction.ps1 to Reconstruct of corrupt Images" -magickPath $magickPath
$imageReconList = Join-Path $scriptDirectory "Output\image_reconstruct_info.json" # Or wherever it's actually saved
& "$scriptDirectory\step12 - Reconstruction\ImageReconstruction.ps1" -magickPath $magickPath -reconstructListPath $imageReconList

#count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/log_step_$logger.txt", "$unzipedDirectory")
$logger++

#step 13 Categorization 
Log "INFO" "step 13 use Categorize.ps1 to categorize files based on the availability of meta data"
& "$scriptDirectory\step13 - Categorization\Categorize.ps1" -unzipedDirectory $unzipedDirectory -ExifToolPath $ExifToolPath

#count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/log_step_$logger.txt", "$unzipedDirectory")
$logger++

#step 13 Categorization 
Log "INFO" "step 14 use EstimateByTime.ps1 to Estimate Location of Files"
& "$scriptDirectory\step14  - Estimate By Time\EstimateByTime.ps1" -unzipedDirectory $unzipedDirectory -ExifToolPath $ExifToolPath

#count
$pythonScriptPath = Join-Path -Path $scriptDirectory -ChildPath 'Step0 - Tools\counter\counter.py'
Invoke-PythonScript -ScriptPath $pythonScriptPath -Arguments @("$scriptDirectory/Logs/log_step_$logger.txt", "$unzipedDirectory")
$logger++
