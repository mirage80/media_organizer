param(
    [Parameter(Mandatory=$true)]
    [string]$unzippedDirectory,
    [Parameter(Mandatory=$true)]
    [string]$step
)

# --- Path Setup ---
$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

# Utils Directory
$UtilDirectory = Join-Path $scriptDirectory "..\Utils"
$UtilFile = Join-Path $UtilDirectory "Utils.psm1"
$MediaToolsFile = Join-Path $UtilDirectory 'MediaTools.psm1'
Import-Module $UtilFile -Force
Import-Module $MediaToolsFile -Force

# --- Logging Setup ---
$logDirectory = Join-Path $scriptDirectory "..\Logs"
$Logger = Initialize-ScriptLogger -LogDirectory $logDirectory -ScriptName $scriptName -Step $step
$Log = $Logger.Logger

# Inject logger for module functions
Set-UtilsLogger -Logger $Log
Set-MediaToolsLogger -Logger $Log

& $Log "INFO" "--- Script Started: $scriptName ---"

function Get-SanitizedName {
    param ([string]$Name)

    # This list includes reserved names that are invalid as the base name of a file in Windows.
    $reservedNames = 'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9', 'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'

    # Allow word characters (alphanumeric + underscore), hyphen, and period. Replace others with underscore.
    $sanitized = $Name -replace '[^\w\-.]+', '_'
    # Collapse multiple underscores into one
    $sanitized = $sanitized -replace '__+','_'
    # Remove leading/trailing underscores AFTER collapsing
    $sanitized = $sanitized -replace '^_|_$',''

    # Check if the resulting base name is a reserved system name.
    $baseName = [System.IO.Path]::GetFileNameWithoutExtension($sanitized)
    if ($reservedNames -icontains $baseName) {
        $extension = [System.IO.Path]::GetExtension($sanitized)
        # Prepend an underscore to the base name to make it valid.
        $sanitized = "_$($baseName)$($extension)"
    }

    return $sanitized
}

function Use-ValidDirectoryName {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DirectoryPath
    )

    $item = $null # Initialize $item
    $originalName = ''
    $parentPath = ''
    $sanitizedName = ''
    $newPath = ''
    try {
        $item = Get-Item -Path $DirectoryPath -ErrorAction Stop # Ensure item exists before proceeding
        # A root directory is the only directory with no parent. It cannot be renamed.
        if ($null -eq $item.Parent) {
            & $Log "DEBUG" "Skipping root directory '$($item.FullName)' as it cannot be renamed."
            return
        }
        $originalName = $item.Name.Trim()
        $parentPath = $item.Parent.FullName
        $sanitizedName = Get-SanitizedName -Name $originalName

        # Add check for empty name after sanitization
        if ([string]::IsNullOrWhiteSpace($sanitizedName)) {
            & $Log "WARNING" "Skipping rename of dir '$originalName' in '$parentPath' because sanitized name is empty."
            return
        }
        if ($originalName -ne $sanitizedName) {
            $newPath = Join-Path -Path $parentPath -ChildPath $sanitizedName

            # --- Attempt Rename using Move-Item with -Force ---
            # Move-Item with -Force handles overwriting existing items at the destination path.
            & $Log "INFO" "Attempting to rename '$originalName' to '$sanitizedName' in '$parentPath' (will overwrite if target exists)."
            Move-Item -Path $item.FullName -Destination $newPath -Force -ErrorAction Stop
            & $Log "INFO" "Successfully renamed '$originalName' to '$sanitizedName' (now at '$newPath')."

        } else {
             & $Log "DEBUG" "Name '$originalName' in '$parentPath' is already sanitized."
        }
    } catch {
        # Log detailed error information
        $errorMessage = "Failed to process or rename path '$DirectoryPath'."
        if ($item) { # If we managed to get the item
            $errorMessage += " Original name: '$originalName'."
            if ($originalName -ne $sanitizedName) {
                 $errorMessage += " Target name: '$sanitizedName'. Target path: '$newPath'."
            }
        }
        # Check if it's a specific 'item already exists' error that Move-Item -Force should have handled but didn't (e.g., permissions)
        if ($_.Exception.Message -match 'Cannot create a file when that file already exists') {
             $errorMessage += " (Move-Item -Force might have failed due to permissions or item being in use)."
        }
        $errorMessage += " Error details: $($_.Exception.Message)"
        & $Log "WARNING" $errorMessage
        # Optionally log the full error record for debugging
        # Log "DEBUG" "Full error record: $_"
    }
}

function Use-ValidDirectoriesRecursively {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RootDirectory
    )

    if (-not (Test-Path -Path $RootDirectory -PathType Container)) {
        & $Log "ERROR" "Root directory '$RootDirectory' does not exist."
        return
    }

    $directories = Get-ChildItem -Path $RootDirectory -Directory -Recurse -ErrorAction SilentlyContinue
    $sortedDirectories = $directories | Sort-Object @{Expression = { $_.FullName.Length }} -Descending

    # Process the sorted directories (deepest first)
    foreach ($directory in $sortedDirectories) {
        Use-ValidDirectoryName -DirectoryPath $directory.FullName
    }

    # Finally, sanitize the root directory itself after all children are done
    Use-ValidDirectoryName -DirectoryPath $RootDirectory
}

function Use-ValidFileName {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath
    )
    $item = $null; $originalName = ''; $parentPath = ''; $sanitizedName = ''; $newPath = ''
    try {
        $item = Get-Item -Path $FilePath -ErrorAction Stop
        $originalName = $item.Name.Trim()
        $parentPath = $item.Directory.FullName

        # Sanitize the base name, but preserve the extension
        $baseName = [System.IO.Path]::GetFileNameWithoutExtension($originalName)
        $extension = [System.IO.Path]::GetExtension($originalName) # Includes the dot

        $sanitizedBaseName = Get-SanitizedName -Name $baseName

        if ([string]::IsNullOrWhiteSpace($sanitizedBaseName)) {
            & $Log "WARNING" "Skipping rename of file '$originalName' in '$parentPath' because sanitized base name is empty."
            return
        }

        $sanitizedName = $sanitizedBaseName + $extension

        if ($originalName -ne $sanitizedName) {
            $newPath = Join-Path -Path $parentPath -ChildPath $sanitizedName
            & $Log "INFO" "Renaming file '$originalName' to '$sanitizedName' in '$parentPath'."
            Move-Item -Path $item.FullName -Destination $newPath -Force -ErrorAction Stop
        }
    } catch {
        & $Log "WARNING" "Failed to process or rename file path '$FilePath'. Error: $($_.Exception.Message)"
    }
}

function Use-ValidFilesRecursively {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RootDirectory
    )
    if (-not (Test-Path -Path $RootDirectory -PathType Container)) {
        & $Log "ERROR" "Root directory '$RootDirectory' does not exist."
        return
    }
    $files = Get-ChildItem -Path $RootDirectory -File -Recurse -ErrorAction SilentlyContinue
    $totalItems = $files.Count
    $currentItem = 0

    foreach ($file in $files) {
        $currentItem++
        $percent = if ($totalItems -gt 0) { [int](($currentItem / $totalItems) * 100) } else { 100 }
        # Update only the second-level progress bar with this step's specific progress
        Update-GraphicalProgressBar -SubTaskPercent $percent -SubTaskMessage "Sanitizing Filename: $($file.Name)"
        Use-ValidFileName -FilePath $file.FullName
    }
}

# --- Main Execution ---
& $Log "INFO" "--- Starting Directory Name Sanitization (deepest first) ---"
Use-ValidDirectoriesRecursively -RootDirectory $unzippedDirectory

& $Log "INFO" "--- Starting File Name Sanitization ---"
Use-ValidFilesRecursively -RootDirectory $unzippedDirectory

Write-Host "" # Newline after progress bar
& $Log "INFO" "--- Script Finished: $scriptName ---"
