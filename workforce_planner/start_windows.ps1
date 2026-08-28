$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Python = Join-Path $Backend ".venv\Scripts\python.exe"
$Url = "http://127.0.0.1:8090"

if (-not (Test-Path $Python)) {
    throw "Run .\setup_windows.ps1 first."
}

$Existing = Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue
if ($Existing) {
    Write-Host "The planner is already running on $Url" -ForegroundColor Green
    Start-Process $Url
    exit 0
}

Set-Location $Backend
Write-Host "TTE Conservative High-Confidence Hybrid RL Employee Planner v1.5: $Url" -ForegroundColor Green
Write-Host "CatBoost forecasting and CP-SAT planning are active. High-confidence hybrid RL remains gated until GPU training passes untouched-test safety checks." -ForegroundColor Cyan
Write-Host "Keep this window open while using the planner." -ForegroundColor Yellow
Start-Process $Url
& $Python -m uvicorn app.main:app --host 127.0.0.1 --port 8090
