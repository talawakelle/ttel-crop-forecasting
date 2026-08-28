param(
    [Parameter(Mandatory = $true)]
    [string]$Source
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "backend\.venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment not found. Run setup_gpu_windows.ps1 first."
}
if (-not (Test-Path -LiteralPath $Source)) {
    throw "Clarendon source not found: $Source"
}

Set-Location $Root
Write-Host "Building pseudonymized productivity and leakage-controlled weather features..." -ForegroundColor Cyan
& $Python "scripts\prepare_forecast_data.py" (Resolve-Path -LiteralPath $Source).Path
if ($LASTEXITCODE -ne 0) { throw "Forecast data preparation failed." }
& $Python "scripts\check_forecast_data.py"
if ($LASTEXITCODE -ne 0) { throw "Prepared forecast data failed validation." }
Write-Host "Forecast data is ready. Raw identifiers were not copied into the training files." -ForegroundColor Green
