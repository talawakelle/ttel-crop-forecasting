$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Python = Join-Path $Backend ".venv\Scripts\python.exe"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python launcher not found. Install 64-bit Python 3.12 and select Add Python to PATH."
}
if (-not (Test-Path $Python)) {
    Write-Host "Creating isolated Python 3.12 environment..." -ForegroundColor Cyan
    py -3.12 -m venv (Join-Path $Backend ".venv")
}
& $Python -m pip install --upgrade pip
Write-Host "Installing CPU PyTorch and planner packages..." -ForegroundColor Cyan
& $Python -m pip install --timeout 3600 torch --index-url https://download.pytorch.org/whl/cpu
& $Python -m pip install --timeout 3600 -r (Join-Path $Backend "requirements.txt")
& $Python (Join-Path $Root "scripts\check_forecast.py") --require-ready
if ($LASTEXITCODE -ne 0) { throw "The packaged CatBoost forecast failed validation." }
Write-Host "Setup complete. Run .\start_windows.ps1" -ForegroundColor Green
Write-Host "Morning RL, legacy full dynamic RL, and selective hybrid RL remain disabled until their training scripts produce approved models." -ForegroundColor Yellow
