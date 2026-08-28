param(
    [Parameter(Mandatory = $false)]
    [string]$CropRoot = "C:\Users\user\Desktop\HG 2",

    [Parameter(Mandatory = $false)]
    [int]$ExpectedEstates = 33
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v3\data_audit\run_estate_data_audit.py"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v3\data_audit_runs"

if (-not (Test-Path $PythonScript)) {
    throw "Corrected audit script not found: $PythonScript"
}
if (-not (Test-Path $CropRoot)) {
    throw "Crop archive folder not found: $CropRoot"
}

if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCommand = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCommand = "python"
} else {
    throw "Python was not found."
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$LogPath = Join-Path $OutputRoot ("data_audit_v301_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force
try {
    Write-Host "Starting corrected all-estate data audit v3.0.1..." -ForegroundColor Cyan
    Write-Host "The v3.0.0 int/string accumulation defect has been removed."
    Write-Host "Reader mode: exact historical All Records schema."
    Write-Host "This stage is read-only."

    & $PythonCommand $PythonScript `
        --crop-root $CropRoot `
        --output-root $OutputRoot `
        --expected-estates $ExpectedEstates

    if ($LASTEXITCODE -ne 0) {
        throw "Corrected audit failed with exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Corrected audit completed." -ForegroundColor Green
    Write-Host "Run .\CHECK_DATA_IDENTITY_READINESS_AUDIT_v3.0.1.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
