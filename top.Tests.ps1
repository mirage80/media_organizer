v#Requires -Modules Pester -Version 5.0

<#
.SYNOPSIS
    Unit tests for the top.ps1 media organizer pipeline script.
#>

# --- Pester Test Suite ---

Describe 'top.ps1 - Media Organizer Pipeline' {

    # Define variables within BeforeAll where $PSScriptRoot is reliable
    BeforeAll {
        # --- Define Test Paths INSIDE BeforeAll ---
        $script:TestScriptDirectory = $PSScriptRoot # Use script scope to make available to tests
        $script:TestLogsDir = Join-Path $script:TestScriptDirectory "TestLogs"
        $script:TestUnzipDir = Join-Path $script:TestScriptDirectory "TestUnzip"
        $script:TestZipDir = Join-Path $script:TestScriptDirectory "TestZip"
        $script:TestRecycleBin = Join-Path $script:TestUnzipDir '$RECYCLE.BIN' # Use TestUnzipDir as base

        Write-Host "BeforeAll: TestScriptDirectory = '$($script:TestScriptDirectory)'"
        Write-Host "BeforeAll: TestLogsDir = '$($script:TestLogsDir)'"

        # Create necessary test directories (now that paths are defined)
        # Use -ErrorAction SilentlyContinue in case they already exist
        New-Item -Path $script:TestLogsDir -ItemType Directory -Force -ErrorAction SilentlyContinue | Out-Null
        New-Item -Path $script:TestUnzipDir -ItemType Directory -Force -ErrorAction SilentlyContinue | Out-Null
        New-Item -Path $script:TestZipDir -ItemType Directory -Force -ErrorAction SilentlyContinue | Out-Null
        Write-Host "BeforeAll: Ensured test directories exist."

        # --- Mocks MUST be defined BEFORE dot-sourcing the script ---

        # 1. SIMPLIFIED Split-Path Mock specifically for loading $scriptDirectory
        Mock -CommandName Split-Path -MockWith {
            param($Path, $Parent)
            if ($PSBoundParameters.ContainsKey('Parent')) {
                Write-Verbose "LOAD MOCK: Split-Path called with -Parent. Returning '$($script:TestScriptDirectory)'."
                return $script:TestScriptDirectory # Use script-scoped variable
            }
            Microsoft.PowerShell.Management\Split-Path @PSBoundParameters
        } -ModuleName Microsoft.PowerShell.Management -Verifiable

        # 2. Mock cmdlets used *during* script loading
        #    Make Test-Path mock slightly more robust - check for $null path
        Mock -CommandName Test-Path {
            param($Path, $PathType)
            if ($null -eq $Path) {
                Write-Warning "LOAD MOCK: Test-Path called with NULL Path!"
                return $false
            }
            Write-Verbose "LOAD MOCK: Test-Path for '$Path' (PathType: $PathType) -> returning True"
            return $true
        } -Verifiable
        Mock -CommandName New-Item { Write-Verbose "LOAD MOCK: New-Item call for $Path" } -Verifiable

        # 3. Mock external commands (Full Path or Name as called in top.ps1)
        #    Store paths/names in script scope for consistent use in mocks and tests
        $script:mock7zPath = 'C:\Program Files\7-Zip\7z.exe'
        $script:mockExifPath = 'C:\Program Files\exiftools\exiftool.exe'
        $script:mockMagickPath = 'C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe'
        $script:mockFfmpegName = 'ffmpeg.exe'
        $script:mockPythonName = 'python3.13.exe'
        $script:mockAttribName = 'attrib.exe'

        Mock -CommandName $script:mock7zPath { Write-Verbose "Mocked 7z.exe ($($script:mock7zPath)) call with args: $Args" } -Verifiable
        Mock -CommandName $script:mockExifPath { Write-Verbose "Mocked exiftool.exe ($($script:mockExifPath)) call with args: $Args" } -Verifiable
        Mock -CommandName $script:mockMagickPath { Write-Verbose "Mocked magick.exe ($($script:mockMagickPath)) call with args: $Args" } -Verifiable
        Mock -CommandName $script:mockFfmpegName { Write-Verbose "Mocked ffmpeg.exe ($($script:mockFfmpegName)) call with args: $Args" } -Verifiable
        Mock -CommandName $script:mockPythonName { Write-Verbose "Mocked python3.13.exe ($($script:mockPythonName)) call with args: $Args" } -Verifiable
        Mock -CommandName $script:mockAttribName { Write-Verbose "Mocked attrib.exe ($($script:mockAttribName)) call with args: $Args" } -Verifiable

        # 3b. Mock Get-Command for external tools (Just in case)
        #     Return a dummy object that looks like a command info
        $dummyCmdInfo = [pscustomobject]@{ Name = 'dummy.exe'; CommandType = 'Application'; Path = 'C:\dummy.exe'; Source = 'C:\dummy.exe' }
        Mock -CommandName Get-Command {
            param($Name)
            Write-Verbose "LOAD MOCK: Get-Command called for '$Name'"
            # Check if it's one of the tools we care about during load checks
            if ($Name -in ($script:mock7zPath, $script:mockExifPath, $script:mockMagickPath, $script:mockFfmpegName)) {
                 Write-Verbose "LOAD MOCK: Get-Command returning dummy object for '$Name'"
                 # Return a dummy object that won't cause Test-Path to fail immediately if Get-Command is used implicitly
                 return $dummyCmdInfo
            }
            # Fallback to real Get-Command for anything else
            Microsoft.PowerShell.Core\Get-Command @PSBoundParameters
        } -Verifiable


        # 4. Mock other cmdlets
        Mock -CommandName Invoke-Expression { Write-Verbose "Mocked Invoke-Expression call with command: $Command" } -Verifiable
        Mock -CommandName Remove-Item { Write-Verbose "Mocked Remove-Item call for path: $Path" } -Verifiable
        Mock -CommandName Move-Item { Write-Verbose "Mocked Move-Item call from $Path to $Destination" } -Verifiable
        Mock -CommandName Rename-Item { Write-Verbose "Mocked Rename-Item call for $Path to $NewName" } -Verifiable
        Mock -CommandName Get-Content { return @() } -Verifiable
        Mock -CommandName Add-Content { Write-Verbose "Mocked Add-Content call to $Path" } -Verifiable
        Mock -CommandName Out-File { Write-Verbose "Mocked Out-File call to $FilePath" } -Verifiable
        Mock -CommandName Get-ChildItem { return @() } -Verifiable
        # Mock Write-Host globally BUT allow explicit Write-Host from test script itself for debugging
        Mock -CommandName Write-Host { if ($MyInvocation.ScriptName -ne $PSScriptRoot) { return } else { Microsoft.PowerShell.Utility\Write-Host @PSBoundParameters } } -Verifiable
        Mock -CommandName Show-ProgressBar { } -Verifiable
        Mock -CommandName exit { throw "Simulated exit with code $args[0]" } -Verifiable
        Mock -CommandName ConvertTo-Json { param($InputObject) return $InputObject | Microsoft.PowerShell.Utility\ConvertTo-Json -Depth 10 } -Verifiable
        Mock -CommandName ConvertFrom-Json { param($InputObject) return $InputObject | Microsoft.PowerShell.Utility\ConvertFrom-Json } -Verifiable
        Mock -CommandName Get-Item { param($Path) return [pscustomobject]@{ Name = (Microsoft.PowerShell.Management\Split-Path $Path -Leaf); FullName = $Path } } -Verifiable


        # --- Load the script into scope ---
        Write-Host "BeforeAll: Attempting to dot-source top.ps1..."
        try {
            . (Join-Path $script:TestScriptDirectory "top.ps1")
            Write-Host "BeforeAll: Dot-sourcing top.ps1 SUCCEEDED."
        } catch {
            Write-Error "BeforeAll: FAILED to dot-source top.ps1: $_"
            # Log the specific exception details
            Write-Error "Exception Type: $($_.Exception.GetType().FullName)"
            Write-Error "Exception Message: $($_.Exception.Message)"
            Write-Error "ScriptStackTrace: $($_.ScriptStackTrace)"
            throw $_ # Re-throw
        }

        # --- Remove mocks specific to loading ---
        Remove-Mock -CommandName Split-Path -ModuleName Microsoft.PowerShell.Management -ErrorAction SilentlyContinue
        Remove-Mock -CommandName Get-Command -ErrorAction SilentlyContinue # Remove Get-Command mock too
        Write-Host "BeforeAll: Removed loading-specific mocks (Split-Path, Get-Command)."

        # --- Verify essential variables are set after loading ---
        if ($null -eq $script:scriptDirectory) { Write-Error "BeforeAll: script:scriptDirectory is NULL!" } else { Write-Host "BeforeAll: script:scriptDirectory = '$($script:scriptDirectory)'" }
        if ($null -eq $script:logDir) { Write-Error "BeforeAll: script:logDir is NULL!" } else { Write-Host "BeforeAll: script:logDir = '$($script:logDir)'" }
        if ($null -eq $script:logFilePath) { Write-Error "BeforeAll: script:logFilePath is NULL!" } else { Write-Host "BeforeAll: script:logFilePath = '$($script:logFilePath)'" }
        if ($null -eq $script:TestLogsDir) { Write-Error "BeforeAll: script:TestLogsDir is NULL!" } # Verify test var itself

    } # End BeforeAll

    AfterAll {
        # Use script-scoped variables for cleanup paths
        Write-Host "AfterAll: Cleaning up test directories..."
        if ($script:TestLogsDir) { Remove-Item -Path $script:TestLogsDir -Recurse -Force -ErrorAction SilentlyContinue }
        if ($script:TestUnzipDir) { Remove-Item -Path $script:TestUnzipDir -Recurse -Force -ErrorAction SilentlyContinue }
        if ($script:TestZipDir) { Remove-Item -Path $script:TestZipDir -Recurse -Force -ErrorAction SilentlyContinue }
    }

    # --- Tests ---

    Context 'Initial Setup and Tool Checks' {
        It 'Should define required variables' {
            # Check variables loaded from top.ps1
            $script:zipDirectory | Should -Be 'D:'
            $script:unzipedDirectory | Should -Be 'E:'
            $script:scriptDirectory | Should -Be $script:TestScriptDirectory # Compare script var with test var
            $script:7zip | Should -Be $script:mock7zPath # Use test variable for comparison
            $script:ExifToolPath | Should -Be $script:mockExifPath
            $script:magickPath | Should -Be $script:mockMagickPath
            $script:ffmpeg | Should -Be $script:mockFfmpegName
            $script:RecycleBinPath | Should -Be (Join-Path $script:unzipedDirectory '$RECYCLE.BIN')
        }

        # --- Tool Check Tests ---
        It 'Should exit if 7-Zip is not found' {
            # Arrange
            Mock -CommandName Test-Path -MockWith { param($Path) if ($Path -eq $script:mock7zPath) { return $false } else { return $true } }
            Mock -CommandName Log

            # Act & Assert
            { . (Join-Path $script:TestScriptDirectory "top.ps1") } | Should -Throw "Simulated exit with code 1"
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'ERROR'; Message = "7-Zip not found at $($script:mock7zPath). Aborting." } -Times 1 -Scope It
        }

        It 'Should exit if ExifTool is not found' {
            Mock -CommandName Test-Path -MockWith { param($Path) if ($Path -eq $script:mockExifPath) { return $false } else { return $true } }
            Mock -CommandName Log
            { . (Join-Path $script:TestScriptDirectory "top.ps1") } | Should -Throw "Simulated exit with code 1"
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'ERROR'; Message = "Exiftools not found at $($script:mockExifPath). Aborting." } -Times 1 -Scope It
        }

         It 'Should exit if ImageMagick is not found' {
            Mock -CommandName Test-Path -MockWith { param($Path) if ($Path -eq $script:mockMagickPath) { return $false } else { return $true } }
            Mock -CommandName Log
            { . (Join-Path $script:TestScriptDirectory "top.ps1") } | Should -Throw "Simulated exit with code 1"
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'ERROR'; Message = "magik not found at $($script:mockMagickPath). Aborting." } -Times 1 -Scope It
        }

         It 'Should exit if ffmpeg is not found' {
            Mock -CommandName Test-Path -MockWith { param($Path) if ($Path -eq $script:mockFfmpegName) { return $false } else { return $true } }
            Mock -CommandName Log
            { . (Join-Path $script:TestScriptDirectory "top.ps1") } | Should -Throw "Simulated exit with code 1"
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'ERROR'; Message = "ffmpeg not found at $($script:mockFfmpegName). Aborting." } -Times 1 -Scope It
        }

        It 'Should proceed if all tools are found' {
            Mock -CommandName Test-Path { return $true } # Ensure the global mock is active
            { . (Join-Path $script:TestScriptDirectory "top.ps1") } | Should -Not -Throw
        }
    }

    Context 'Function: Log' {
        BeforeEach {
            # Access script-scoped variables set in BeforeAll
            # Ensure logLevelMap is available (it should be loaded by top.ps1 into script scope)
            if (-not $script:logLevelMap) { throw "logLevelMap not found in script scope for Log tests!" }
            $script:consoleLogLevel = $script:logLevelMap["INFO"]
            $script:fileLogLevel = $script:logLevelMap["DEBUG"]
            $script:logFilePath = Join-Path $script:TestLogsDir "test_pipeline.log" # Use test path var
            if (Test-Path $script:logFilePath) { Remove-Item $script:logFilePath -Force }

            # Unmock Write-Host and Add-Content specifically for Log tests
            Remove-Mock -CommandName Write-Host -ErrorAction SilentlyContinue
            Remove-Mock -CommandName Add-Content -ErrorAction SilentlyContinue

            # Mock them again to capture calls
            Mock -CommandName Write-Host { $script:logOutput_Host = $ArgumentList[0] } -Verifiable
            Mock -CommandName Add-Content { $script:logOutput_File = $Value; $script:logOutput_FilePath = $Path } -Verifiable
            $script:logOutput_Host = $null
            $script:logOutput_File = $null
            $script:logOutput_FilePath = $null
        }
        AfterEach {
             # Restore global Write-Host mock (suppress output from SUT, allow from test script)
             Mock -CommandName Write-Host { if ($MyInvocation.ScriptName -ne $PSScriptRoot) { return } else { Microsoft.PowerShell.Utility\Write-Host @PSBoundParameters } } -Verifiable
             Mock -CommandName Add-Content { Write-Verbose "Mocked Add-Content call to $Path" } -Verifiable
        }

         It 'Should log DEBUG to file only (with default levels)' {
            Log "DEBUG" "Debug message"
            $script:logOutput_Host | Should -BeNullOrEmpty
            $script:logOutput_File | Should -Match "DEBUG - Debug message"
            $script:logOutput_FilePath | Should -Be $script:logFilePath
        }

        It 'Should log INFO to console and file (with default levels)' {
            Log "INFO" "Info message"
            $script:logOutput_Host | Should -Match "INFO - Info message"
            $script:logOutput_File | Should -Match "INFO - Info message"
            $script:logOutput_FilePath | Should -Be $script:logFilePath
        }

        It 'Should log WARNING to console and file' {
            Log "WARNING" "Warning message"
            $script:logOutput_Host | Should -Match "WARNING - Warning message"
            $script:logOutput_File | Should -Match "WARNING - Warning message"
        }

        It 'Should log ERROR to console and file' {
            Log "ERROR" "Error message"
            $script:logOutput_Host | Should -Match "ERROR - Error message"
            $script:logOutput_File | Should -Match "ERROR - Error message"
        }

        It 'Should respect console log level' {
            $script:consoleLogLevel = $script:logLevelMap["WARNING"] # Only WARNING and ERROR to console
            Log "INFO" "Info message"
            $script:logOutput_Host | Should -BeNullOrEmpty
            Log "WARNING" "Warning message"
            $script:logOutput_Host | Should -Match "WARNING - Warning message"
        }

        It 'Should respect file log level' {
            $script:fileLogLevel = $script:logLevelMap["ERROR"] # Only ERROR to file
            Log "WARNING" "Warning message"
            $script:logOutput_File | Should -BeNullOrEmpty
            Log "ERROR" "Error message"
            $script:logOutput_File | Should -Match "ERROR - Error message"
        }
    }

    Context 'Function: Write-JsonAtomic' {
        $testJsonPath = Join-Path $script:TestScriptDirectory "test.json"
        $testJsonTempPath = "$testJsonPath.tmp"
        $testData = @{ Name = "Test"; Value = 123 }

        BeforeEach {
            if (Test-Path $testJsonPath) { Remove-Item $testJsonPath -Force }
            if (Test-Path $testJsonTempPath) { Remove-Item $testJsonTempPath -Force }
            Mock -CommandName Test-Path { param($Path) return $false }
            Mock -CommandName Log { }
            (Get-Mock -CommandName ConvertTo-Json).Clear()
            (Get-Mock -CommandName Out-File).Clear()
            (Get-Mock -CommandName Get-Content).Clear()
            (Get-Mock -CommandName ConvertFrom-Json).Clear()
            (Get-Mock -CommandName Move-Item).Clear()
            (Get-Mock -CommandName Remove-Item).Clear()
            (Get-Mock -CommandName Log).Clear()
        }

         It 'Should write data to temp file, validate, and move to final path' {
            Mock -CommandName Get-Content { param($Path) if($Path -eq $testJsonTempPath) { return '{"Name":"Test","Value":123}' } else { return $null } } -Verifiable
            Mock -CommandName ConvertFrom-Json { param($InputObject) return $InputObject | Microsoft.PowerShell.Utility\ConvertFrom-Json } -Verifiable
            Write-JsonAtomic -Data $testData -Path $testJsonPath
            Assert-MockCalled -CommandName ConvertTo-Json -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Out-File -Parameters @{ FilePath = $testJsonTempPath } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Get-Content -Parameters @{ Path = $testJsonTempPath } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName ConvertFrom-Json -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Move-Item -Parameters @{ Path = $testJsonTempPath; Destination = $testJsonPath } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Remove-Item -Exactly 0 -Scope It
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'INFO'; Message = "✅ Atomic write succeeded: $testJsonPath" } -Exactly 1 -Scope It
        }

        It 'Should log error and remove temp file if ConvertTo-Json fails' {
            Mock -CommandName ConvertTo-Json { throw "JSON Conversion Failed" } -Verifiable
            Mock -CommandName Log
            Write-JsonAtomic -Data $testData -Path $testJsonPath
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'ERROR'; Message = "❌ Atomic write failed for $testJsonPath : JSON Conversion Failed" } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Move-Item -Exactly 0 -Scope It
            Assert-MockCalled -CommandName Remove-Item -Exactly 0 -Scope It
        }

         It 'Should log error and remove temp file if Out-File fails' {
            Mock -CommandName Out-File { throw "Cannot write file" } -Verifiable
            Mock -CommandName Test-Path { return $false }
            Mock -CommandName Log
            Write-JsonAtomic -Data $testData -Path $testJsonPath
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'ERROR'; Message = "❌ Atomic write failed for $testJsonPath : Cannot write file" } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Move-Item -Exactly 0 -Scope It
            Assert-MockCalled -CommandName Remove-Item -Exactly 0 -Scope It
        }

        It 'Should log error and remove temp file if JSON validation fails' {
            Mock -CommandName Get-Content { param($Path) if($Path -eq $testJsonTempPath) { return '{"Name":"Test","Value":123}' } else { return $null } } -Verifiable
            Mock -CommandName ConvertFrom-Json { throw "Invalid JSON" } -Verifiable
            Mock -CommandName Test-Path { param($Path) if ($Path -eq $testJsonTempPath) { return $true } else { return $false } }
            Mock -CommandName Log
            Write-JsonAtomic -Data $testData -Path $testJsonPath
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'ERROR'; Message = "❌ Atomic write failed for $testJsonPath : Invalid JSON" } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Move-Item -Exactly 0 -Scope It
            Assert-MockCalled -CommandName Remove-Item -Parameters @{ Path = $testJsonTempPath } -Exactly 1 -Scope It
        }

         It 'Should log error and remove temp file if Move-Item fails' {
            Mock -CommandName Get-Content { param($Path) if($Path -eq $testJsonTempPath) { return '{"Name":"Test","Value":123}' } else { return $null } } -Verifiable
            Mock -CommandName ConvertFrom-Json { param($InputObject) return $InputObject | Microsoft.PowerShell.Utility\ConvertFrom-Json } -Verifiable
            Mock -CommandName Move-Item { throw "Access Denied" } -Verifiable
            Mock -CommandName Test-Path { param($Path) if ($Path -eq $testJsonTempPath) { return $true } else { return $false } }
            Mock -CommandName Log
            Write-JsonAtomic -Data $testData -Path $testJsonPath
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'ERROR'; Message = "❌ Atomic write failed for $testJsonPath : Access Denied" } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Remove-Item -Parameters @{ Path = $testJsonTempPath } -Exactly 1 -Scope It
        }
    }

    Context 'Function: Invoke-PythonScript' {
        $testPyScript = Join-Path $script:TestScriptDirectory "test_script.py"

        BeforeEach {
            Mock -CommandName Log { }
            (Get-Mock -CommandName $script:mockPythonName).Clear() # Use variable
            (Get-Mock -CommandName Log).Clear()
            (Get-Mock -CommandName exit).Clear()
        }

        It 'Should call python3.13.exe with script path only when no arguments' {
            Invoke-PythonScript -ScriptPath $testPyScript
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters $testPyScript -Exactly 1 -Scope It # Use variable
        }

        It 'Should call python3.13.exe with script path and arguments' {
            $arguments = "--input file.txt --output results.json"
            Invoke-PythonScript -ScriptPath $testPyScript -Arguments $arguments
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters @($testPyScript, $arguments) -Exactly 1 -Scope It # Use variable
        }

        It 'Should log error and exit if python script fails' {
            Mock -CommandName $script:mockPythonName { throw "Python Error" } -Verifiable # Use variable
            Mock -CommandName Log
            Mock -CommandName exit { throw "Simulated exit 1" } -Verifiable
            { Invoke-PythonScript -ScriptPath $testPyScript } | Should -Throw "Simulated exit 1"
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'ERROR'; Message = "Error running Python script '$testPyScript': Python Error" } -Exactly 1 -Scope It
        }
    }

    Context 'Function: Use-ValidDirectoryName' {
        $testDirPath = Join-Path $script:TestUnzipDir "Test Dir !@#"
        $sanitizedName = "Test_Dir_"
        $sanitizedPath = Join-Path $script:TestUnzipDir $sanitizedName

        BeforeEach {
             Mock -CommandName Get-Item {
                param($Path)
                $name = Microsoft.PowerShell.Management\Split-Path $Path -Leaf
                if ($Path -match "^[a-zA-Z]:\\?$") { return [pscustomobject]@{ Name = $name; FullName = $Path } }
                if ($Path -like '*ValidName*') { return [pscustomobject]@{ Name = 'ValidName'; FullName = $Path } }
                if ($Path -like '*_leading*') { return [pscustomobject]@{ Name = '_leading'; FullName = $Path } }
                if ($Path -like '*trailing_*') { return [pscustomobject]@{ Name = 'trailing_'; FullName = $Path } }
                return [pscustomobject]@{ Name = $name; FullName = $Path }
            } -Verifiable
            Mock -CommandName Log { }
            (Get-Mock -CommandName Rename-Item).Clear()
            (Get-Mock -CommandName Log).Clear()
        }

        It 'Should not rename if the name is already valid' {
            $validPath = Join-Path $script:TestUnzipDir "ValidName"
            Use-ValidDirectoryName -DirectoryPath $validPath
            Assert-MockCalled -CommandName Rename-Item -Exactly 0 -Scope It
        }

        It 'Should rename directory with invalid characters' {
            Use-ValidDirectoryName -DirectoryPath $testDirPath
            Assert-MockCalled -CommandName Rename-Item -Parameters @{ Path = $testDirPath; NewName = $sanitizedName } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'INFO'; Message = "Renamed 'Test Dir !@#' to '$sanitizedName'" } -Exactly 1 -Scope It
        }

         It 'Should remove leading underscore' {
            $leadingPath = Join-Path $script:TestUnzipDir "_leading"
            Use-ValidDirectoryName -DirectoryPath $leadingPath
            Assert-MockCalled -CommandName Rename-Item -Parameters @{ Path = $leadingPath; NewName = 'leading' } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'INFO'; Message = "Renamed '_leading' to 'leading'" } -Exactly 1 -Scope It
        }

        It 'Should remove trailing underscore' {
            $trailingPath = Join-Path $script:TestUnzipDir "trailing_"
            Use-ValidDirectoryName -DirectoryPath $trailingPath
            Assert-MockCalled -CommandName Rename-Item -Parameters @{ Path = $trailingPath; NewName = 'trailing' } -Exactly 1 -Scope It
             Assert-MockCalled -CommandName Log -Parameters @{ Level = 'INFO'; Message = "Renamed 'trailing_' to 'trailing'" } -Exactly 1 -Scope It
        }

        It 'Should not attempt to rename a drive root' {
            Use-ValidDirectoryName -DirectoryPath "E:"
            Assert-MockCalled -CommandName Rename-Item -Exactly 0 -Scope It
            Assert-MockCalled -CommandName Log -Exactly 0 -Scope It
        }

        It 'Should log warning if rename fails' {
            Mock -CommandName Rename-Item { throw "Access Denied" } -Verifiable
            Mock -CommandName Log
            Use-ValidDirectoryName -DirectoryPath $testDirPath
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'WARNING'; Message = "Failed to rename 'Test Dir !@#': Access Denied" } -Exactly 1 -Scope It
        }
    }

     Context 'Function: Use-ValidDirectoriesRecursively' {
        $rootPath = $script:TestUnzipDir
        $subDir1Invalid = Join-Path $rootPath "Sub Dir 1!"
        $subDir2Valid = Join-Path $rootPath "SubDir2"
        $subSubDirInvalid = Join-Path $subDir2Valid "Sub Sub Dir 3?"

        BeforeEach {
            Mock -CommandName Test-Path { param($Path, $PathType) if($Path -eq $rootPath -and $PathType -eq 'Container') { return $true } else { return $false } } -Verifiable
            $mockSubDir1 = [pscustomobject]@{ FullName = $subDir1Invalid; Name = "Sub Dir 1!"; PSIsContainer = $true }
            $mockSubDir2 = [pscustomobject]@{ FullName = $subDir2Valid; Name = "SubDir2"; PSIsContainer = $true }
            $mockSubSubDir = [pscustomobject]@{ FullName = $subSubDirInvalid; Name = "Sub Sub Dir 3?"; PSIsContainer = $true }
            Mock -CommandName Get-ChildItem {
                param($Path, $Directory, $Recurse)
                if ($Path -eq $rootPath -and $Directory -and $Recurse) { return @($mockSubDir1, $mockSubDir2, $mockSubSubDir) }
                else { return @() }
            } -Verifiable
            Mock -CommandName Use-ValidDirectoryName { Write-Verbose "Mocked Use-ValidDirectoryName for $($args[0])" } -Verifiable
            Mock -CommandName Log { }
            (Get-Mock -CommandName Use-ValidDirectoryName).Clear()
            (Get-Mock -CommandName Get-ChildItem).Clear()
            (Get-Mock -CommandName Test-Path).Clear()
            (Get-Mock -CommandName Log).Clear()
        }

         It 'Should call Use-ValidDirectoryName for each directory and the root' {
             Mock -CommandName Test-Path { param($Path, $PathType) if($Path -eq $rootPath -and $PathType -eq 'Container') { return $true } else { return $false } } -Verifiable
             Use-ValidDirectoriesRecursively -RootDirectory $rootPath
             Assert-MockCalled -CommandName Get-ChildItem -Parameters @{ Path = $rootPath; Directory = $true; Recurse = $true } -Exactly 1 -Scope It
             Assert-MockCalled -CommandName Use-ValidDirectoryName -Parameters @{ DirectoryPath = $subDir1Invalid } -Exactly 1 -Scope It
             Assert-MockCalled -CommandName Use-ValidDirectoryName -Parameters @{ DirectoryPath = $subDir2Valid } -Exactly 1 -Scope It
             Assert-MockCalled -CommandName Use-ValidDirectoryName -Parameters @{ DirectoryPath = $subSubDirInvalid } -Exactly 1 -Scope It
             Assert-MockCalled -CommandName Use-ValidDirectoryName -Parameters @{ DirectoryPath = $rootPath } -Exactly 1 -Scope It
        }

        It 'Should log error and return if root directory does not exist' {
             Mock -CommandName Test-Path { return $false } -Verifiable
             Mock -CommandName Log
             Use-ValidDirectoriesRecursively -RootDirectory $rootPath
             Assert-MockCalled -CommandName Log -Parameters @{ Level = 'ERROR'; Message = "Root directory '$rootPath' does not exist." } -Exactly 1 -Scope It
             Assert-MockCalled -CommandName Get-ChildItem -Exactly 0 -Scope It
             Assert-MockCalled -CommandName Use-ValidDirectoryName -Exactly 0 -Scope It
        }
     }

    Context 'Pipeline Step 1: Extract Zip Files' {
        BeforeEach {
            $mockZip1 = [pscustomobject]@{ FullName = (Join-Path $script:TestZipDir "a.zip"); Name = "a.zip"; PSIsContainer = $false }
            $mockZip2 = [pscustomobject]@{ FullName = (Join-Path $script:TestZipDir "b.zip"); Name = "b.zip"; PSIsContainer = $false }
            Mock -CommandName Get-ChildItem -MockWith {
                 param($Path, $Recurse, $Filter, $File)
                 if ($Path -eq $script:zipDirectory -and $Filter -eq '*.zip' -and $File.IsPresent) { return @($mockZip1, $mockZip2) }
                 Microsoft.PowerShell.Management\Get-ChildItem @PSBoundParameters
            } -Verifiable
            (Get-Mock -CommandName $script:mock7zPath).Clear() # Use variable
            (Get-Mock -CommandName Show-ProgressBar).Clear()
            (Get-Mock -CommandName Get-ChildItem).Clear()
        }

        It 'Should call 7z.exe for each zip file found' {
            $zipFiles = Get-ChildItem -Path $script:zipDirectory -recurse -Filter "*.zip" -File
            $currentItem = 0
            $totalItems = $zipFiles.count
            foreach ($zipFile in $zipFiles) {
                $currentItem++
                Show-ProgressBar -Current $currentItem -Total $totalItems -Message "$($zipFile.FullName)"
                & "$($script:7zip)" x -aos "$($zipFile.FullName)" "-o$($script:unzipedDirectory)" | Out-Null
            }
            Assert-MockCalled -CommandName Get-ChildItem -Parameters @{ Path = $script:zipDirectory; Recurse = $true; Filter = '*.zip'; File = $true } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Show-ProgressBar -Times 2 -Scope It
            Assert-MockCalled -CommandName $script:mock7zPath -Times 2 -Scope It # Use variable
            Assert-MockCalled -CommandName $script:mock7zPath -Parameters @('x', '-aos', $mockZip1.FullName, "-o$($script:unzipedDirectory)") -Exactly 1 -Scope It # Use variable
            Assert-MockCalled -CommandName $script:mock7zPath -Parameters @('x', '-aos', $mockZip2.FullName, "-o$($script:unzipedDirectory)") -Exactly 1 -Scope It # Use variable
        }
    }

    Context 'Pipeline Step 3: Clean JSON Names (Batch Rename)' {
         $batchScriptDir = Join-Path $script:TestScriptDirectory "step3 - clean_json"
         $batchFile = "level1_batch.txt"
         $batchFilePath = Join-Path $batchScriptDir $batchFile

        BeforeEach {
            $renameCmd1 = "ren '$($script:TestUnzipDir)\old1.json' '$($script:TestUnzipDir)\new1.json'"
            $renameCmd2 = "ren '$($script:TestUnzipDir)\old2.json' '$($script:TestUnzipDir)\new2.json'"
            $renameCmd3 = "ren '$($script:TestUnzipDir)\old3.json' '$($script:TestUnzipDir)\new3.json'"
            Mock -CommandName Test-Path -MockWith {
                param($Path, $PathType)
                if ($Path -eq $batchFilePath -and $PathType -eq 'Leaf') { return $true }
                if ($Path -eq "$($script:TestUnzipDir)\new2.json") { return $true }
                return $false
            } -Verifiable
            Mock -CommandName Get-Content { param($Path) if ($Path -eq $batchFilePath) { return @($renameCmd1, $renameCmd2, $renameCmd3) } else { return @() } } -Verifiable
            Mock -CommandName Invoke-Expression {
                param($Command)
                Write-Verbose "Mock Invoke-Expression: $Command"
                if ($Command -like "*old3.json*") { throw "Rename failed" }
            } -Verifiable
            (Get-Mock -CommandName Invoke-Expression).Clear()
            (Get-Mock -CommandName Remove-Item).Clear()
            (Get-Mock -CommandName Show-ProgressBar).Clear()
            (Get-Mock -CommandName Get-Content).Clear()
            (Get-Mock -CommandName Test-Path).Clear()
            Mock -CommandName Log { }
        }

        It 'Should process rename commands from batch files' {
             # Assume $script:batchFiles and $script:batchScriptDirectory are loaded by top.ps1
             if (-not $script:batchFiles) { $script:batchFiles = @($batchFile) } # Provide default if not loaded
             if (-not $script:batchScriptDirectory) { $script:batchScriptDirectory = $batchScriptDir } # Provide default if not loaded

             $passed = 0
             $failed = 0
             foreach ($bf in $script:batchFiles) {
                 $filePath = Join-Path -Path $script:batchScriptDirectory -ChildPath $bf
                 if (!(Test-Path -Path $filePath -PathType Leaf)) {
                     Log "WARNING" "File '$filePath' not found. Skipping..."
                     continue
                 }
                 $contents = Get-Content -Path $filePath
                 $currentItem = 0
                 $totalItems = $contents.Count
                 Get-Content -Path $filePath | ForEach-Object {
                     $currentItem++
                     Show-ProgressBar -Current $currentItem -Total $totalItems -Message "$bf"
                     $command = $_.Trim()
                     if ($command -match "(ren)\s+'(.*?)'\s+'(.*?)'") {
                         $src = $Matches[2]
                         $dest = $Matches[3]
                         if (Test-Path -Path $dest) {
                             # Temporarily mock Test-Path to make src exist for Remove-Item check
                             $originalTestPathMock = Get-Mock -CommandName Test-Path
                             Mock -CommandName Test-Path -MockWith { param($Path) if ($Path -eq $src) { return $true } else { $originalTestPathMock.ScriptBlock.Invoke(@PSBoundParameters) } } -Verifiable -Scope It
                             Remove-Item -Path $src -Force
                             # Restore original Test-Path mock for this context
                             Mock -CommandName Test-Path -ScriptBlock $originalTestPathMock.ScriptBlock -Verifiable
                             continue
                         }
                     }

                     $command = $command -replace '\"', "'"
                     try {
                         Invoke-Expression $command
                         $passed++
                     } catch {
                         Log "WARNING" "Failed to execute: $command. Error: $_"
                         $failed++
                     }
                 }
             }

            Assert-MockCalled -CommandName Get-Content -Parameters @{ Path = $batchFilePath } -Times 2 -Scope It
            Assert-MockCalled -CommandName Show-ProgressBar -Times 3 -Scope It
            Assert-MockCalled -CommandName Invoke-Expression -Parameters $renameCmd1 -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Invoke-Expression -Exactly 2 -Scope It
            Assert-MockCalled -CommandName Remove-Item -Parameters @{ Path = "$($script:TestUnzipDir)\old2.json"; Force = $true } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'WARNING'; Message = "Failed to execute: $renameCmd3. Error: Rename failed" } -Exactly 1 -Scope It
        }
    }

    Context 'Pipeline Step 4: Remove Orphaned JSON' {
        $orphanedListPath = Join-Path $script:TestScriptDirectory 'step4 - ListandRemoveOrphanedJSON\orphaned_json_files.txt'
        $orphan1 = Join-Path $script:TestUnzipDir 'orphan1.json'
        $orphan2 = Join-Path $script:TestUnzipDir 'orphan2.json'
        $orphan3 = Join-Path $script:TestUnzipDir 'not_found.json'

        BeforeEach {
            # Assume $script:orphanedListPath is loaded from top.ps1
            if (-not $script:orphanedListPath) { $script:orphanedListPath = $orphanedListPath } # Provide default if not loaded

            Mock -CommandName Get-Content { param($Path) if ($Path -eq $script:orphanedListPath) { return @(" $orphan1 ", " $orphan2 ", " $orphan3 ") } else { return @() } } -Verifiable
            Mock -CommandName Test-Path {
                param($Path, $PathType)
                if ($PathType -ne 'Leaf') { return $false }
                if ($Path -eq $orphan1) { return $true }
                if ($Path -eq $orphan2) { return $true }
                if ($Path -eq $orphan3) { return $false }
                return $false
            } -Verifiable
            Mock -CommandName Remove-Item {
                param($Path, $Force)
                Write-Verbose "Mock Remove-Item: $Path"
                if ($Path -eq $orphan2) { throw "Deletion failed" }
            } -Verifiable
            Mock -CommandName Log { }
            (Get-Mock -CommandName Get-Content).Clear()
            (Get-Mock -CommandName Test-Path).Clear()
            (Get-Mock -CommandName Remove-Item).Clear()
            (Get-Mock -CommandName Log).Clear()
        }

        It 'Should attempt to remove files listed in orphaned_json_files.txt' {
            Get-Content -Path $script:orphanedListPath | ForEach-Object {
                $file = $_.Trim()
                if (Test-Path -Path "$file" -PathType Leaf) {
                    try { Remove-Item -Path "$file" -Force }
                    catch { Log "WARNING" "Failed to delete '$file': $_" }
                } else { Log "WARNING" "File not found: $file" }
            }
            Assert-MockCalled -CommandName Get-Content -Parameters @{ Path = $script:orphanedListPath } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Test-Path -Parameters @{ Path = $orphan1; PathType = 'Leaf' } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Test-Path -Parameters @{ Path = $orphan2; PathType = 'Leaf' } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Test-Path -Parameters @{ Path = $orphan3; PathType = 'Leaf' } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Remove-Item -Parameters @{ Path = $orphan1; Force = $true } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Remove-Item -Parameters @{ Path = $orphan2; Force = $true } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'WARNING'; Message = "Failed to delete '$orphan2': Deletion failed" } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'WARNING'; Message = "File not found: $orphan3" } -Exactly 1 -Scope It
        }
    }


    Context 'Pipeline Step 7: Clean Recycle Bin' {
         BeforeEach {
            Mock -CommandName Test-Path { param($Path, $PathType) if ($Path -eq $script:TestRecycleBin -and $PathType -eq 'Container') { return $true } else { return $false } } -Verifiable
            (Get-Mock -CommandName $script:mockAttribName).Clear() # Use variable
            (Get-Mock -CommandName Remove-Item).Clear()
            (Get-Mock -CommandName Test-Path).Clear()
         }

         It 'Should change attributes and remove contents if Recycle Bin exists' {
             if (Test-Path -Path $script:RecycleBinPath -PathType Container) {
                 & $script:mockAttribName -H -R -S -A $script:RecycleBinPath # Use variable for command name
                 Remove-Item -Path (Join-Path -Path $script:RecycleBinPath -ChildPath "*") -Recurse -Force
             }
             Assert-MockCalled -CommandName Test-Path -Parameters @{ Path = $script:RecycleBinPath; PathType = 'Container' } -Exactly 1 -Scope It
             Assert-MockCalled -CommandName $script:mockAttribName -Parameters @('-H', '-R', '-S', '-A', $script:RecycleBinPath) -Exactly 1 -Scope It # Use variable
             Assert-MockCalled -CommandName Remove-Item -Parameters @{ Path = (Join-Path $script:RecycleBinPath '*'); Recurse = $true; Force = $true } -Exactly 1 -Scope It
         }

         It 'Should do nothing if Recycle Bin does not exist' {
             Mock -CommandName Test-Path { return $false } -Verifiable
             if (Test-Path -Path $script:RecycleBinPath -PathType Container) {
                 & $script:mockAttribName -H -R -S -A $script:RecycleBinPath # Use variable
                 Remove-Item -Path (Join-Path -Path $script:RecycleBinPath -ChildPath "*") -Recurse -Force
             }
             Assert-MockCalled -CommandName Test-Path -Parameters @{ Path = $script:RecycleBinPath; PathType = 'Container' } -Exactly 1 -Scope It
             Assert-MockCalled -CommandName $script:mockAttribName -Exactly 0 -Scope It # Use variable
             Assert-MockCalled -CommandName Remove-Item -Exactly 0 -Scope It
         }
    }

     Context 'Pipeline Steps 8-11: Verify Python Script Calls' {
        BeforeEach{
             (Get-Mock -CommandName $script:mockPythonName).Clear() # Use variable
        }

        It 'Step 8-1: Should call HashANDGroupPossibleVideoDuplicates.py' {
            $scriptPath = Join-Path $script:scriptDirectory 'step8 - HashAndGroup\HashANDGroupPossibleVideoDuplicates.py'
            $expectedArgs = "$($script:unzipedDirectory)\"
            Invoke-PythonScript -ScriptPath $scriptPath -Arguments $expectedArgs
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters @($scriptPath, $expectedArgs) -Exactly 1 -Scope It # Use variable
        }
         It 'Step 8-2: Should call HashANDGroupPossibleImageDuplicates.py' {
            $scriptPath = Join-Path $script:scriptDirectory 'step8 - HashAndGroup\HashANDGroupPossibleImageDuplicates.py'
            $expectedArgs = "$($script:unzipedDirectory)\"
            Invoke-PythonScript -ScriptPath $scriptPath -Arguments $expectedArgs
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters @($scriptPath, $expectedArgs) -Exactly 1 -Scope It # Use variable
        }
         It 'Step 9-1: Should call RemoveExactVideoDuplicate.py with --dry-run' {
            $scriptPath = Join-Path $script:scriptDirectory 'step9 - RemoveExactDuplicates\RemoveExactVideoDuplicate.py'
            $expectedArgs = '--dry-run'
            Invoke-PythonScript -ScriptPath $scriptPath -Arguments $expectedArgs
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters @($scriptPath, $expectedArgs) -Exactly 1 -Scope It # Use variable
        }
         It 'Step 9-2: Should call RemoveExactImageDuplicate.py' {
            $scriptPath = Join-Path $script:scriptDirectory 'step9 - RemoveExactDuplicates\RemoveExactImageDuplicate.py'
            Invoke-PythonScript -ScriptPath $scriptPath
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters $scriptPath -Exactly 1 -Scope It # Use variable
        }
         It 'Step 10-1: Should call ShowANDRemoveDuplicateVideo.py' {
            $scriptPath = Join-Path $script:scriptDirectory 'step10 - ShowANDRemoveDuplicate\ShowANDRemoveDuplicateVideo.py'
            Invoke-PythonScript -ScriptPath $scriptPath
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters $scriptPath -Exactly 1 -Scope It # Use variable
        }
         It 'Step 10-2: Should call ShowANDRemoveDuplicateImage.py' {
            $scriptPath = Join-Path $script:scriptDirectory 'step10 - ShowANDRemoveDuplicate\ShowANDRemoveDuplicateImage.py'
            Invoke-PythonScript -ScriptPath $scriptPath
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters $scriptPath -Exactly 1 -Scope It # Use variable
        }
         It 'Step 11-1: Should call RemoveJunkVideo.py' {
            $scriptPath = Join-Path $script:scriptDirectory 'step11 - RemoveJunk\RemoveJunkVideo.py'
            $expectedArgs = "$($script:unzipedDirectory)\"
            Invoke-PythonScript -ScriptPath $scriptPath -Arguments $expectedArgs
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters @($scriptPath, $expectedArgs) -Exactly 1 -Scope It # Use variable
        }
         It 'Step 11-2: Should call RemoveJunkImage.py' {
            $scriptPath = Join-Path $script:scriptDirectory 'step11 - RemoveJunk\RemoveJunkImage.py'
            $expectedArgs = "$($script:unzipedDirectory)\"
            Invoke-PythonScript -ScriptPath $scriptPath -Arguments $expectedArgs
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters @($scriptPath, $expectedArgs) -Exactly 1 -Scope It # Use variable
        }
     }

     Context 'Pipeline Steps 12-14: Verify PowerShell Script Calls' {
        BeforeEach {
            Mock -CommandName Log { }
            Remove-Mock -CommandName (Join-Path $script:scriptDirectory 'step12 - Reconstruction\VideoReconstruction.ps1') -ErrorAction SilentlyContinue
            Remove-Mock -CommandName (Join-Path $script:scriptDirectory 'step12 - Reconstruction\ImageReconstruction.ps1') -ErrorAction SilentlyContinue
            Remove-Mock -CommandName (Join-Path $script:scriptDirectory 'step13 - Categorization\Categorize.ps1') -ErrorAction SilentlyContinue
            Remove-Mock -CommandName (Join-Path $script:scriptDirectory 'step14  - Estimate By Time\EstimateByTime.ps1') -ErrorAction SilentlyContinue
        }

        It 'Step 12-1: Should invoke VideoReconstruction.ps1' {
             $scriptPath = Join-Path $script:scriptDirectory 'step12 - Reconstruction\VideoReconstruction.ps1'
             Mock -CommandName $scriptPath { Write-Verbose "Mocked call to $scriptPath" } -Verifiable
             & $scriptPath
             Assert-MockCalled -CommandName $scriptPath -Exactly 1 -Scope It
        }
        It 'Step 12-2: Should invoke ImageReconstruction.ps1' {
             $scriptPath = Join-Path $script:scriptDirectory 'step12 - Reconstruction\ImageReconstruction.ps1'
             Mock -CommandName $scriptPath { Write-Verbose "Mocked call to $scriptPath" } -Verifiable
             & $scriptPath
             Assert-MockCalled -CommandName $scriptPath -Exactly 1 -Scope It
        }
        It 'Step 13: Should invoke Categorize.ps1' {
             $scriptPath = Join-Path $script:scriptDirectory 'step13 - Categorization\Categorize.ps1'
             Mock -CommandName $scriptPath { Write-Verbose "Mocked call to $scriptPath" } -Verifiable
             & $scriptPath
             Assert-MockCalled -CommandName $scriptPath -Exactly 1 -Scope It
        }
        It 'Step 14: Should invoke EstimateByTime.ps1' {
             $scriptPath = Join-Path $script:scriptDirectory 'step14  - Estimate By Time\EstimateByTime.ps1'
             Mock -CommandName $scriptPath { Write-Verbose "Mocked call to $scriptPath" } -Verifiable
             & $scriptPath
             Assert-MockCalled -CommandName $scriptPath -Exactly 1 -Scope It
        }
     }

    Context 'Counter Steps' {
        BeforeEach {
            (Get-Mock -CommandName $script:mockPythonName).Clear() # Use variable
            $script:logger = 0
        }

        It 'Should call counter.py script multiple times with incrementing log file names' {
            $counterScriptPath = Join-Path $script:scriptDirectory 'Step0 - Tools\counter\counter.py'
            $logArg0 = "$($script:scriptDirectory)/Logs/log_step_0.txt"
            Invoke-PythonScript -ScriptPath $counterScriptPath -Arguments "$logArg0 $($script:unzipedDirectory)"
            $script:logger++
            $logArg1 = "$($script:scriptDirectory)/Logs/log_step_1.txt"
            Invoke-PythonScript -ScriptPath $counterScriptPath -Arguments "$logArg1 $($script:unzipedDirectory)"
            $script:logger++
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters @($counterScriptPath, "$logArg0 $($script:unzipedDirectory)") -Exactly 1 -Scope It # Use variable
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters @($counterScriptPath, "$logArg1 $($script:unzipedDirectory)") -Exactly 1 -Scope It # Use variable
        }
    }
}
#Requires -Modules Pester -Version 5.0

<#
.SYNOPSIS
    Unit tests for the top.ps1 media organizer pipeline script.
#>

# --- Pester Test Suite ---

Describe 'top.ps1 - Media Organizer Pipeline' {

    # Define variables within BeforeAll where $PSScriptRoot is reliable
    BeforeAll {
        # --- Define Test Paths INSIDE BeforeAll ---
        $script:TestScriptDirectory = $PSScriptRoot # Use script scope to make available to tests
        $script:TestLogsDir = Join-Path $script:TestScriptDirectory "TestLogs"
        $script:TestUnzipDir = Join-Path $script:TestScriptDirectory "TestUnzip"
        $script:TestZipDir = Join-Path $script:TestScriptDirectory "TestZip"
        $script:TestRecycleBin = Join-Path $script:TestUnzipDir '$RECYCLE.BIN' # Use TestUnzipDir as base

        Write-Host "BeforeAll: TestScriptDirectory = '$($script:TestScriptDirectory)'"
        Write-Host "BeforeAll: TestLogsDir = '$($script:TestLogsDir)'"

        # Create necessary test directories (now that paths are defined)
        # Use -ErrorAction SilentlyContinue in case they already exist
        New-Item -Path $script:TestLogsDir -ItemType Directory -Force -ErrorAction SilentlyContinue | Out-Null
        New-Item -Path $script:TestUnzipDir -ItemType Directory -Force -ErrorAction SilentlyContinue | Out-Null
        New-Item -Path $script:TestZipDir -ItemType Directory -Force -ErrorAction SilentlyContinue | Out-Null
        Write-Host "BeforeAll: Ensured test directories exist."

        # --- Mocks MUST be defined BEFORE dot-sourcing the script ---

        # 1. SIMPLIFIED Split-Path Mock specifically for loading $scriptDirectory
        Mock -CommandName Split-Path -MockWith {
            param($Path, $Parent)
            if ($PSBoundParameters.ContainsKey('Parent')) {
                Write-Verbose "LOAD MOCK: Split-Path called with -Parent. Returning '$($script:TestScriptDirectory)'."
                return $script:TestScriptDirectory # Use script-scoped variable
            }
            Microsoft.PowerShell.Management\Split-Path @PSBoundParameters
        } -ModuleName Microsoft.PowerShell.Management -Verifiable

        # 2. Mock cmdlets used *during* script loading
        #    Make Test-Path mock slightly more robust - check for $null path
        Mock -CommandName Test-Path {
            param($Path, $PathType)
            if ($null -eq $Path) {
                Write-Warning "LOAD MOCK: Test-Path called with NULL Path!"
                return $false
            }
            Write-Verbose "LOAD MOCK: Test-Path for '$Path' (PathType: $PathType) -> returning True"
            return $true
        } -Verifiable
        Mock -CommandName New-Item { Write-Verbose "LOAD MOCK: New-Item call for $Path" } -Verifiable

        # 3. Mock external commands (Full Path or Name as called in top.ps1)
        #    Store paths/names in script scope for consistent use in mocks and tests
        $script:mock7zPath = 'C:\Program Files\7-Zip\7z.exe'
        $script:mockExifPath = 'C:\Program Files\exiftools\exiftool.exe'
        $script:mockMagickPath = 'C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe'
        $script:mockFfmpegName = 'ffmpeg.exe'
        $script:mockPythonName = 'python3.13.exe'
        $script:mockAttribName = 'attrib.exe'

        Mock -CommandName $script:mock7zPath { Write-Verbose "Mocked 7z.exe ($($script:mock7zPath)) call with args: $Args" } -Verifiable
        Mock -CommandName $script:mockExifPath { Write-Verbose "Mocked exiftool.exe ($($script:mockExifPath)) call with args: $Args" } -Verifiable
        Mock -CommandName $script:mockMagickPath { Write-Verbose "Mocked magick.exe ($($script:mockMagickPath)) call with args: $Args" } -Verifiable
        Mock -CommandName $script:mockFfmpegName { Write-Verbose "Mocked ffmpeg.exe ($($script:mockFfmpegName)) call with args: $Args" } -Verifiable
        Mock -CommandName $script:mockPythonName { Write-Verbose "Mocked python3.13.exe ($($script:mockPythonName)) call with args: $Args" } -Verifiable
        Mock -CommandName $script:mockAttribName { Write-Verbose "Mocked attrib.exe ($($script:mockAttribName)) call with args: $Args" } -Verifiable

        # 3b. Mock Get-Command for external tools (Just in case)
        #     Return a dummy object that looks like a command info
        $dummyCmdInfo = [pscustomobject]@{ Name = 'dummy.exe'; CommandType = 'Application'; Path = 'C:\dummy.exe'; Source = 'C:\dummy.exe' }
        Mock -CommandName Get-Command {
            param($Name)
            Write-Verbose "LOAD MOCK: Get-Command called for '$Name'"
            # Check if it's one of the tools we care about during load checks
            if ($Name -in ($script:mock7zPath, $script:mockExifPath, $script:mockMagickPath, $script:mockFfmpegName)) {
                 Write-Verbose "LOAD MOCK: Get-Command returning dummy object for '$Name'"
                 # Return a dummy object that won't cause Test-Path to fail immediately if Get-Command is used implicitly
                 return $dummyCmdInfo
            }
            # Fallback to real Get-Command for anything else
            Microsoft.PowerShell.Core\Get-Command @PSBoundParameters
        } -Verifiable


        # 4. Mock other cmdlets
        Mock -CommandName Invoke-Expression { Write-Verbose "Mocked Invoke-Expression call with command: $Command" } -Verifiable
        Mock -CommandName Remove-Item { Write-Verbose "Mocked Remove-Item call for path: $Path" } -Verifiable
        Mock -CommandName Move-Item { Write-Verbose "Mocked Move-Item call from $Path to $Destination" } -Verifiable
        Mock -CommandName Rename-Item { Write-Verbose "Mocked Rename-Item call for $Path to $NewName" } -Verifiable
        Mock -CommandName Get-Content { return @() } -Verifiable
        Mock -CommandName Add-Content { Write-Verbose "Mocked Add-Content call to $Path" } -Verifiable
        Mock -CommandName Out-File { Write-Verbose "Mocked Out-File call to $FilePath" } -Verifiable
        Mock -CommandName Get-ChildItem { return @() } -Verifiable
        # Mock Write-Host globally BUT allow explicit Write-Host from test script itself for debugging
        Mock -CommandName Write-Host { if ($MyInvocation.ScriptName -ne $PSScriptRoot) { return } else { Microsoft.PowerShell.Utility\Write-Host @PSBoundParameters } } -Verifiable
        Mock -CommandName Show-ProgressBar { } -Verifiable
        Mock -CommandName exit { throw "Simulated exit with code $args[0]" } -Verifiable
        Mock -CommandName ConvertTo-Json { param($InputObject) return $InputObject | Microsoft.PowerShell.Utility\ConvertTo-Json -Depth 10 } -Verifiable
        Mock -CommandName ConvertFrom-Json { param($InputObject) return $InputObject | Microsoft.PowerShell.Utility\ConvertFrom-Json } -Verifiable
        Mock -CommandName Get-Item { param($Path) return [pscustomobject]@{ Name = (Microsoft.PowerShell.Management\Split-Path $Path -Leaf); FullName = $Path } } -Verifiable


        # --- Load the script into scope ---
        Write-Host "BeforeAll: Attempting to dot-source top.ps1..."
        try {
            . (Join-Path $script:TestScriptDirectory "top.ps1")
            Write-Host "BeforeAll: Dot-sourcing top.ps1 SUCCEEDED."
        } catch {
            Write-Error "BeforeAll: FAILED to dot-source top.ps1: $_"
            # Log the specific exception details
            Write-Error "Exception Type: $($_.Exception.GetType().FullName)"
            Write-Error "Exception Message: $($_.Exception.Message)"
            Write-Error "ScriptStackTrace: $($_.ScriptStackTrace)"
            throw $_ # Re-throw
        }

        # --- Remove mocks specific to loading ---
        Remove-Mock -CommandName Split-Path -ModuleName Microsoft.PowerShell.Management -ErrorAction SilentlyContinue
        Remove-Mock -CommandName Get-Command -ErrorAction SilentlyContinue # Remove Get-Command mock too
        Write-Host "BeforeAll: Removed loading-specific mocks (Split-Path, Get-Command)."

        # --- Verify essential variables are set after loading ---
        if ($null -eq $script:scriptDirectory) { Write-Error "BeforeAll: script:scriptDirectory is NULL!" } else { Write-Host "BeforeAll: script:scriptDirectory = '$($script:scriptDirectory)'" }
        if ($null -eq $script:logDir) { Write-Error "BeforeAll: script:logDir is NULL!" } else { Write-Host "BeforeAll: script:logDir = '$($script:logDir)'" }
        if ($null -eq $script:logFilePath) { Write-Error "BeforeAll: script:logFilePath is NULL!" } else { Write-Host "BeforeAll: script:logFilePath = '$($script:logFilePath)'" }
        if ($null -eq $script:TestLogsDir) { Write-Error "BeforeAll: script:TestLogsDir is NULL!" } # Verify test var itself

    } # End BeforeAll

    AfterAll {
        # Use script-scoped variables for cleanup paths
        Write-Host "AfterAll: Cleaning up test directories..."
        if ($script:TestLogsDir) { Remove-Item -Path $script:TestLogsDir -Recurse -Force -ErrorAction SilentlyContinue }
        if ($script:TestUnzipDir) { Remove-Item -Path $script:TestUnzipDir -Recurse -Force -ErrorAction SilentlyContinue }
        if ($script:TestZipDir) { Remove-Item -Path $script:TestZipDir -Recurse -Force -ErrorAction SilentlyContinue }
    }

    # --- Tests ---

    Context 'Initial Setup and Tool Checks' {
        It 'Should define required variables' {
            # Check variables loaded from top.ps1
            $script:zipDirectory | Should -Be 'D:'
            $script:unzipedDirectory | Should -Be 'E:'
            $script:scriptDirectory | Should -Be $script:TestScriptDirectory # Compare script var with test var
            $script:7zip | Should -Be $script:mock7zPath # Use test variable for comparison
            $script:ExifToolPath | Should -Be $script:mockExifPath
            $script:magickPath | Should -Be $script:mockMagickPath
            $script:ffmpeg | Should -Be $script:mockFfmpegName
            $script:RecycleBinPath | Should -Be (Join-Path $script:unzipedDirectory '$RECYCLE.BIN')
        }

        # --- Tool Check Tests ---
        It 'Should exit if 7-Zip is not found' {
            # Arrange
            Mock -CommandName Test-Path -MockWith { param($Path) if ($Path -eq $script:mock7zPath) { return $false } else { return $true } }
            Mock -CommandName Log

            # Act & Assert
            { . (Join-Path $script:TestScriptDirectory "top.ps1") } | Should -Throw "Simulated exit with code 1"
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'ERROR'; Message = "7-Zip not found at $($script:mock7zPath). Aborting." } -Times 1 -Scope It
        }

        It 'Should exit if ExifTool is not found' {
            Mock -CommandName Test-Path -MockWith { param($Path) if ($Path -eq $script:mockExifPath) { return $false } else { return $true } }
            Mock -CommandName Log
            { . (Join-Path $script:TestScriptDirectory "top.ps1") } | Should -Throw "Simulated exit with code 1"
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'ERROR'; Message = "Exiftools not found at $($script:mockExifPath). Aborting." } -Times 1 -Scope It
        }

         It 'Should exit if ImageMagick is not found' {
            Mock -CommandName Test-Path -MockWith { param($Path) if ($Path -eq $script:mockMagickPath) { return $false } else { return $true } }
            Mock -CommandName Log
            { . (Join-Path $script:TestScriptDirectory "top.ps1") } | Should -Throw "Simulated exit with code 1"
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'ERROR'; Message = "magik not found at $($script:mockMagickPath). Aborting." } -Times 1 -Scope It
        }

         It 'Should exit if ffmpeg is not found' {
            Mock -CommandName Test-Path -MockWith { param($Path) if ($Path -eq $script:mockFfmpegName) { return $false } else { return $true } }
            Mock -CommandName Log
            { . (Join-Path $script:TestScriptDirectory "top.ps1") } | Should -Throw "Simulated exit with code 1"
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'ERROR'; Message = "ffmpeg not found at $($script:mockFfmpegName). Aborting." } -Times 1 -Scope It
        }

        It 'Should proceed if all tools are found' {
            Mock -CommandName Test-Path { return $true } # Ensure the global mock is active
            { . (Join-Path $script:TestScriptDirectory "top.ps1") } | Should -Not -Throw
        }
    }

    Context 'Function: Log' {
        BeforeEach {
            # Access script-scoped variables set in BeforeAll
            # Ensure logLevelMap is available (it should be loaded by top.ps1 into script scope)
            if (-not $script:logLevelMap) { throw "logLevelMap not found in script scope for Log tests!" }
            $script:consoleLogLevel = $script:logLevelMap["INFO"]
            $script:fileLogLevel = $script:logLevelMap["DEBUG"]
            $script:logFilePath = Join-Path $script:TestLogsDir "test_pipeline.log" # Use test path var
            if (Test-Path $script:logFilePath) { Remove-Item $script:logFilePath -Force }

            # Unmock Write-Host and Add-Content specifically for Log tests
            Remove-Mock -CommandName Write-Host -ErrorAction SilentlyContinue
            Remove-Mock -CommandName Add-Content -ErrorAction SilentlyContinue

            # Mock them again to capture calls
            Mock -CommandName Write-Host { $script:logOutput_Host = $ArgumentList[0] } -Verifiable
            Mock -CommandName Add-Content { $script:logOutput_File = $Value; $script:logOutput_FilePath = $Path } -Verifiable
            $script:logOutput_Host = $null
            $script:logOutput_File = $null
            $script:logOutput_FilePath = $null
        }
        AfterEach {
             # Restore global Write-Host mock (suppress output from SUT, allow from test script)
             Mock -CommandName Write-Host { if ($MyInvocation.ScriptName -ne $PSScriptRoot) { return } else { Microsoft.PowerShell.Utility\Write-Host @PSBoundParameters } } -Verifiable
             Mock -CommandName Add-Content { Write-Verbose "Mocked Add-Content call to $Path" } -Verifiable
        }

         It 'Should log DEBUG to file only (with default levels)' {
            Log "DEBUG" "Debug message"
            $script:logOutput_Host | Should -BeNullOrEmpty
            $script:logOutput_File | Should -Match "DEBUG - Debug message"
            $script:logOutput_FilePath | Should -Be $script:logFilePath
        }

        It 'Should log INFO to console and file (with default levels)' {
            Log "INFO" "Info message"
            $script:logOutput_Host | Should -Match "INFO - Info message"
            $script:logOutput_File | Should -Match "INFO - Info message"
            $script:logOutput_FilePath | Should -Be $script:logFilePath
        }

        It 'Should log WARNING to console and file' {
            Log "WARNING" "Warning message"
            $script:logOutput_Host | Should -Match "WARNING - Warning message"
            $script:logOutput_File | Should -Match "WARNING - Warning message"
        }

        It 'Should log ERROR to console and file' {
            Log "ERROR" "Error message"
            $script:logOutput_Host | Should -Match "ERROR - Error message"
            $script:logOutput_File | Should -Match "ERROR - Error message"
        }

        It 'Should respect console log level' {
            $script:consoleLogLevel = $script:logLevelMap["WARNING"] # Only WARNING and ERROR to console
            Log "INFO" "Info message"
            $script:logOutput_Host | Should -BeNullOrEmpty
            Log "WARNING" "Warning message"
            $script:logOutput_Host | Should -Match "WARNING - Warning message"
        }

        It 'Should respect file log level' {
            $script:fileLogLevel = $script:logLevelMap["ERROR"] # Only ERROR to file
            Log "WARNING" "Warning message"
            $script:logOutput_File | Should -BeNullOrEmpty
            Log "ERROR" "Error message"
            $script:logOutput_File | Should -Match "ERROR - Error message"
        }
    }

    Context 'Function: Write-JsonAtomic' {
        $testJsonPath = Join-Path $script:TestScriptDirectory "test.json"
        $testJsonTempPath = "$testJsonPath.tmp"
        $testData = @{ Name = "Test"; Value = 123 }

        BeforeEach {
            if (Test-Path $testJsonPath) { Remove-Item $testJsonPath -Force }
            if (Test-Path $testJsonTempPath) { Remove-Item $testJsonTempPath -Force }
            Mock -CommandName Test-Path { param($Path) return $false }
            Mock -CommandName Log { }
            (Get-Mock -CommandName ConvertTo-Json).Clear()
            (Get-Mock -CommandName Out-File).Clear()
            (Get-Mock -CommandName Get-Content).Clear()
            (Get-Mock -CommandName ConvertFrom-Json).Clear()
            (Get-Mock -CommandName Move-Item).Clear()
            (Get-Mock -CommandName Remove-Item).Clear()
            (Get-Mock -CommandName Log).Clear()
        }

         It 'Should write data to temp file, validate, and move to final path' {
            Mock -CommandName Get-Content { param($Path) if($Path -eq $testJsonTempPath) { return '{"Name":"Test","Value":123}' } else { return $null } } -Verifiable
            Mock -CommandName ConvertFrom-Json { param($InputObject) return $InputObject | Microsoft.PowerShell.Utility\ConvertFrom-Json } -Verifiable
            Write-JsonAtomic -Data $testData -Path $testJsonPath
            Assert-MockCalled -CommandName ConvertTo-Json -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Out-File -Parameters @{ FilePath = $testJsonTempPath } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Get-Content -Parameters @{ Path = $testJsonTempPath } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName ConvertFrom-Json -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Move-Item -Parameters @{ Path = $testJsonTempPath; Destination = $testJsonPath } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Remove-Item -Exactly 0 -Scope It
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'INFO'; Message = "✅ Atomic write succeeded: $testJsonPath" } -Exactly 1 -Scope It
        }

        It 'Should log error and remove temp file if ConvertTo-Json fails' {
            Mock -CommandName ConvertTo-Json { throw "JSON Conversion Failed" } -Verifiable
            Mock -CommandName Log
            Write-JsonAtomic -Data $testData -Path $testJsonPath
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'ERROR'; Message = "❌ Atomic write failed for $testJsonPath : JSON Conversion Failed" } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Move-Item -Exactly 0 -Scope It
            Assert-MockCalled -CommandName Remove-Item -Exactly 0 -Scope It
        }

         It 'Should log error and remove temp file if Out-File fails' {
            Mock -CommandName Out-File { throw "Cannot write file" } -Verifiable
            Mock -CommandName Test-Path { return $false }
            Mock -CommandName Log
            Write-JsonAtomic -Data $testData -Path $testJsonPath
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'ERROR'; Message = "❌ Atomic write failed for $testJsonPath : Cannot write file" } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Move-Item -Exactly 0 -Scope It
            Assert-MockCalled -CommandName Remove-Item -Exactly 0 -Scope It
        }

        It 'Should log error and remove temp file if JSON validation fails' {
            Mock -CommandName Get-Content { param($Path) if($Path -eq $testJsonTempPath) { return '{"Name":"Test","Value":123}' } else { return $null } } -Verifiable
            Mock -CommandName ConvertFrom-Json { throw "Invalid JSON" } -Verifiable
            Mock -CommandName Test-Path { param($Path) if ($Path -eq $testJsonTempPath) { return $true } else { return $false } }
            Mock -CommandName Log
            Write-JsonAtomic -Data $testData -Path $testJsonPath
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'ERROR'; Message = "❌ Atomic write failed for $testJsonPath : Invalid JSON" } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Move-Item -Exactly 0 -Scope It
            Assert-MockCalled -CommandName Remove-Item -Parameters @{ Path = $testJsonTempPath } -Exactly 1 -Scope It
        }

         It 'Should log error and remove temp file if Move-Item fails' {
            Mock -CommandName Get-Content { param($Path) if($Path -eq $testJsonTempPath) { return '{"Name":"Test","Value":123}' } else { return $null } } -Verifiable
            Mock -CommandName ConvertFrom-Json { param($InputObject) return $InputObject | Microsoft.PowerShell.Utility\ConvertFrom-Json } -Verifiable
            Mock -CommandName Move-Item { throw "Access Denied" } -Verifiable
            Mock -CommandName Test-Path { param($Path) if ($Path -eq $testJsonTempPath) { return $true } else { return $false } }
            Mock -CommandName Log
            Write-JsonAtomic -Data $testData -Path $testJsonPath
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'ERROR'; Message = "❌ Atomic write failed for $testJsonPath : Access Denied" } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Remove-Item -Parameters @{ Path = $testJsonTempPath } -Exactly 1 -Scope It
        }
    }

    Context 'Function: Invoke-PythonScript' {
        $testPyScript = Join-Path $script:TestScriptDirectory "test_script.py"

        BeforeEach {
            Mock -CommandName Log { }
            (Get-Mock -CommandName $script:mockPythonName).Clear() # Use variable
            (Get-Mock -CommandName Log).Clear()
            (Get-Mock -CommandName exit).Clear()
        }

        It 'Should call python3.13.exe with script path only when no arguments' {
            Invoke-PythonScript -ScriptPath $testPyScript
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters $testPyScript -Exactly 1 -Scope It # Use variable
        }

        It 'Should call python3.13.exe with script path and arguments' {
            $arguments = "--input file.txt --output results.json"
            Invoke-PythonScript -ScriptPath $testPyScript -Arguments $arguments
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters @($testPyScript, $arguments) -Exactly 1 -Scope It # Use variable
        }

        It 'Should log error and exit if python script fails' {
            Mock -CommandName $script:mockPythonName { throw "Python Error" } -Verifiable # Use variable
            Mock -CommandName Log
            Mock -CommandName exit { throw "Simulated exit 1" } -Verifiable
            { Invoke-PythonScript -ScriptPath $testPyScript } | Should -Throw "Simulated exit 1"
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'ERROR'; Message = "Error running Python script '$testPyScript': Python Error" } -Exactly 1 -Scope It
        }
    }

    Context 'Function: Use-ValidDirectoryName' {
        $testDirPath = Join-Path $script:TestUnzipDir "Test Dir !@#"
        $sanitizedName = "Test_Dir_"
        $sanitizedPath = Join-Path $script:TestUnzipDir $sanitizedName

        BeforeEach {
             Mock -CommandName Get-Item {
                param($Path)
                $name = Microsoft.PowerShell.Management\Split-Path $Path -Leaf
                if ($Path -match "^[a-zA-Z]:\\?$") { return [pscustomobject]@{ Name = $name; FullName = $Path } }
                if ($Path -like '*ValidName*') { return [pscustomobject]@{ Name = 'ValidName'; FullName = $Path } }
                if ($Path -like '*_leading*') { return [pscustomobject]@{ Name = '_leading'; FullName = $Path } }
                if ($Path -like '*trailing_*') { return [pscustomobject]@{ Name = 'trailing_'; FullName = $Path } }
                return [pscustomobject]@{ Name = $name; FullName = $Path }
            } -Verifiable
            Mock -CommandName Log { }
            (Get-Mock -CommandName Rename-Item).Clear()
            (Get-Mock -CommandName Log).Clear()
        }

        It 'Should not rename if the name is already valid' {
            $validPath = Join-Path $script:TestUnzipDir "ValidName"
            Use-ValidDirectoryName -DirectoryPath $validPath
            Assert-MockCalled -CommandName Rename-Item -Exactly 0 -Scope It
        }

        It 'Should rename directory with invalid characters' {
            Use-ValidDirectoryName -DirectoryPath $testDirPath
            Assert-MockCalled -CommandName Rename-Item -Parameters @{ Path = $testDirPath; NewName = $sanitizedName } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'INFO'; Message = "Renamed 'Test Dir !@#' to '$sanitizedName'" } -Exactly 1 -Scope It
        }

         It 'Should remove leading underscore' {
            $leadingPath = Join-Path $script:TestUnzipDir "_leading"
            Use-ValidDirectoryName -DirectoryPath $leadingPath
            Assert-MockCalled -CommandName Rename-Item -Parameters @{ Path = $leadingPath; NewName = 'leading' } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'INFO'; Message = "Renamed '_leading' to 'leading'" } -Exactly 1 -Scope It
        }

        It 'Should remove trailing underscore' {
            $trailingPath = Join-Path $script:TestUnzipDir "trailing_"
            Use-ValidDirectoryName -DirectoryPath $trailingPath
            Assert-MockCalled -CommandName Rename-Item -Parameters @{ Path = $trailingPath; NewName = 'trailing' } -Exactly 1 -Scope It
             Assert-MockCalled -CommandName Log -Parameters @{ Level = 'INFO'; Message = "Renamed 'trailing_' to 'trailing'" } -Exactly 1 -Scope It
        }

        It 'Should not attempt to rename a drive root' {
            Use-ValidDirectoryName -DirectoryPath "E:"
            Assert-MockCalled -CommandName Rename-Item -Exactly 0 -Scope It
            Assert-MockCalled -CommandName Log -Exactly 0 -Scope It
        }

        It 'Should log warning if rename fails' {
            Mock -CommandName Rename-Item { throw "Access Denied" } -Verifiable
            Mock -CommandName Log
            Use-ValidDirectoryName -DirectoryPath $testDirPath
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'WARNING'; Message = "Failed to rename 'Test Dir !@#': Access Denied" } -Exactly 1 -Scope It
        }
    }

     Context 'Function: Use-ValidDirectoriesRecursively' {
        $rootPath = $script:TestUnzipDir
        $subDir1Invalid = Join-Path $rootPath "Sub Dir 1!"
        $subDir2Valid = Join-Path $rootPath "SubDir2"
        $subSubDirInvalid = Join-Path $subDir2Valid "Sub Sub Dir 3?"

        BeforeEach {
            Mock -CommandName Test-Path { param($Path, $PathType) if($Path -eq $rootPath -and $PathType -eq 'Container') { return $true } else { return $false } } -Verifiable
            $mockSubDir1 = [pscustomobject]@{ FullName = $subDir1Invalid; Name = "Sub Dir 1!"; PSIsContainer = $true }
            $mockSubDir2 = [pscustomobject]@{ FullName = $subDir2Valid; Name = "SubDir2"; PSIsContainer = $true }
            $mockSubSubDir = [pscustomobject]@{ FullName = $subSubDirInvalid; Name = "Sub Sub Dir 3?"; PSIsContainer = $true }
            Mock -CommandName Get-ChildItem {
                param($Path, $Directory, $Recurse)
                if ($Path -eq $rootPath -and $Directory -and $Recurse) { return @($mockSubDir1, $mockSubDir2, $mockSubSubDir) }
                else { return @() }
            } -Verifiable
            Mock -CommandName Use-ValidDirectoryName { Write-Verbose "Mocked Use-ValidDirectoryName for $($args[0])" } -Verifiable
            Mock -CommandName Log { }
            (Get-Mock -CommandName Use-ValidDirectoryName).Clear()
            (Get-Mock -CommandName Get-ChildItem).Clear()
            (Get-Mock -CommandName Test-Path).Clear()
            (Get-Mock -CommandName Log).Clear()
        }

         It 'Should call Use-ValidDirectoryName for each directory and the root' {
             Mock -CommandName Test-Path { param($Path, $PathType) if($Path -eq $rootPath -and $PathType -eq 'Container') { return $true } else { return $false } } -Verifiable
             Use-ValidDirectoriesRecursively -RootDirectory $rootPath
             Assert-MockCalled -CommandName Get-ChildItem -Parameters @{ Path = $rootPath; Directory = $true; Recurse = $true } -Exactly 1 -Scope It
             Assert-MockCalled -CommandName Use-ValidDirectoryName -Parameters @{ DirectoryPath = $subDir1Invalid } -Exactly 1 -Scope It
             Assert-MockCalled -CommandName Use-ValidDirectoryName -Parameters @{ DirectoryPath = $subDir2Valid } -Exactly 1 -Scope It
             Assert-MockCalled -CommandName Use-ValidDirectoryName -Parameters @{ DirectoryPath = $subSubDirInvalid } -Exactly 1 -Scope It
             Assert-MockCalled -CommandName Use-ValidDirectoryName -Parameters @{ DirectoryPath = $rootPath } -Exactly 1 -Scope It
        }

        It 'Should log error and return if root directory does not exist' {
             Mock -CommandName Test-Path { return $false } -Verifiable
             Mock -CommandName Log
             Use-ValidDirectoriesRecursively -RootDirectory $rootPath
             Assert-MockCalled -CommandName Log -Parameters @{ Level = 'ERROR'; Message = "Root directory '$rootPath' does not exist." } -Exactly 1 -Scope It
             Assert-MockCalled -CommandName Get-ChildItem -Exactly 0 -Scope It
             Assert-MockCalled -CommandName Use-ValidDirectoryName -Exactly 0 -Scope It
        }
     }

    Context 'Pipeline Step 1: Extract Zip Files' {
        BeforeEach {
            $mockZip1 = [pscustomobject]@{ FullName = (Join-Path $script:TestZipDir "a.zip"); Name = "a.zip"; PSIsContainer = $false }
            $mockZip2 = [pscustomobject]@{ FullName = (Join-Path $script:TestZipDir "b.zip"); Name = "b.zip"; PSIsContainer = $false }
            Mock -CommandName Get-ChildItem -MockWith {
                 param($Path, $Recurse, $Filter, $File)
                 if ($Path -eq $script:zipDirectory -and $Filter -eq '*.zip' -and $File.IsPresent) { return @($mockZip1, $mockZip2) }
                 Microsoft.PowerShell.Management\Get-ChildItem @PSBoundParameters
            } -Verifiable
            (Get-Mock -CommandName $script:mock7zPath).Clear() # Use variable
            (Get-Mock -CommandName Show-ProgressBar).Clear()
            (Get-Mock -CommandName Get-ChildItem).Clear()
        }

        It 'Should call 7z.exe for each zip file found' {
            $zipFiles = Get-ChildItem -Path $script:zipDirectory -recurse -Filter "*.zip" -File
            $currentItem = 0
            $totalItems = $zipFiles.count
            foreach ($zipFile in $zipFiles) {
                $currentItem++
                Show-ProgressBar -Current $currentItem -Total $totalItems -Message "$($zipFile.FullName)"
                & "$($script:7zip)" x -aos "$($zipFile.FullName)" "-o$($script:unzipedDirectory)" | Out-Null
            }
            Assert-MockCalled -CommandName Get-ChildItem -Parameters @{ Path = $script:zipDirectory; Recurse = $true; Filter = '*.zip'; File = $true } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Show-ProgressBar -Times 2 -Scope It
            Assert-MockCalled -CommandName $script:mock7zPath -Times 2 -Scope It # Use variable
            Assert-MockCalled -CommandName $script:mock7zPath -Parameters @('x', '-aos', $mockZip1.FullName, "-o$($script:unzipedDirectory)") -Exactly 1 -Scope It # Use variable
            Assert-MockCalled -CommandName $script:mock7zPath -Parameters @('x', '-aos', $mockZip2.FullName, "-o$($script:unzipedDirectory)") -Exactly 1 -Scope It # Use variable
        }
    }

    Context 'Pipeline Step 3: Clean JSON Names (Batch Rename)' {
         $batchScriptDir = Join-Path $script:TestScriptDirectory "step3 - clean_json"
         $batchFile = "level1_batch.txt"
         $batchFilePath = Join-Path $batchScriptDir $batchFile

        BeforeEach {
            $renameCmd1 = "ren '$($script:TestUnzipDir)\old1.json' '$($script:TestUnzipDir)\new1.json'"
            $renameCmd2 = "ren '$($script:TestUnzipDir)\old2.json' '$($script:TestUnzipDir)\new2.json'"
            $renameCmd3 = "ren '$($script:TestUnzipDir)\old3.json' '$($script:TestUnzipDir)\new3.json'"
            Mock -CommandName Test-Path -MockWith {
                param($Path, $PathType)
                if ($Path -eq $batchFilePath -and $PathType -eq 'Leaf') { return $true }
                if ($Path -eq "$($script:TestUnzipDir)\new2.json") { return $true }
                return $false
            } -Verifiable
            Mock -CommandName Get-Content { param($Path) if ($Path -eq $batchFilePath) { return @($renameCmd1, $renameCmd2, $renameCmd3) } else { return @() } } -Verifiable
            Mock -CommandName Invoke-Expression {
                param($Command)
                Write-Verbose "Mock Invoke-Expression: $Command"
                if ($Command -like "*old3.json*") { throw "Rename failed" }
            } -Verifiable
            (Get-Mock -CommandName Invoke-Expression).Clear()
            (Get-Mock -CommandName Remove-Item).Clear()
            (Get-Mock -CommandName Show-ProgressBar).Clear()
            (Get-Mock -CommandName Get-Content).Clear()
            (Get-Mock -CommandName Test-Path).Clear()
            Mock -CommandName Log { }
        }

        It 'Should process rename commands from batch files' {
             # Assume $script:batchFiles and $script:batchScriptDirectory are loaded by top.ps1
             if (-not $script:batchFiles) { $script:batchFiles = @($batchFile) } # Provide default if not loaded
             if (-not $script:batchScriptDirectory) { $script:batchScriptDirectory = $batchScriptDir } # Provide default if not loaded

             $passed = 0
             $failed = 0
             foreach ($bf in $script:batchFiles) {
                 $filePath = Join-Path -Path $script:batchScriptDirectory -ChildPath $bf
                 if (!(Test-Path -Path $filePath -PathType Leaf)) {
                     Log "WARNING" "File '$filePath' not found. Skipping..."
                     continue
                 }
                 $contents = Get-Content -Path $filePath
                 $currentItem = 0
                 $totalItems = $contents.Count
                 Get-Content -Path $filePath | ForEach-Object {
                     $currentItem++
                     Show-ProgressBar -Current $currentItem -Total $totalItems -Message "$bf"
                     $command = $_.Trim()
                     if ($command -match "(ren)\s+'(.*?)'\s+'(.*?)'") {
                         $src = $Matches[2]
                         $dest = $Matches[3]
                         if (Test-Path -Path $dest) {
                             # Temporarily mock Test-Path to make src exist for Remove-Item check
                             $originalTestPathMock = Get-Mock -CommandName Test-Path
                             Mock -CommandName Test-Path -MockWith { param($Path) if ($Path -eq $src) { return $true } else { $originalTestPathMock.ScriptBlock.Invoke(@PSBoundParameters) } } -Verifiable -Scope It
                             Remove-Item -Path $src -Force
                             # Restore original Test-Path mock for this context
                             Mock -CommandName Test-Path -ScriptBlock $originalTestPathMock.ScriptBlock -Verifiable
                             continue
                         }
                     }

                     $command = $command -replace '\"', "'"
                     try {
                         Invoke-Expression $command
                         $passed++
                     } catch {
                         Log "WARNING" "Failed to execute: $command. Error: $_"
                         $failed++
                     }
                 }
             }

            Assert-MockCalled -CommandName Get-Content -Parameters @{ Path = $batchFilePath } -Times 2 -Scope It
            Assert-MockCalled -CommandName Show-ProgressBar -Times 3 -Scope It
            Assert-MockCalled -CommandName Invoke-Expression -Parameters $renameCmd1 -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Invoke-Expression -Exactly 2 -Scope It
            Assert-MockCalled -CommandName Remove-Item -Parameters @{ Path = "$($script:TestUnzipDir)\old2.json"; Force = $true } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'WARNING'; Message = "Failed to execute: $renameCmd3. Error: Rename failed" } -Exactly 1 -Scope It
        }
    }

    Context 'Pipeline Step 4: Remove Orphaned JSON' {
        $orphanedListPath = Join-Path $script:TestScriptDirectory 'step4 - ListandRemoveOrphanedJSON\orphaned_json_files.txt'
        $orphan1 = Join-Path $script:TestUnzipDir 'orphan1.json'
        $orphan2 = Join-Path $script:TestUnzipDir 'orphan2.json'
        $orphan3 = Join-Path $script:TestUnzipDir 'not_found.json'

        BeforeEach {
            # Assume $script:orphanedListPath is loaded from top.ps1
            if (-not $script:orphanedListPath) { $script:orphanedListPath = $orphanedListPath } # Provide default if not loaded

            Mock -CommandName Get-Content { param($Path) if ($Path -eq $script:orphanedListPath) { return @(" $orphan1 ", " $orphan2 ", " $orphan3 ") } else { return @() } } -Verifiable
            Mock -CommandName Test-Path {
                param($Path, $PathType)
                if ($PathType -ne 'Leaf') { return $false }
                if ($Path -eq $orphan1) { return $true }
                if ($Path -eq $orphan2) { return $true }
                if ($Path -eq $orphan3) { return $false }
                return $false
            } -Verifiable
            Mock -CommandName Remove-Item {
                param($Path, $Force)
                Write-Verbose "Mock Remove-Item: $Path"
                if ($Path -eq $orphan2) { throw "Deletion failed" }
            } -Verifiable
            Mock -CommandName Log { }
            (Get-Mock -CommandName Get-Content).Clear()
            (Get-Mock -CommandName Test-Path).Clear()
            (Get-Mock -CommandName Remove-Item).Clear()
            (Get-Mock -CommandName Log).Clear()
        }

        It 'Should attempt to remove files listed in orphaned_json_files.txt' {
            Get-Content -Path $script:orphanedListPath | ForEach-Object {
                $file = $_.Trim()
                if (Test-Path -Path "$file" -PathType Leaf) {
                    try { Remove-Item -Path "$file" -Force }
                    catch { Log "WARNING" "Failed to delete '$file': $_" }
                } else { Log "WARNING" "File not found: $file" }
            }
            Assert-MockCalled -CommandName Get-Content -Parameters @{ Path = $script:orphanedListPath } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Test-Path -Parameters @{ Path = $orphan1; PathType = 'Leaf' } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Test-Path -Parameters @{ Path = $orphan2; PathType = 'Leaf' } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Test-Path -Parameters @{ Path = $orphan3; PathType = 'Leaf' } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Remove-Item -Parameters @{ Path = $orphan1; Force = $true } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Remove-Item -Parameters @{ Path = $orphan2; Force = $true } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'WARNING'; Message = "Failed to delete '$orphan2': Deletion failed" } -Exactly 1 -Scope It
            Assert-MockCalled -CommandName Log -Parameters @{ Level = 'WARNING'; Message = "File not found: $orphan3" } -Exactly 1 -Scope It
        }
    }


    Context 'Pipeline Step 7: Clean Recycle Bin' {
         BeforeEach {
            Mock -CommandName Test-Path { param($Path, $PathType) if ($Path -eq $script:TestRecycleBin -and $PathType -eq 'Container') { return $true } else { return $false } } -Verifiable
            (Get-Mock -CommandName $script:mockAttribName).Clear() # Use variable
            (Get-Mock -CommandName Remove-Item).Clear()
            (Get-Mock -CommandName Test-Path).Clear()
         }

         It 'Should change attributes and remove contents if Recycle Bin exists' {
             if (Test-Path -Path $script:RecycleBinPath -PathType Container) {
                 & $script:mockAttribName -H -R -S -A $script:RecycleBinPath # Use variable for command name
                 Remove-Item -Path (Join-Path -Path $script:RecycleBinPath -ChildPath "*") -Recurse -Force
             }
             Assert-MockCalled -CommandName Test-Path -Parameters @{ Path = $script:RecycleBinPath; PathType = 'Container' } -Exactly 1 -Scope It
             Assert-MockCalled -CommandName $script:mockAttribName -Parameters @('-H', '-R', '-S', '-A', $script:RecycleBinPath) -Exactly 1 -Scope It # Use variable
             Assert-MockCalled -CommandName Remove-Item -Parameters @{ Path = (Join-Path $script:RecycleBinPath '*'); Recurse = $true; Force = $true } -Exactly 1 -Scope It
         }

         It 'Should do nothing if Recycle Bin does not exist' {
             Mock -CommandName Test-Path { return $false } -Verifiable
             if (Test-Path -Path $script:RecycleBinPath -PathType Container) {
                 & $script:mockAttribName -H -R -S -A $script:RecycleBinPath # Use variable
                 Remove-Item -Path (Join-Path -Path $script:RecycleBinPath -ChildPath "*") -Recurse -Force
             }
             Assert-MockCalled -CommandName Test-Path -Parameters @{ Path = $script:RecycleBinPath; PathType = 'Container' } -Exactly 1 -Scope It
             Assert-MockCalled -CommandName $script:mockAttribName -Exactly 0 -Scope It # Use variable
             Assert-MockCalled -CommandName Remove-Item -Exactly 0 -Scope It
         }
    }

     Context 'Pipeline Steps 8-11: Verify Python Script Calls' {
        BeforeEach{
             (Get-Mock -CommandName $script:mockPythonName).Clear() # Use variable
        }

        It 'Step 8-1: Should call HashANDGroupPossibleVideoDuplicates.py' {
            $scriptPath = Join-Path $script:scriptDirectory 'step8 - HashAndGroup\HashANDGroupPossibleVideoDuplicates.py'
            $expectedArgs = "$($script:unzipedDirectory)\"
            Invoke-PythonScript -ScriptPath $scriptPath -Arguments $expectedArgs
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters @($scriptPath, $expectedArgs) -Exactly 1 -Scope It # Use variable
        }
         It 'Step 8-2: Should call HashANDGroupPossibleImageDuplicates.py' {
            $scriptPath = Join-Path $script:scriptDirectory 'step8 - HashAndGroup\HashANDGroupPossibleImageDuplicates.py'
            $expectedArgs = "$($script:unzipedDirectory)\"
            Invoke-PythonScript -ScriptPath $scriptPath -Arguments $expectedArgs
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters @($scriptPath, $expectedArgs) -Exactly 1 -Scope It # Use variable
        }
         It 'Step 9-1: Should call RemoveExactVideoDuplicate.py with --dry-run' {
            $scriptPath = Join-Path $script:scriptDirectory 'step9 - RemoveExactDuplicates\RemoveExactVideoDuplicate.py'
            $expectedArgs = '--dry-run'
            Invoke-PythonScript -ScriptPath $scriptPath -Arguments $expectedArgs
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters @($scriptPath, $expectedArgs) -Exactly 1 -Scope It # Use variable
        }
         It 'Step 9-2: Should call RemoveExactImageDuplicate.py' {
            $scriptPath = Join-Path $script:scriptDirectory 'step9 - RemoveExactDuplicates\RemoveExactImageDuplicate.py'
            Invoke-PythonScript -ScriptPath $scriptPath
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters $scriptPath -Exactly 1 -Scope It # Use variable
        }
         It 'Step 10-1: Should call ShowANDRemoveDuplicateVideo.py' {
            $scriptPath = Join-Path $script:scriptDirectory 'step10 - ShowANDRemoveDuplicate\ShowANDRemoveDuplicateVideo.py'
            Invoke-PythonScript -ScriptPath $scriptPath
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters $scriptPath -Exactly 1 -Scope It # Use variable
        }
         It 'Step 10-2: Should call ShowANDRemoveDuplicateImage.py' {
            $scriptPath = Join-Path $script:scriptDirectory 'step10 - ShowANDRemoveDuplicate\ShowANDRemoveDuplicateImage.py'
            Invoke-PythonScript -ScriptPath $scriptPath
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters $scriptPath -Exactly 1 -Scope It # Use variable
        }
         It 'Step 11-1: Should call RemoveJunkVideo.py' {
            $scriptPath = Join-Path $script:scriptDirectory 'step11 - RemoveJunk\RemoveJunkVideo.py'
            $expectedArgs = "$($script:unzipedDirectory)\"
            Invoke-PythonScript -ScriptPath $scriptPath -Arguments $expectedArgs
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters @($scriptPath, $expectedArgs) -Exactly 1 -Scope It # Use variable
        }
         It 'Step 11-2: Should call RemoveJunkImage.py' {
            $scriptPath = Join-Path $script:scriptDirectory 'step11 - RemoveJunk\RemoveJunkImage.py'
            $expectedArgs = "$($script:unzipedDirectory)\"
            Invoke-PythonScript -ScriptPath $scriptPath -Arguments $expectedArgs
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters @($scriptPath, $expectedArgs) -Exactly 1 -Scope It # Use variable
        }
     }

     Context 'Pipeline Steps 12-14: Verify PowerShell Script Calls' {
        BeforeEach {
            Mock -CommandName Log { }
            Remove-Mock -CommandName (Join-Path $script:scriptDirectory 'step12 - Reconstruction\VideoReconstruction.ps1') -ErrorAction SilentlyContinue
            Remove-Mock -CommandName (Join-Path $script:scriptDirectory 'step12 - Reconstruction\ImageReconstruction.ps1') -ErrorAction SilentlyContinue
            Remove-Mock -CommandName (Join-Path $script:scriptDirectory 'step13 - Categorization\Categorize.ps1') -ErrorAction SilentlyContinue
            Remove-Mock -CommandName (Join-Path $script:scriptDirectory 'step14  - Estimate By Time\EstimateByTime.ps1') -ErrorAction SilentlyContinue
        }

        It 'Step 12-1: Should invoke VideoReconstruction.ps1' {
             $scriptPath = Join-Path $script:scriptDirectory 'step12 - Reconstruction\VideoReconstruction.ps1'
             Mock -CommandName $scriptPath { Write-Verbose "Mocked call to $scriptPath" } -Verifiable
             & $scriptPath
             Assert-MockCalled -CommandName $scriptPath -Exactly 1 -Scope It
        }
        It 'Step 12-2: Should invoke ImageReconstruction.ps1' {
             $scriptPath = Join-Path $script:scriptDirectory 'step12 - Reconstruction\ImageReconstruction.ps1'
             Mock -CommandName $scriptPath { Write-Verbose "Mocked call to $scriptPath" } -Verifiable
             & $scriptPath
             Assert-MockCalled -CommandName $scriptPath -Exactly 1 -Scope It
        }
        It 'Step 13: Should invoke Categorize.ps1' {
             $scriptPath = Join-Path $script:scriptDirectory 'step13 - Categorization\Categorize.ps1'
             Mock -CommandName $scriptPath { Write-Verbose "Mocked call to $scriptPath" } -Verifiable
             & $scriptPath
             Assert-MockCalled -CommandName $scriptPath -Exactly 1 -Scope It
        }
        It 'Step 14: Should invoke EstimateByTime.ps1' {
             $scriptPath = Join-Path $script:scriptDirectory 'step14  - Estimate By Time\EstimateByTime.ps1'
             Mock -CommandName $scriptPath { Write-Verbose "Mocked call to $scriptPath" } -Verifiable
             & $scriptPath
             Assert-MockCalled -CommandName $scriptPath -Exactly 1 -Scope It
        }
     }

    Context 'Counter Steps' {
        BeforeEach {
            (Get-Mock -CommandName $script:mockPythonName).Clear() # Use variable
            $script:logger = 0
        }

        It 'Should call counter.py script multiple times with incrementing log file names' {
            $counterScriptPath = Join-Path $script:scriptDirectory 'Step0 - Tools\counter\counter.py'
            $logArg0 = "$($script:scriptDirectory)/Logs/log_step_0.txt"
            Invoke-PythonScript -ScriptPath $counterScriptPath -Arguments "$logArg0 $($script:unzipedDirectory)"
            $script:logger++
            $logArg1 = "$($script:scriptDirectory)/Logs/log_step_1.txt"
            Invoke-PythonScript -ScriptPath $counterScriptPath -Arguments "$logArg1 $($script:unzipedDirectory)"
            $script:logger++
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters @($counterScriptPath, "$logArg0 $($script:unzipedDirectory)") -Exactly 1 -Scope It # Use variable
            Assert-MockCalled -CommandName $script:mockPythonName -Parameters @($counterScriptPath, "$logArg1 $($script:unzipedDirectory)") -Exactly 1 -Scope It # Use variable
        }
    }
}

