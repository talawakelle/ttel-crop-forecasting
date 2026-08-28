[CmdletBinding()]
param(
    [string]$CropDirectory = "data\incoming\crop",
    [string]$ReportPath = "outputs\crop_archive_validation.csv"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if (-not (Test-Path $CropDirectory -PathType Container)) {
    throw "Crop directory not found: $CropDirectory"
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$Rows = foreach ($File in Get-ChildItem -Path $CropDirectory -Filter "*.zip" -File | Sort-Object Name) {
    $Status = "PASS"
    $WorkbookCount = 0
    $Message = "Archive is readable"
    try {
        $Archive = [System.IO.Compression.ZipFile]::OpenRead($File.FullName)
        try {
            $WorkbookCount = @($Archive.Entries | Where-Object {
                $_.FullName.EndsWith(".xlsx", [System.StringComparison]::OrdinalIgnoreCase)
            }).Count
            if ($WorkbookCount -eq 0) {
                $Status = "FAIL"
                $Message = "No .xlsx files found"
            }
        }
        finally {
            $Archive.Dispose()
        }
    }
    catch {
        $Status = "FAIL"
        $Message = $_.Exception.Message
    }

    [PSCustomObject]@{
        file_name = $File.Name
        size_mb = [math]::Round($File.Length / 1MB, 2)
        status = $Status
        xlsx_workbooks = $WorkbookCount
        message = $Message
    }
}

if (@($Rows).Count -eq 0) {
    throw "No ZIP archives were found in: $CropDirectory"
}

$ReportDirectory = Split-Path -Parent $ReportPath
if ($ReportDirectory) {
    New-Item -ItemType Directory -Force -Path $ReportDirectory | Out-Null
}
$Rows | Export-Csv -Path $ReportPath -NoTypeInformation -Encoding UTF8
$Rows | Format-Table -AutoSize

$Failed = @($Rows | Where-Object { $_.status -eq "FAIL" }).Count
if ($Failed -gt 0) {
    throw "$Failed crop archive(s) failed validation. See $ReportPath."
}

Write-Host "All crop archives passed. Report: $ReportPath" -ForegroundColor Green
