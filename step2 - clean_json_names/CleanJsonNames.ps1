param(
    [Parameter(Mandatory=$true)]
    [string]$unzippedDirectory,
    [string]$step
)

$scriptDirectory = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$scriptName = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

#Utils Dirctory
$UtilDirectory = Join-Path $scriptDirectory "..\Utils"
$UtilFile = Join-Path $UtilDirectory "Utils.psm1"
Import-Module $UtilFile -Force

# --- Centralized Logging Setup ---
try {
    $logFile = Join-Path $scriptDirectory "..\Logs" -ChildPath $("Step_$step" + "_" + "$scriptName.log")
    Initialize-ChildScriptLogger -ChildLogFilePath $logFile
} catch {
    Write-Error "FATAL: Failed to initialize logger. Error: $_"
    exit 1
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
    
    $item = $null # Initialize $item
    $originalName = ''
    $parentPath = ''
    $sanitizedName = ''
    $newPath = ''

    try {
        $item = Get-Item -Path $DirectoryPath -ErrorAction Stop # Ensure item exists before proceeding
        $originalName = $item.Name.Trim()
        $parentPath = $item.Parent.FullName

        # --- Sanitization Logic ---
        # Allow word characters (alphanumeric + underscore), hyphen, and period. Replace others with underscore.
        $sanitizedName = $originalName -replace '[^\w\-.]+', '_'
        $sanitizedName = $sanitizedName -replace '__+','_'       # Collapse multiple underscores
        $sanitizedName = $sanitizedName -replace '^_|_$',''      # Remove leading/trailing underscores AFTER collapsing

        # Add check for empty name after sanitization
        if ([string]::IsNullOrWhiteSpace($sanitizedName)) {
            Log "WARNING" "Skipping rename of '$originalName' in '$parentPath' because sanitized name is empty."
            return
        }
        # --- End Sanitization ---
        if ($originalName -ne $sanitizedName) {
            $newPath = Join-Path -Path $parentPath -ChildPath $sanitizedName

            # --- Attempt Rename using Move-Item with -Force ---
            # Move-Item with -Force handles overwriting existing items at the destination path.
            Log "INFO" "Attempting to rename '$originalName' to '$sanitizedName' in '$parentPath' (will overwrite if target exists)."
            Move-Item -Path $item.FullName -Destination $newPath -Force -ErrorAction Stop
            Log "INFO" "Successfully renamed '$originalName' to '$sanitizedName' (now at '$newPath')."

        } else {
             Log "DEBUG" "Name '$originalName' in '$parentPath' is already sanitized."
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
        Log "WARNING" $errorMessage
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
        Log "ERROR" "Root directory '$RootDirectory' does not exist."
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

Use-ValidDirectoriesRecursively -RootDirectory $unzippedDirectory
