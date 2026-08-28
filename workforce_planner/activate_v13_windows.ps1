$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run setup_windows.ps1 or setup_gpu_windows.ps1 first." }
Set-Location $Root
& $Python "scripts\check_profile.py" --require-full
& $Python "scripts\check_forecast.py" --require-ready
& $Python "scripts\check_crop_forecast.py"
Write-Host "v1.3 robust dynamic-RL environment is ready." -ForegroundColor Green
Write-Host "Use start_windows.ps1 to run, IMPORT_CROP_FORECAST.bat to refresh crop demand, or TRAIN_DYNAMIC_RL_GPU.bat to train the intraday policy." -ForegroundColor Cyan
