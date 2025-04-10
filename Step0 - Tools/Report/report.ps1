function Get-ZipEntries {
    param ([string]$ZipPath)
    $entries = @()
    try {
        $zip = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
        foreach ($entry in $zip.Entries) {
            if ($entry.FullName -and -not $entry.FullName.EndsWith("/")) {
                $entries += $entry.FullName
            }
        }
        $zip.Dispose()
    } catch {
        Write-Warning "Failed to read ZIP: $ZipPath"
    }
    return $entries
}

function Collect-ExtensionStatsAndFiles {
    param (
        [string]$Path,
        [hashtable]$ExtSummary,
        [hashtable]$FileListing
    )

    Get-ChildItem -Path $Path -Recurse -File | ForEach-Object {
        $dir = Split-Path $_.FullName -Parent
        $ext = [System.IO.Path]::GetExtension($_.Name).ToLowerInvariant().TrimStart('.')
        if (-not $ExtSummary.ContainsKey($dir)) {
            $ExtSummary[$dir] = @{}
        }
        if (-not $ExtSummary[$dir].ContainsKey($ext)) {
            $ExtSummary[$dir][$ext] = 0
        }
        $ExtSummary[$dir][$ext] += 1

        if (-not $FileListing.ContainsKey($dir)) {
            $FileListing[$dir] = @()
        }
        $FileListing[$dir] += $_.Name
    }
}

function Write-ExtensionSummary {
    param (
        [hashtable]$Summary,
        [string]$OutputFile,
        [string]$Header
    )

    "" | Out-File -FilePath $OutputFile -Encoding UTF8
    Add-Content -Path $OutputFile -Value $Header
    Add-Content -Path $OutputFile -Value ("-" * $Header.Length)

    $total = @{}

    if ($Mode -ne "TotalReport") {
        foreach ($dir in ($Summary.Keys | Sort-Object)) {
            Add-Content -Path $OutputFile -Value "`n[$dir]"
            foreach ($ext in ($Summary[$dir].Keys | Sort-Object)) {
                $label = if ($ext) { $ext } else { "<no extension>" }
                $count = $Summary[$dir][$ext]
                Add-Content -Path $OutputFile -Value ("  $label : $count")

                if (-not $total.ContainsKey($label)) {
                    $total[$label] = 0
                }
                $total[$label] += $count
            }
        }
    } else {
        foreach ($dir in $Summary.Keys) {
            foreach ($ext in $Summary[$dir].Keys) {
                $label = if ($ext) { $ext } else { "<no extension>" }
                if (-not $total.ContainsKey($label)) {
                    $total[$label] = 0
                }
                $total[$label] += $Summary[$dir][$ext]
            }
        }
    }

    if ($Mode -eq "TotalReport" -or $Mode -eq "DirectoryReport") {
        Add-Content -Path $OutputFile -Value "`n[Total]"
        foreach ($ext in ($total.Keys | Sort-Object)) {
            Add-Content -Path $OutputFile -Value ("  $ext : $($total[$ext])")
        }
    }
}

function Write-FileList {
    param (
        [hashtable]$Listing,
        [string]$OutputFile,
        [string]$Header
    )

    "" | Out-File -FilePath $OutputFile -Encoding UTF8
    Add-Content -Path $OutputFile -Value $Header
    Add-Content -Path $OutputFile -Value ("-" * $Header.Length)

    $totalCount = 0

    if ($Mode -eq "Detailed") {
        foreach ($dir in ($Listing.Keys | Sort-Object)) {
            Add-Content -Path $OutputFile -Value "`n[$dir]"
            $files = $Listing[$dir] | Sort-Object
            $totalCount += $files.Count
            foreach ($file in $files) {
                Add-Content -Path $OutputFile -Value "  $file"
            }
        }
    } else {
        foreach ($files in $Listing.Values) {
            $totalCount += $files.Count
        }
    }

    if ($Mode -ne "Detailed") {
        Add-Content -Path $OutputFile -Value "`n[Total Files] : $totalCount"
    }
}

function Process-MediaStructure {
    param (
        [string]$Label,
        [string]$InputPath,
        [string]$SummaryOutputPath,
        [string]$FilesOutputPath,
        [bool]$IsZip
    )

    $extSummary = @{}
    $fileListing = @{}

    if ($IsZip) {
        $zipFiles = Get-ChildItem -Path $InputPath -Filter *.zip -Recurse
        foreach ($zipFile in $zipFiles) {
            $entries = Get-ZipEntries -ZipPath $zipFile.FullName | Sort-Object
            foreach ($path in $entries) {
                $parts = $path -split "[\\\/]"
                if ($parts.Length -lt 2) { continue }

                $filename = $parts[-1]
                $ext = [System.IO.Path]::GetExtension($filename).ToLowerInvariant().TrimStart('.')
                $dirPath = ($parts[0..($parts.Length - 2)] -join "\")

                if (-not $extSummary.ContainsKey($dirPath)) {
                    $extSummary[$dirPath] = @{}
                }
                if (-not $extSummary[$dirPath].ContainsKey($ext)) {
                    $extSummary[$dirPath][$ext] = 0
                }
                $extSummary[$dirPath][$ext] += 1

                if (-not $fileListing.ContainsKey($dirPath)) {
                    $fileListing[$dirPath] = @()
                }
                $fileListing[$dirPath] += $filename
            }
        }
    } else {
        Collect-ExtensionStatsAndFiles -Path $InputPath -ExtSummary $extSummary -FileListing $fileListing
    }

    Write-ExtensionSummary -Summary $extSummary -OutputFile $SummaryOutputPath -Header "File Type Summary Per $Label Directory:"
    Write-FileList -Listing $fileListing -OutputFile $FilesOutputPath -Header "Files Per $Label Directory:"

    Write-Host "`n$Label output written to:"
    Write-Host " - $SummaryOutputPath"
    Write-Host " - $FilesOutputPath"
}

function Run-MediaStructureAnalysis {
    param (
        [string]$ZipDirectory = "D:",
        [string]$RootDirectory = "E:",
        [ValidateSet("Detailed", "TotalReport", "DirectoryReport")]
        [string]$ModeParam = "Detailed",
        [ValidateSet("Zip", "Unzip", "Both")]
        [string]$Target = "Both"
    )

    $global:Mode = $ModeParam

    $OutputFileZip        = Join-Path $PSScriptRoot "extracted_structure_zip.txt"
    $OutputFileUnzip      = Join-Path $PSScriptRoot "extracted_structure_unzip.txt"
    $OutputFileZipFiles   = Join-Path $PSScriptRoot "files_by_dir_zip.txt"
    $OutputFileUnzipFiles = Join-Path $PSScriptRoot "files_by_dir_unzip.txt"

    if ($Target -eq "Zip" -or $Target -eq "Both") {
        Process-MediaStructure -Label "Simulated Extracted" `
                               -InputPath $ZipDirectory `
                               -SummaryOutputPath $OutputFileZip `
                               -FilesOutputPath $OutputFileZipFiles `
                               -IsZip $true
    }

    if ($Target -eq "Unzip" -or $Target -eq "Both") {
        Process-MediaStructure -Label "Actual" `
                               -InputPath $RootDirectory `
                               -SummaryOutputPath $OutputFileUnzip `
                               -FilesOutputPath $OutputFileUnzipFiles `
                               -IsZip $false
    }
}

Run-MediaStructureAnalysis -ZipDirectory "D:" -RootDirectory "E:" -ModeParam "TotalReport" -Target "unzip"
