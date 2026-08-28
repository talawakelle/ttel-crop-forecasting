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
    throw "Audit script not found: $PythonScript"
}
if (-not (Test-Path $CropRoot)) {
    throw "Crop archive folder not found: $CropRoot"
}

$PythonCommand = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCommand = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCommand = "python"
} else {
    throw "Python was not found. Install Python or add it to PATH."
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$LogPath = Join-Path $OutputRoot ("data_audit_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force
try {
    Write-Host "Starting the all-estate data identity and readiness audit..." -ForegroundColor Cyan
    Write-Host "Crop archives: $CropRoot"
    Write-Host "This stage is read-only. It will not change the portal, candidate models or live allocator."

    & $PythonCommand $PythonScript `
        --crop-root $CropRoot `
        --output-root $OutputRoot `
        --expected-estates $ExpectedEstates

    if ($LASTEXITCODE -ne 0) {
        throw "Data audit failed with exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Next-stage audit completed." -ForegroundColor Green
    Write-Host "Run .\CHECK_DATA_IDENTITY_READINESS_AUDIT_v3.0.0.ps1 to review the results."
}
finally {
    Stop-Transcript | Out-Null
}
