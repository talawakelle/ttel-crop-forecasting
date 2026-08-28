[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Estate,

    [Parameter(Mandatory = $true)]
    [string]$CropZip,

    [string]$WeatherFile = "",

    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "The Python environment is missing. Run .\setup_windows.ps1 first."
}
if (-not (Test-Path $CropZip)) {
    throw "Crop ZIP/XLSX not found: $CropZip"
}
if (-not [string]::IsNullOrWhiteSpace($WeatherFile) -and -not (Test-Path $WeatherFile)) {
    throw "Weather workbook not found: $WeatherFile"
}

$ResolvedCrop = (Resolve-Path $CropZip).Path
if ([System.IO.Path]::GetExtension($ResolvedCrop) -ieq ".zip") {
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $Archive = [System.IO.Compression.ZipFile]::OpenRead($ResolvedCrop)
        try {
            $WorkbookCount = @($Archive.Entries | Where-Object {
                $_.FullName.EndsWith(".xlsx", [System.StringComparison]::OrdinalIgnoreCase)
            }).Count
            if ($WorkbookCount -eq 0) {
                throw "No .xlsx crop workbooks were found inside the archive."
            }
        }
        finally {
            $Archive.Dispose()
        }
    }
    catch {
        throw "Crop ZIP is incomplete or unreadable: $CropZip. Recreate or re-upload it before training. Details: $($_.Exception.Message)"
    }
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $SafeEstate = $Estate -replace '[^A-Za-z0-9_-]', '_'
    $OutputDirectory = Join-Path "outputs" $SafeEstate
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

$TrainArguments = @(
    "train.py",
    "--estate", $Estate,
    "--crop", $ResolvedCrop,
    "--output-dir", $OutputDirectory
)
if (-not [string]::IsNullOrWhiteSpace($WeatherFile)) {
    $ResolvedWeather = (Resolve-Path $WeatherFile).Path
    $TrainArguments += @("--weather", $ResolvedWeather)
}

& $Python @TrainArguments

if ($LASTEXITCODE -ne 0) {
    throw "Training failed. Review the error above before attempting another estate."
}

Write-Host "Training completed for $Estate." -ForegroundColor Green
Write-Host "Results: $OutputDirectory"
