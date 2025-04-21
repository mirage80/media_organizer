param(
    [Parameter(Mandatory=$true)]
    [string]$unzipedDirectory,
    [Parameter(Mandatory=$true)]
    [string]$ExifToolPath
)

$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

# --- Logging Setup ---
$logDir = Join-Path $scriptDirectory "..\Logs"
$logFile = Join-Path $logDir "$scriptName.log"
$logFormat = "{0} - {1}: {2}"

# Create the log directory if it doesn't exist
if (-not (Test-Path $logDir)) {
    try {
        New-Item -ItemType Directory -Path $logDir -Force -ErrorAction Stop | Out-Null
    } catch {
        Write-Error "FATAL: Failed to create log directory '$logDir'. Aborting. Error: $_"
        exit 1
    }
}

# Deserialize the JSON back into a hashtable
$logLevelMap = $null
$logLevelMap = $env:LOG_LEVEL_MAP_JSON

if (-not [string]::IsNullOrWhiteSpace($logLevelMap)) {
    try {
        # --- FIX IS HERE ---
        # Use -AsHashtable to ensure the correct object type
        $logLevelMap = $logLevelMap | ConvertFrom-Json -AsHashtable -ErrorAction Stop
        # --- END FIX ---
    } catch {
        # Log a fatal error and exit immediately if deserialization fails
        Write-Error "FATAL: Failed to deserialize LOG_LEVEL_MAP_JSON environment variable. Check the variable's content is valid JSON. Aborting. Error: $_"
        exit 1
    }
}
if ($null -eq $logLevelMap) {
    # This case should ideally not happen if top.ps1 ran, but handle defensively
    Write-Error "FATAL: LOG_LEVEL_MAP_JSON environment variable not found or invalid. Aborting."
    exit 1
}

# Check if required environment variables are set (by top.ps1 or externally)
if ($null -eq $env:DEDUPLICATOR_CONSOLE_LOG_LEVEL) {
    Write-Error "FATAL: Environment variable DEDUPLICATOR_CONSOLE_LOG_LEVEL is not set. Run via top.ps1 or set externally. Aborting."
    exit 1
}
if ($null -eq $env:DEDUPLICATOR_FILE_LOG_LEVEL) {
    Write-Error "FATAL: Environment variable DEDUPLICATOR_FILE_LOG_LEVEL is not set. Run via top.ps1 or set externally. Aborting."
    exit 1
}

# Read the environment variables directly and trim whitespace (NOW SAFE)
$EffectiveConsoleLogLevelString = $env:DEDUPLICATOR_CONSOLE_LOG_LEVEL.Trim()
$EffectiveFileLogLevelString    = $env:DEDUPLICATOR_FILE_LOG_LEVEL.Trim()

# Look up the numeric level using the effective string and the map
$consoleLogLevel = $logLevelMap[$EffectiveConsoleLogLevelString.ToUpper()]
$fileLogLevel    = $logLevelMap[$EffectiveFileLogLevelString.ToUpper()]

# --- Validation for THIS script's levels ---
if ($null -eq $consoleLogLevel) {
    Write-Error "FATAL: Invalid Console Log Level specified ('$EffectiveConsoleLogLevelString'). Check environment variable or script default. Aborting."
    exit 1
}
if ($null -eq $fileLogLevel) {
    Write-Error "FATAL: Invalid File Log Level specified ('$EffectiveFileLogLevelString'). Check environment variable or script default. Aborting."
    exit 1
}

# --- Log Function Definition ---
function Log {
    param (
        [string]$Level,
        [string]$Message
    )
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $formatted = $logFormat -f $timestamp, $Level.ToUpper(), $Message
    $levelIndex = $logLevelMap[$Level.ToUpper()]

    if ($null -ne $levelIndex) {
        if ($levelIndex -ge $consoleLogLevel) {
            Write-Host $formatted
        }
        if ($levelIndex -ge $fileLogLevel) {
            try {
                Add-Content -Path $logFile -Value $formatted -Encoding UTF8 -ErrorAction Stop
            } catch {
                Write-Warning "Failed to write to log file '$logFile': $_"
            }
        }
    } else {
        Write-Warning "Invalid log level used: $Level"
    }
}

# --- Show-ProgressBar Function Definition ---
function Show-ProgressBar {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Current,

        [Parameter(Mandatory = $true)]
        [int]$Total,

        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    # Check if running in a host that supports progress bars
    if ($null -eq $Host.UI.RawUI) {
        # Fallback for non-interactive environments or simplified hosts
        $percent = 0; 
        if ($Total -gt 0) { 
            $percent = [math]::Round(($Current / $Total) * 100) 
        }
        Write-Host "$Message Progress: $percent% ($Current/$Total)"
        return
    }
    try {
        $percent = [math]::Round(($Current / $Total) * 100)
        $screenWidth = $Host.UI.RawUI.WindowSize.Width - 30
        $barLength = [math]::Min($screenWidth, 80)
        $filledLength = [math]::Round(($barLength * $percent) / 100)
        $emptyLength = $barLength - $filledLength
        $filledBar = ('=' * $filledLength)
        $emptyBar = (' ' * $emptyLength)
        Write-Host -NoNewline "$Message [$filledBar$emptyBar] $percent% ($Current/$Total)`r"
    } catch {
        $percent = 0; if ($Total -gt 0) { $percent = [math]::Round(($Current / $Total) * 100) }
        Write-Host "$Message Progress: $percent% ($Current/$Total)"
    }
}
# --- End Show-ProgressBar Function Definition ---
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
        Log "ERROR" "❌ Atomic write failed for $Path : $_"
        if (Test-Path $tempPath) {
            Remove-Item $tempPath -Force -ErrorAction SilentlyContinue
        }
    }
}

# --- Add WPF Assemblies ---
try {
    Add-Type -AssemblyName PresentationFramework
    Add-Type -AssemblyName PresentationCore
    Add-Type -AssemblyName WindowsBase
    Log "DEBUG" "WPF Assemblies loaded."
} catch {
    Log "CRITICAL" "Failed to load WPF assemblies. GUI cannot be displayed. Error: $($_.Exception.Message)"
    exit 1
}


# --- Configuration ---
$MediaExtensions = @(".jpg", ".mp4")
$TimestampTags = @("DateTimeOriginal", "CreateDate", "ModifyDate") # Prioritized list

# Define source directories based on Step 13 output
$SourceDirWithGeo = Join-Path $unzipedDirectory "with_time_with_geo" 
$SourceDirNoGeo = Join-Path $unzipedDirectory "with_time_no_geo"     

# Place metadata files in the Output Directory for easier management
$CacheFilePath = Join-Path $logDir "Cache$scriptName.log"
$UndoLogFilePath = Join-Path $logDir "Undo$scriptName.log"
$ProcessedLogFilePath = Join-Path $logDir "Processed$scriptName.log"

# --- Helper Functions ---
# Function to safely get metadata using ExifTool
function Get-MediaMetadata {
    param(
        [string]$FilePath,
        [string[]]$Tags,
        [string]$DateFormat = $null # <-- ADDED: Optional date format string
    )
    try {
        $tagArgs = $Tags | ForEach-Object { "-$_" }
        # Base arguments
        $arguments = @("-j", "-n", "-fast")

        # Add date format argument if provided
        if (-not [string]::IsNullOrEmpty($DateFormat)) { # <-- ADDED BLOCK
            $arguments += @("-d", $DateFormat)
        }

        # Add tags and file path
        $arguments += $tagArgs
        $arguments += @($FilePath)

        Log "DEBUG" "Running ExifTool: $ExifToolPath $arguments"
        $jsonOutput = & $ExifToolPath $arguments | ConvertFrom-Json
        return $jsonOutput[0]
    } catch {
        Log "WARNING" "Error getting metadata for '$FilePath': $($_.Exception.Message)"
        return $null
    }
}

# Function to undo the last recorded geotag action
function Undo-LastGeotagAction {
    Log "INFO" "Attempting to undo the last geotag action..."

    # --- Load Undo Log ---
    $undoLog = @{}
    if (Test-Path $UndoLogFilePath) {
        try {
            $undoLog = Get-Content $UndoLogFilePath -Raw | ConvertFrom-Json -AsHashtable
        } catch {
            Log "ERROR" "Failed to load or parse undo log '$UndoLogFilePath'. Cannot undo. Error: $($_.Exception.Message)"
            return @{ Success = $false; Message = "Error loading undo log." }
        }
    }

    if ($undoLog.Count -eq 0) {
        Log "INFO" "Undo log is empty. Nothing to undo."
        return @{ Success = $false; Message = "Nothing to undo." }
    }

    # --- Find Latest Entry ---
    $latestTimestamp = [datetime]::MinValue
    $latestOriginalPath = $null
    $latestUndoData = $null

    foreach ($key in $undoLog.Keys) {
        $entryData = $undoLog[$key]
        try {
            $entryTimestamp = [datetime]::ParseExact($entryData.TimestampApplied, "o", $null)
            if ($entryTimestamp -gt $latestTimestamp) {
                $latestTimestamp = $entryTimestamp
                $latestOriginalPath = $key
                $latestUndoData = $entryData
            }
        } catch {
            Log "WARNING" "Could not parse timestamp for entry '$key' in undo log. Skipping."
        }
    }

    if ($null -eq $latestOriginalPath) {
        Log "ERROR" "Could not find a valid latest entry in the undo log."
        return @{ Success = $false; Message = "Could not find valid entry to undo." }
    }

    Log "INFO" "Found latest action to undo for file: '$latestOriginalPath' (Action Time: $latestTimestamp)"

    # --- Perform Undo Actions ---
    $undoSuccess = $true
    $errorMessage = ""

    # 1. Reverse Move (if applicable)
    if ($latestUndoData.MoveSuccessful -eq $true) {
        $sourceMovePath = $latestUndoData.DestinationPath
        $targetMovePath = $latestOriginalPath # Move it back to the original path

        if ([string]::IsNullOrEmpty($sourceMovePath) -or -not (Test-Path $sourceMovePath -PathType Leaf)) {
             Log "WARNING" "Undo: Source file for move back ('$sourceMovePath') not found or invalid. Skipping move back."
             # Continue to remove tags, but log this issue
        } else {
            try {
                $targetDir = Split-Path -Path $targetMovePath -Parent
                if (-not (Test-Path $targetDir -PathType Container)) {
                    Log "DEBUG" "Undo: Creating directory '$targetDir' for move back."
                    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
                }
                Log "INFO" "Undo: Moving '$sourceMovePath' back to '$targetMovePath'..."
                Move-Item -Path $sourceMovePath -Destination $targetMovePath -Force
                Log "INFO" "Undo: Move back successful."
            } catch {
                Log "ERROR" "Undo: Failed to move file back from '$sourceMovePath' to '$targetMovePath'. Error: $($_.Exception.Message)"
                $errorMessage += "Failed to move file back. "
                $undoSuccess = $false # Consider stopping if move fails? For now, continue to tag removal.
            }
        }
    }

    # 2. Remove Geotags (from the original path)
    Log "INFO" "Undo: Removing geotags from '$latestOriginalPath'..."
    try {
        $arguments = @(
            "-GPSLatitude=",
            "-GPSLongitude=",
            "-GPSLatitudeRef=",
            "-GPSLongitudeRef=",
            "-overwrite_original",
            "-P",
            $latestOriginalPath
        )
        Log "DEBUG" "Undo: Running ExifTool: $ExifToolPath $arguments"
        & $ExifToolPath $arguments
        # We might add verification here if needed, but removal is usually straightforward
        Log "INFO" "Undo: Geotag removal command executed for '$latestOriginalPath'."
    } catch {
        Log "ERROR" "Undo: Failed to remove geotags for '$latestOriginalPath'. Error: $($_.Exception.Message)"
        $errorMessage += "Failed to remove geotags. "
        $undoSuccess = $false
    }

    # --- Update Logs (Only if core undo actions were deemed successful enough) ---
    if ($undoSuccess) {
        # 3. Update Undo Log (Remove entry)
        Log "DEBUG" "Undo: Removing entry for '$latestOriginalPath' from undo log."
        [void]$undoLog.Remove($latestOriginalPath)
        # Atomically save the modified undo log
        $tempUndoPath = "$UndoLogFilePath.tmp"
        try {
            $undoLog | ConvertTo-Json -Depth 5 | Out-File $tempUndoPath -Encoding UTF8 -Force
            $null = Get-Content $tempUndoPath -Raw | ConvertFrom-Json # Validate
            Move-Item -Path $tempUndoPath -Destination $UndoLogFilePath -Force
            Log "DEBUG" "Undo log updated successfully after removal."
        } catch {
            Log "ERROR" "Undo: Failed to save updated undo log '$UndoLogFilePath' after removal. Error: $($_.Exception.Message)"
            $errorMessage += "Failed to update undo log. "
            $undoSuccess = $false
            if (Test-Path $tempUndoPath) { Remove-Item $tempUndoPath -Force -ErrorAction SilentlyContinue }
        }

        # 4. Update Processed Log (Remove entry)
        Log "DEBUG" "Undo: Removing '$latestOriginalPath' from processed log."
        $tempProcessedPath = "$ProcessedLogFilePath.tmp"
        try {
            # Read all lines, filter out the one to remove, write back
            $lines = Get-Content $ProcessedLogFilePath -ErrorAction SilentlyContinue
            $lines | Where-Object { $_ -ne $latestOriginalPath } | Out-File $tempProcessedPath -Encoding UTF8 -Force
            # Basic check if file has content (optional)
            # if ((Get-Item $tempProcessedPath).Length -gt 0) { $null = Get-Content $tempProcessedPath -Raw }
            Move-Item -Path $tempProcessedPath -Destination $ProcessedLogFilePath -Force
            Log "DEBUG" "Processed log updated successfully after removal."

            # Also remove from the in-memory set for the current session
            if ($processedFiles.Contains($latestOriginalPath)) {
                [void]$processedFiles.Remove($latestOriginalPath)
                Log "DEBUG" "Removed '$latestOriginalPath' from in-memory processed set."
            }

        } catch {
            Log "ERROR" "Undo: Failed to update processed log '$ProcessedLogFilePath' after removal. Error: $($_.Exception.Message)"
            $errorMessage += "Failed to update processed log. "
            $undoSuccess = $false
            if (Test-Path $tempProcessedPath) { Remove-Item $tempProcessedPath -Force -ErrorAction SilentlyContinue }
        }

    } else {
         Log "WARNING" "Undo: Core undo actions failed. Logs were not updated."
    }

    # --- Return Result ---
    if ($undoSuccess) {
        Log "INFO" "Successfully undid last action for '$latestOriginalPath'."
        return @{ Success = $true; Message = "Successfully undid action for:`n$latestOriginalPath" }
    } else {
        Log "ERROR" "Undo failed for '$latestOriginalPath'. Details: $errorMessage"
        return @{ Success = $false; Message = "Undo failed for:`n$latestOriginalPath`nError: $errorMessage" }
    }
}

# Function to display the graphical comparison dialog
function Show-GeotagDialog {
    param(
        [Parameter(Mandatory = $true)]
        [PSCustomObject]$TargetFile,

        [Parameter(Mandatory = $true)]
        [PSCustomObject]$ClosestMatch,

        [Parameter(Mandatory = $true)]
        [TimeSpan]$TimeDifference
    )

    # Define the XAML for the window
    $xaml = @"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Geotag Estimation - Compare Files" Height="650" Width="1000"
        WindowStartupLocation="CenterScreen" ResizeMode="CanResize" >
    <Grid Margin="10">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/> <!-- Labels -->
            <RowDefinition Height="*"/>    <!-- Content -->
            <RowDefinition Height="Auto"/> <!-- Buttons -->
        </Grid.RowDefinitions>
        <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/> <!-- Target File -->
            <ColumnDefinition Width="*"/> <!-- Reference File -->
        </Grid.ColumnDefinitions>

        <!-- Labels -->
        <TextBlock Grid.Row="0" Grid.Column="0" Text="Target File (Needs Geotag)" FontWeight="Bold" HorizontalAlignment="Center" Margin="0,0,0,5"/>
        <TextBlock Grid.Row="0" Grid.Column="1" Text="Reference File (Closest Time)" FontWeight="Bold" HorizontalAlignment="Center" Margin="0,0,0,5"/>

        <!-- Content Area -->
        <Border Grid.Row="1" Grid.Column="0" BorderBrush="Gray" BorderThickness="1" Margin="5">
            <StackPanel Margin="5">
                <MediaElement x:Name="TargetMedia" Height="400" LoadedBehavior="Manual" UnloadedBehavior="Stop" Stretch="Uniform" />
                <TextBlock x:Name="TargetPathText" Margin="0,5,0,2" TextWrapping="Wrap" ToolTip="{Binding Text, RelativeSource={RelativeSource Self}}" Text="Path: "/>
                <TextBlock x:Name="TargetTimestampText" Margin="0,2,0,2" Text="Timestamp: "/>
            </StackPanel>
        </Border>

        <Border Grid.Row="1" Grid.Column="1" BorderBrush="Gray" BorderThickness="1" Margin="5">
            <StackPanel Margin="5">
                <MediaElement x:Name="ReferenceMedia" Height="400" LoadedBehavior="Manual" UnloadedBehavior="Stop" Stretch="Uniform" />
                <TextBlock x:Name="ReferencePathText" Margin="0,5,0,2" TextWrapping="Wrap" ToolTip="{Binding Text, RelativeSource={RelativeSource Self}}" Text="Path: "/>
                <TextBlock x:Name="ReferenceTimestampText" Margin="0,2,0,2" Text="Timestamp: "/>
                <TextBlock x:Name="ReferenceCoordsText" Margin="0,2,0,2" Text="Coordinates: "/>
                <TextBlock x:Name="TimeDifferenceText" Margin="0,2,0,2" Text="Time Difference: "/>
            </StackPanel>
        </Border>

        <!-- Buttons -->
        <StackPanel Grid.Row="2" Grid.ColumnSpan="2" Orientation="Horizontal" HorizontalAlignment="Center" Margin="0,10,0,0">
            <Button x:Name="YesButton" Content="_Yes (Apply Geotag)" Width="150" Height="30" Margin="5" ToolTip="Apply the reference file's geotag to the target file and move it."/>
            <Button x:Name="NoButton" Content="_No (Do Not Apply)" Width="150" Height="30" Margin="5" ToolTip="Do not apply the geotag. Mark the target file as processed for this session."/>
            <Button x:Name="SkipButton" Content="_Skip (Decide Later)" Width="150" Height="30" Margin="5" ToolTip="Skip this file for now. It will be shown again in the next run."/>
            <Button x:Name="UndoButton" Content="_Undo Last Action" Width="150" Height="30" Margin="15,5,5,5" ToolTip="Reverts the last geotag applied by this script (removes tags, moves file back)."/>
            <Button x:Name="QuitButton" Content="_Quit Script" Width="150" Height="30" Margin="5" ToolTip="Stop processing any more files in this script run."/>
        </StackPanel>
    </Grid>
</Window>
"@

   # --- Load XAML and Find Controls ---
    $window = $null
    $targetMediaElement = $null
    $referenceMediaElement = $null
    $script:dialogResult = 'q' # Default to Quit if window is closed unexpectedly

    try {
        $reader = (New-Object System.Xml.XmlNodeReader ([xml]$xaml))
        $window = [Windows.Markup.XamlReader]::Load($reader)

        # Find Media Elements
        $targetMediaElement = $window.FindName("TargetMedia")
        $referenceMediaElement = $window.FindName("ReferenceMedia")

        # Find Text Blocks
        $targetPathText = $window.FindName("TargetPathText")
        $targetTimestampText = $window.FindName("TargetTimestampText")
        $referencePathText = $window.FindName("ReferencePathText")
        $referenceTimestampText = $window.FindName("ReferenceTimestampText")
        $referenceCoordsText = $window.FindName("ReferenceCoordsText")
        $timeDifferenceText = $window.FindName("TimeDifferenceText")

        # Find Buttons
        $yesButton = $window.FindName("YesButton")
        $noButton = $window.FindName("NoButton")
        $skipButton = $window.FindName("SkipButton")
        $undoButton = $window.FindName("UndoButton")
        $quitButton = $window.FindName("QuitButton")

        # Basic validation
        if ($null -eq $targetMediaElement -or $null -eq $referenceMediaElement -or $null -eq $yesButton -or $null -eq $undoButton) { 
            throw "Failed to find essential controls in XAML."
        }

    } catch {
        Log "ERROR" "Failed to load or parse XAML for Geotag Dialog: $($_.Exception.Message)"
        # Cannot proceed without the dialog
        return 'q' # Return Quit
    }

    # --- Populate Controls ---
    try {
        # Target File Info
        $targetPathText.Text = "Path: $($TargetFile.FilePath)"
        $targetTimestampText.Text = "Timestamp: $($TargetFile.Timestamp.ToString('yyyy-MM-dd HH:mm:ss'))"
        $targetMediaElement.Source = [System.Uri]$TargetFile.FilePath

        # Reference File Info
        $referencePathText.Text = "Path: $($ClosestMatch.FilePath)"
        $referenceTimestampText.Text = "Timestamp: $($ClosestMatch.Timestamp.ToString('yyyy-MM-dd HH:mm:ss'))"
        $referenceCoordsText.Text = "Coordinates: $($ClosestMatch.Latitude), $($ClosestMatch.Longitude)"
        $timeDifferenceText.Text = "Time Difference: $($TimeDifference.ToString())"
        $referenceMediaElement.Source = [System.Uri]$ClosestMatch.FilePath

        # Attempt to start and pause media to show first frame (might not work perfectly for all codecs)
        # Do this within SourceInitialized or Loaded event for better reliability
        $window.Add_SourceInitialized({
            try {
                $targetMediaElement.Play()
                $targetMediaElement.Pause()
                $referenceMediaElement.Play()
                $referenceMediaElement.Pause()
            } catch {
                Log "DEBUG" "Could not auto-play/pause media elements: $($_.Exception.Message)"
            }
        })

    } catch {
        Log "ERROR" "Failed to populate controls or set media source: $($_.Exception.Message)"
        # Might still be able to show the window with text info
    }

    # --- Define Button Actions ---
    $yesButton.add_Click({
        $script:dialogResult = 'y'
        $window.Close()
    })
    $noButton.add_Click({
        $script:dialogResult = 'n'
        $window.Close()
    })
    $skipButton.add_Click({
        $script:dialogResult = 's'
        $window.Close()
    })
    $quitButton.add_Click({
        $script:dialogResult = 'q'
        $window.Close()
    })

    $undoButton.add_Click({
        Log "DEBUG" "Undo button clicked."
        # Disable button temporarily to prevent double-clicks
        $undoButton.IsEnabled = $false
        try {
            # Call the undo function
            $undoResult = Undo-LastGeotagAction

            # Show feedback to the user
            if ($undoResult.Success) {
                [System.Windows.MessageBox]::Show($window, $undoResult.Message, "Undo Successful", [System.Windows.MessageBoxButton]::OK, [System.Windows.MessageBoxImage]::Information)
            } else {
                [System.Windows.MessageBox]::Show($window, $undoResult.Message, "Undo Failed", [System.Windows.MessageBoxButton]::OK, [System.Windows.MessageBoxImage]::Warning)
            }
        } catch {
             Log "ERROR" "Unexpected error during Undo button click handler: $($_.Exception.Message)"
             [System.Windows.MessageBox]::Show($window, "An unexpected error occurred during the undo operation.", "Undo Error", [System.Windows.MessageBoxButton]::OK, [System.Windows.MessageBoxImage]::Error)
        } finally {
             # Re-enable button
             $undoButton.IsEnabled = $true
        }
    })

    # --- Handle Window Closing (CRUCIAL for releasing file locks) ---
    $window.add_Closing({
        param($req_sender, $e)
        Log "DEBUG" "Closing Geotag Dialog. Releasing media resources."
        try {
            if ($targetMediaElement) {
                $targetMediaElement.Stop()
                $targetMediaElement.Source = $null
            }
            if ($referenceMediaElement) {
                $referenceMediaElement.Stop()
                $referenceMediaElement.Source = $null
            }
            # Force garbage collection to help release file handles sooner, especially for videos
            [System.GC]::Collect()
            [System.GC]::WaitForPendingFinalizers()
        } catch {
            Log "WARNING" "Error during media cleanup on window close: $($_.Exception.Message)"
        }
    })

    # --- Show the Window Modally ---
    Log "INFO" "Displaying comparison dialog..."
    try {
        $null = $window.ShowDialog() # Blocks script execution until closed
    } catch {
        Log "ERROR" "Error displaying the Geotag Dialog: $($_.Exception.Message)"
        $script:dialogResult = 'q' # Default to quit on display error
    }

    Log "INFO" "Dialog closed by user. Choice: $script:dialogResult"
    return $script:dialogResult
}


# Function to parse timestamp from metadata (expecting pre-formatted string)
function Format-Timestamp {
    param(
        [PSCustomObject]$Metadata,
        [string[]]$TimestampTags
    )
    # Define the expected format (must match -d argument format)
    $expectedFormat = "yyyy-MM-dd HH:mm:ss"

    foreach ($tag in $TimestampTags) {
        # Check if the tag exists and has a value
        if ($Metadata.$tag -and $Metadata.$tag -ne '0000-00-00 00:00:00') { # Check against formatted zero date
            try {
                # --- MODIFIED ---
                # Directly parse the pre-formatted string
                return [datetime]::ParseExact($Metadata.$tag, $expectedFormat, $null)
                # --- END MODIFIED ---
            } catch {
                Log "DEBUG" "Could not parse timestamp '$($Metadata.$tag)' using format '$expectedFormat' for tag '$tag'."
            }
        }
    }
    Log "DEBUG" "No valid timestamp found in tags: $($TimestampTags -join ', ')"
    return $null
}


# Function to update geotag using ExifTool
function Update-MediaGeotag {
    param(
        [string]$FilePath,
        [double]$Latitude,
        [double]$Longitude
    )
    try {
        Log "INFO" "Attempting to update geotag for '$FilePath'..."
        $latRef = if ($Latitude -ge 0) { "N" } else { "S" }
        $lonRef = if ($Longitude -ge 0) { "E" } else { "W" }
        $absLat = [Math]::Abs($Latitude)
        $absLon = [Math]::Abs($Longitude)

        $arguments = @(
            "-GPSLatitude=$absLat",
            "-GPSLatitudeRef=$latRef",
            "-GPSLongitude=$absLon",
            "-GPSLongitudeRef=$lonRef",
            "-overwrite_original",
            "-P",
            $FilePath
        )

        Log "DEBUG" "Running ExifTool: $ExifToolPath $arguments"
        & $ExifToolPath $arguments

        # Verification
        $verifyMeta = Get-MediaMetadata -FilePath $FilePath -Tags @("GPSLatitude", "GPSLongitude")
        if ($verifyMeta -and [Math]::Abs($verifyMeta.GPSLatitude - $Latitude) -lt 0.00001 -and [Math]::Abs($verifyMeta.GPSLongitude - $Longitude) -lt 0.00001) {
            Log "INFO" "Successfully updated and verified geotag for '$FilePath'."
            return $true
        } else {
            Log "WARNING" "Geotag update for '$FilePath' could not be verified. Check file manually."
            return $false
        }
    } catch {
        Log "ERROR" "Failed to update geotag for '$FilePath': $($_.Exception.Message)"
        return $false
    }
}

# Function to add entry to the undo log (Using Write-JsonAtomic from top.ps1 concept)
function Add-UndoLogEntry {
    param(
        [string]$OriginalFilePath, # Log the path *before* potential move
        [hashtable]$UndoData       # Contains AppliedLat/Lon, RefFile, Timestamp, potentially DestinationPath
    )
    $undoLog = @{}
    if (Test-Path $UndoLogFilePath) {
        try {
            $undoLog = Get-Content $UndoLogFilePath -Raw | ConvertFrom-Json -AsHashtable
        } catch {
            Log "WARNING" "Could not read existing undo log '$UndoLogFilePath'. Creating a new one. Error: $($_.Exception.Message)"
            $undoLog = @{}
        }
    }
    # Use the original path as the key
    $undoLog[$OriginalFilePath] = $UndoData

    # Atomic write implementation
    $tempPath = "$UndoLogFilePath.tmp"
    try {
        $undoLog | ConvertTo-Json -Depth 5 | Out-File $tempPath -Encoding UTF8 -Force
        $null = Get-Content $tempPath -Raw | ConvertFrom-Json # Basic validation
        Move-Item -Path $tempPath -Destination $UndoLogFilePath -Force
        Log "DEBUG" "Undo log updated successfully: $UndoLogFilePath"
    } catch {
        Log "ERROR" "Failed to save undo log to '$UndoLogFilePath': $($_.Exception.Message)"
        if (Test-Path $tempPath) {
            Remove-Item $tempPath -Force -ErrorAction SilentlyContinue
        }
    }
}

# --- Main Script ---
# Load processed files log
$processedFiles = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
if (Test-Path $ProcessedLogFilePath) {
    try {
        Get-Content $ProcessedLogFilePath | ForEach-Object { [void]$processedFiles.Add($_) }
        Log "INFO" "Loaded $($processedFiles.Count) entries from processed log '$ProcessedLogFilePath'."
    } catch {
        Log "WARNING" "Could not read processed log '$ProcessedLogFilePath'. Starting fresh. Error: $($_.Exception.Message)"
    }
}

# --- Step 14-1: Generate/Load JSON file of media with geotag and timestamp ---
$withGeoAndTime = @() # Initialize

# Attempt to load from cache first
if (Test-Path $CacheFilePath) {
    Log "INFO" "Loading reference cache from '$CacheFilePath'..."
    try {
        # Use Where-Object *after* attempting conversion
        $withGeoAndTime = Get-Content $CacheFilePath -Raw | ConvertFrom-Json | ForEach-Object {
            # Assume valid initially
            $isValidEntry = $true
            try {
                # Attempt to parse and add the DateTime property
                $_.Timestamp = [datetime]::ParseExact($_.TimestampString, "o", $null)
            } catch {
                Log "WARNING" "Could not parse timestamp '$($_.TimestampString)' for file '$($_.FilePath)' from cache. Skipping entry."
                # Mark the entry as invalid instead of assigning null to $_
                $isValidEntry = $false
            }

            # Only output the object if it's still considered valid
            if ($isValidEntry) {
                $_ # Output the potentially modified object
            }
            # If !$isValidEntry, nothing is output for this iteration
        } # End ForEach-Object

        Log "INFO" "Loaded $($withGeoAndTime.Count) valid entries from cache." # Count will be correct now

    } catch {
        Log "WARNING" "Failed to load or parse cache file '$CacheFilePath'. Regenerating... Error: $($_.Exception.Message)"
        $withGeoAndTime = @() # Ensure empty on failure
    }
}

# Regenerate cache if empty OR if source directories exist (to potentially update cache)
if ($withGeoAndTime.Count -eq 0 -or (Test-Path $SourceDirWithGeo -PathType Container)) {
    if ($withGeoAndTime.Count -eq 0) {
        Log "INFO" "Reference cache is empty or failed to load. Scanning source directories..."
    } else {
        Log "INFO" "Re-scanning source directories to potentially update cache..."
        $withGeoAndTime = @() # Clear existing cache data before re-scan
    }

    # Scan Reference Directory (with_time_with_geo)
    if (Test-Path $SourceDirWithGeo -PathType Container) {
        Log "INFO" "Scanning '$SourceDirWithGeo' for reference files..."
        $refMediaFiles = Get-ChildItem -Path $SourceDirWithGeo -Recurse -File | Where-Object { $MediaExtensions -contains $_.Extension }
        $totalRefFiles = $refMediaFiles.Count
        Log "INFO" "Found $totalRefFiles potential reference files."
        $i = 0
        foreach ($file in $refMediaFiles) {
            $i++
            Write-Progress -Activity "Scanning Reference Metadata" -Status "Processing file $i of $totalRefFiles ($($file.Name))" -PercentComplete (($i / $totalRefFiles) * 100)
            $metadata = Get-MediaMetadata -FilePath $file.FullName `
                        -Tags ($TimestampTags + @("GPSLatitude", "GPSLongitude")) `
                        -DateFormat "%Y-%m-%d %H:%M:%S" # <-- ADDED DateFormat argument
            if ($metadata) {
                # Format-Timestamp call remains the same, but receives formatted data
                $timestamp = Format-Timestamp -Metadata $metadata -TimestampTags $TimestampTags
                $latitude = $metadata.GPSLatitude
                $longitude = $metadata.GPSLongitude

                if (($null -ne $timestamp) -and ($null -ne $latitude -and $null -ne $longitude)) {
                    $withGeoAndTime += [PSCustomObject]@{
                        FilePath     = $file.FullName
                        Timestamp    = $timestamp
                        Latitude     = $latitude
                        Longitude    = $longitude
                        HasTimestamp = $true # Implicitly true
                        HasGeotag    = $true  # Implicitly true
                    }
                } else {
                     Log "DEBUG" "File '$($file.FullName)' in reference dir missing required Geo+Time metadata."
                }
            }
        }
        Log "INFO" "Found $($withGeoAndTime.Count) valid reference files in '$SourceDirWithGeo'."
    } else {
         Log "WARNING" "Reference directory '$SourceDirWithGeo' not found during scan."
    }

    # Save the updated cache
    Log "INFO" "Saving $($withGeoAndTime.Count) entries to reference cache '$CacheFilePath'..."
    $cacheData = $withGeoAndTime | Select-Object FilePath, @{N='TimestampString'; E={$_.Timestamp.ToString("o")}}, Latitude, Longitude
    $tempCachePath = "$CacheFilePath.tmp"
    try {
        $cacheData | ConvertTo-Json -Depth 5 | Out-File $tempCachePath -Encoding UTF8 -Force
        $null = Get-Content $tempCachePath -Raw | ConvertFrom-Json # Validate
        Move-Item -Path $tempCachePath -Destination $CacheFilePath -Force
        Log "DEBUG" "Cache file saved successfully: $CacheFilePath"
    } catch {
        Log "ERROR" "Failed to save cache file '$CacheFilePath': $($_.Exception.Message)"
        if (Test-Path $tempCachePath) { Remove-Item $tempCachePath -Force -ErrorAction SilentlyContinue }
    }
}

# --- Step 14-2: Process files without geotags ---
Log "INFO" "Scanning '$SourceDirNoGeo' for target files (Time present, Geo missing)..."
$noGeoButTime = @() # Reset before scan
if (Test-Path $SourceDirNoGeo -PathType Container) {
    $targetMediaFiles = Get-ChildItem -Path $SourceDirNoGeo -Recurse -File | Where-Object { $MediaExtensions -contains $_.Extension }
    $i = 0
    foreach ($file in $targetMediaFiles) {
        $i++

        # Skip if already processed (Y/N decision made)
        if ($processedFiles.Contains($file.FullName)) {
            Log "DEBUG" "Skipping already processed file: $($file.FullName)"
            continue
        }

        $metadata = Get-MediaMetadata -FilePath $file.FullName -Tags ($TimestampTags + @("GPSLatitude", "GPSLongitude")) -DateFormat "%Y-%m-%d %H:%M:%S"
        if ($metadata) {
            $timestamp = Format-Timestamp -Metadata $metadata -TimestampTags $TimestampTags
            $latitude = $metadata.GPSLatitude
            $longitude = $metadata.GPSLongitude
            $hasTimestamp = ($null -ne $timestamp)
            $hasGeotag = ($null -ne $latitude -and $null -ne $longitude)

            if ($hasTimestamp -and (-not $hasGeotag)) {
                 $noGeoButTime += [PSCustomObject]@{
                    FilePath     = $file.FullName
                    Timestamp    = $timestamp
                    Latitude     = $null
                    Longitude    = $null
                    HasTimestamp = $true
                    HasGeotag    = $false
                }
            } else {
                 Log "DEBUG" "File '$($file.FullName)' in target dir does not meet criteria (HasTime: $hasTimestamp, HasGeo: $hasGeotag)."
            }
        }
    }
    Write-Progress -Activity "Scanning Target Metadata" -Completed
    Log "INFO" "Found $($noGeoButTime.Count) target files needing geotag estimation in '$SourceDirNoGeo'."
} else {
    Log "WARNING" "Target directory '$SourceDirNoGeo' not found during scan. No files to process."
    # $noGeoButTime will remain empty
}


if ($withGeoAndTime.Count -eq 0) {
    Log "WARNING" "No reference media files with both timestamp and geotag found in '$unzipedDirectory'. Cannot estimate missing geotags."
    exit # Use exit code other than 0? e.g., exit 2
}

$filesToProcess = $noGeoButTime | Where-Object { -not $processedFiles.Contains($_.FilePath) }
$totalToProcess = $filesToProcess.Count

if ($totalToProcess -eq 0) {
    Log "INFO" "No media files found needing geotag estimation (Timestamp present, Geotag missing, not already processed)."
    exit
}

# --- Step 14-3 - Estimate geotags for files without geotags
Log "INFO" "$totalToProcess files found with timestamp but no geotag (and not previously processed). Starting estimation process..."

$processedCount = 0
$updatedCount = 0
$skippedThisRun = 0

# --- Main Processing Loop ---
foreach ($targetFile in $filesToProcess) {
    $processedCount++
    Log "INFO" "`n--- Processing file $processedCount of $totalToProcess : '$($targetFile.FilePath)' ---"
    Log "DEBUG" "Target Timestamp: $($targetFile.Timestamp)"

    # Find the closest reference file by time
    $minTimeDiff = [TimeSpan]::MaxValue
    $closestMatch = $null

    foreach ($refFile in $withGeoAndTime) {
        # Ensure both timestamps are valid before calculating difference
        if ($null -ne $targetFile.Timestamp -and $null -ne $refFile.Timestamp) {
            $timeDiff = ($targetFile.Timestamp - $refFile.Timestamp)
            if ($timeDiff.TotalSeconds -lt 0) { $timeDiff = $timeDiff.Negate() } # Absolute difference

            if ($timeDiff -lt $minTimeDiff) {
                $minTimeDiff = $timeDiff
                $closestMatch = $refFile
            }
        } else {
            Log "DEBUG" "Skipping comparison due to null timestamp (Target: $($null -ne $targetFile.Timestamp), Ref: $($null -ne $refFile.Timestamp))"
        }
    }

    if ($null -eq $closestMatch) {
        Log "WARNING" "Could not find any valid reference file to compare time with for '$($targetFile.FilePath)'. Skipping."
        $skippedThisRun++
        continue # Skip to the next target file
    }

    Log "INFO" "Closest match found: '$($closestMatch.FilePath)'"
    Log "INFO" "   Reference Timestamp: $($closestMatch.Timestamp)"
    Log "INFO" "   Reference Geotag: $($closestMatch.Latitude), $($closestMatch.Longitude)"
    Log "INFO" "   Time difference: $minTimeDiff"

    # --- Step 14-4: Show GUI and Get User Choice ---
    $choice = Show-GeotagDialog -TargetFile $targetFile -ClosestMatch $closestMatch -TimeDifference $minTimeDiff

    # --- Step 14-5: Act on user choice ---
    $originalPath = $targetFile.FilePath # Store original path before potential move

    switch ($choice) {
        'y' {
            Log "INFO" "User chose YES. Applying geotag from '$($closestMatch.FilePath)'."
            $success = Update-MediaGeotag -FilePath $originalPath -Latitude $closestMatch.Latitude -Longitude $closestMatch.Longitude

            if ($success) {
                $updatedCount++
                $moveAttempted = $false
                $moveSuccessful = $false
                $destinationPath = $null

                # Attempt to move the file to the 'with_geo' structure
                try {
                    $moveAttempted = $true
                    $relativePath = $originalPath -replace [regex]::Escape($SourceDirNoGeo), '' # Get path relative to source root
                    $relativePath = $relativePath.TrimStart('\/')
                    $destinationPath = Join-Path -Path $SourceDirWithGeo -ChildPath $relativePath
                    $destinationDir = Split-Path -Path $destinationPath -Parent

                    if (-not (Test-Path $destinationDir -PathType Container)) {
                        Log "DEBUG" "Creating destination directory: $destinationDir"
                        New-Item -ItemType Directory -Path $destinationDir -Force | Out-Null
                    }

                    Log "INFO" "Moving '$originalPath' to '$destinationPath'..."
                    Move-Item -Path $originalPath -Destination $destinationPath -Force
                    $moveSuccessful = $true
                    Log "INFO" "Move successful."
                    # Update targetFile object's path if needed for subsequent steps *within this run* (though unlikely needed here)
                    # $targetFile.FilePath = $destinationPath
                } catch {
                    Log "WARNING" "Failed to move '$originalPath' to '$destinationPath' after geotag update. Error: $($_.Exception.Message)"
                    # File remains in original location, but geotagged.
                    $moveSuccessful = $false
                }

                # Add to Undo Log
                $undoData = @{
                    AppliedLatitude  = $closestMatch.Latitude
                    AppliedLongitude = $closestMatch.Longitude
                    ReferenceFile    = $closestMatch.FilePath
                    TimestampApplied = (Get-Date).ToString("o") # ISO 8601 timestamp of action
                    MoveAttempted    = $moveAttempted
                    MoveSuccessful   = $moveSuccessful
                    DestinationPath  = $destinationPath # Log where it was *supposed* to go or *did* go
                }
                Add-UndoLogEntry -OriginalFilePath $originalPath -UndoData $undoData

                # Add original path to processed log only after successful update/decision
                try {
                    Add-Content -Path $ProcessedLogFilePath -Value $originalPath
                    [void]$processedFiles.Add($originalPath)
                    Log "DEBUG" "Added '$originalPath' to processed log after 'y'."
                } catch {
                     Log "WARNING" "Failed to add '$originalPath' to processed log '$ProcessedLogFilePath': $($_.Exception.Message)"
                }

            } else {
                 Log "WARNING" "Update-MediaGeotag failed for '$originalPath'. File not moved or marked as processed. Will retry next time."
                 $skippedThisRun++ # Count as skipped for this run's summary
            }
        }
        'n' {
            Log "INFO" "User chose NO for '$originalPath'."
            # Add original path to processed log as the user made a decision
            try {
                Add-Content -Path $ProcessedLogFilePath -Value $originalPath
                [void]$processedFiles.Add($originalPath)
                Log "DEBUG" "Added '$originalPath' to processed log after 'n'."
            } catch {
                 Log "WARNING" "Failed to add '$originalPath' to processed log '$ProcessedLogFilePath': $($_.Exception.Message)"
            }
        }
        's' {
            Log "INFO" "User chose SKIP for '$originalPath'. It will be considered in the next run."
            $skippedThisRun++
            # Do NOT add to processed log here
        }
        'q' {
            Log "INFO" "User chose QUIT. Stopping estimation process."
            break # Exit the foreach loop
        }
        default {
             Log "WARNING" "Unknown choice '$choice' received from dialog for '$originalPath'. Treating as QUIT."
             break # Exit the foreach loop on unexpected result
        }
    } # End switch

} # End foreach ($targetFile in $filesToProcess)

# --- Final Summary ---
Log "INFO" "`n--- Geotag Estimation Summary ---"
Log "INFO" "Total files needing geotags (Timestamp present, Geotag missing): $($noGeoButTime.Count)"
Log "INFO" "Files presented for processing in this run: $processedCount"
Log "INFO" "Files updated with estimated geotag: $updatedCount"
Log "INFO" "Files skipped by user ('s' or failed update) in this run: $skippedThisRun"
$remainingToProcess = $noGeoButTime.Count - $processedFiles.Count
Log "INFO" "Files remaining for future runs (skipped or not reached): $remainingToProcess"
Log "INFO" "Reference cache saved to: $CacheFilePath"
Log "INFO" "Undo log saved to: $UndoLogFilePath"
Log "INFO" "Processed log saved to: $ProcessedLogFilePath"

Log "INFO" "Geotag Estimation Process Finished."
