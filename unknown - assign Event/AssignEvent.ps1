$ffmpegPath = "ffmpeg"
$ffprobePath = "ffprobe"
$verbosity = 1
$logFile = "C:\path\to\logfile.txt"

# Import necessary .NET libraries
Add-Type -Path "C:\Users\sawye\.nuget\packages\opencvsharp4\4.10.0.20241108\lib\netstandard2.0\OpenCvSharp.dll"
Add-Type -AssemblyName PresentationFramework, System.Windows.Forms, System.Drawing

# Define file extensions
$imageExtensions = @(".jpg")
$videoExtensions = @(".mp4")

# Executes user input for event-based organization
function Exec_Event_Assignment {
    param (
        [System.IO.FileInfo]$file1,
        [System.IO.DirectoryInfo]$DestDirectory
    )

    $Dir = $DestDirectory.FullName
    $sourcePath = $file1.FullName
    $SrcDirectory = $file1.DirectoryName
    $subfolderName = Split-Path -Path $SrcDirectory -Leaf

    if (-Not (Test-Path -Path $sourcePath)) {
        Log-Message "Error: $file1 not found in source directory." -type "error"
        return
    }

    $Event_dir = Join-Path -Path $Dir -ChildPath "events"
    if (-Not (Test-Path -Path $Event_dir -PathType Container)) {
        New-Item -Path $Event_dir -ItemType Directory -Force
    }

    $Selection = Show_Event_DirectorySelector -Path $Event_dir -Possible_Event $subfolderName
    $choice = $Selection[-1]

    [OpenCvSharp.Cv2]::DestroyAllWindows()

    if ($choice.ToLower() -eq "no") {  
        Log-Message "No action needed for $file1" -type "information"
    } else {
        Log-Message "Moving $file1 to event subdirectory"  -type "information"
        $TargetPath = Join-Path $Event_dir $choice
        Move_File_To_Event_Subdirectory -FileToMove $file1 -DestDirectory $([System.IO.DirectoryInfo]$TargetPath)
    }
}

function Move_File_To_Event_Subdirectory {
    param (
        [System.IO.FileInfo]$FileToMove,
        [System.IO.DirectoryInfo]$DestDirectory            
    )
    $FilePath = $FileToMove.FullName
    $DestPath = $DestDirectory.FullName

    if (-not (Test-Path -Path $DestPath)) {
        New-Item -Path $DestPath -ItemType Directory -Force
    }

    if (-not (Test-Path -Path $FilePath)) {
        Log-Message "Error: The file '$FilePath' does not exist." -type "error"
        return
    }

    Move_Safe -SrcFile $FilePath -DestDirectory $DestDirectory
}

function Show_Event_DirectorySelector {
    param (
        [string]$Path,
        [string]$Possible_Event
    )
    
    if (!(Test-Path -Path $Path -PathType Container)) {
        [System.Windows.MessageBox]::Show("The path '$Path' is not a valid directory.", "Error", [System.Windows.MessageBoxButton]::OK, [System.Windows.MessageBoxImage]::Error)
        return $null
    }

    $selected = [ref]$null

    $window = New-Object System.Windows.Window
    $window.Title = "Select an Event"
    $window.Width = 300
    $window.SizeToContent = "Height"
    $window.WindowStartupLocation = "CenterScreen"
    $window.Topmost = $true
    $window.ResizeMode = "NoResize" 

    $stackPanel = New-Object System.Windows.Controls.StackPanel
    $stackPanel.Orientation = "Vertical"
    $window.Content = $stackPanel

    $directories = Get-ChildItem -Path $Path -Directory

    foreach ($dir in $directories) {
        $button = New-Object System.Windows.Controls.Button
        $button.Content = $dir.Name
        $button.Margin = "5"
    
        $currentButton = $button  
    
        $currentButton.Add_Click({ 
            $selected.Value = $this.Content  
            $window.Close()
        })
        $stackPanel.Children.Add($currentButton)
    }

    $addButton = New-Object System.Windows.Controls.Button
    $addButton.Content = "Add Event"
    $addButton.Margin = "5"
    $addButton.Add_Click({
        $newDirPath = Add_NewDirectory -BasePath $Path
        $selected.Value = Split-Path -Path $newDirPath -Leaf
        $window.Close()
    })
    $stackPanel.Children.Add($addButton)

    $Possible_Path = Join-Path -Path $Path -ChildPath $Possible_Event
    if (!(Test-Path -Path $Possible_Path -PathType Container)) {
        $PossibleEventButton = New-Object System.Windows.Controls.Button
        $PossibleEventButton.Content = $Possible_Event
        $PossibleEventButton.Margin = "5"
        $PossibleEventButton.Add_Click({
            $selected.Value = $this.Content
            $window.Close()
        })
        $stackPanel.Children.Add($PossibleEventButton)
    }

    $dontKnowButton = New-Object System.Windows.Controls.Button
    $dontKnowButton.Content = "No"
    $dontKnowButton.Margin = "5"
    $dontKnowButton.Add_Click({
        $selected.Value =  $this.Content
        $window.Close()
    })
    $stackPanel.Children.Add($dontKnowButton)

    $window.ShowDialog() | Out-Null
    return $selected.value
}

function Log-Message {
    param (
        [string]$message,
        [string]$type
    )
    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $logMessage = "[$timestamp] $type: $message"
    Add-Content -Path $logFile -Value $logMessage
    if ($verbosity -eq 1) {
        switch ($type.ToLower()) {
            "error" { Write-Error $logMessage }
            "information" { Write-Host $logMessage -ForegroundColor Green }
            "warning" { Write-Host $logMessage -ForegroundColor Yellow }
            default { Write-Host $logMessage -ForegroundColor White }
        }
    }
}

function Get_UniqueFilePath {
    param([System.IO.FileInfo]$SrcFile, [System.IO.DirectoryInfo]$DestDirectory)
    
    $counter = 1
    $fileHash = [System.BitConverter]::ToString([System.Security.Cryptography.MD5]::Create().ComputeHash([System.Text.Encoding]::UTF8.GetBytes($SrcFile.FullName)))
    do {
        $uniqueFilePath = Join-Path $DestDirectory.FullName "${($SrcFile.BaseName)}_$fileHash" + "$($SrcFile.Extension.ToLower())"
        $counter++
    } while (Test-Path $uniqueFilePath)
    
    return [System.IO.FileInfo]::new($uniqueFilePath)
}

function Main {
    param (
        [System.IO.DirectoryInfo]$SrcDirectory,
        [System.IO.DirectoryInfo]$DestDirectory
    )
    
    $files = Get-ChildItem -Path $SrcDirectory.FullName -File | Where-Object { $_.Extension -in $imageExtensions + $videoExtensions }
    $currentItem = 0
    $totalItems = $files.Count

    # Process files in parallel to improve performance
    $jobs = @()
    foreach ($file in $files) {
        $jobs += Start-Job -ScriptBlock {
            param($file, $DestDirectory)
            Exec_Event_Assignment -file1 $file -DestDirectory $DestDirectory
        } -ArgumentList $file, $DestDirectory
    }

    # Wait for all jobs to complete
    $jobs | ForEach-Object { Wait-Job -Job $_; Receive-Job -Job $_ }

    # Clean up jobs
    $jobs | ForEach-Object { Remove-Job -Job $_ }
}

# Execute the main function
Main -SrcDirectory "C:\Source\no_time_with_geo" -DestDirectory "C:\Destination"
Main -SrcDirectory "C:\Source\no_time_no_geo" -DestDirectory "C:\Destination"
