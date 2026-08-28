$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run setup_windows.ps1 or setup_gpu_windows.ps1 first." }
Set-Location $Root
& $Python "scripts\check_profile.py" --require-full
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python "scripts\check_forecast.py" --require-ready
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python "scripts\check_crop_forecast.py"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "v1.4 selective hybrid RL environment is ready." -ForegroundColor Green
Write-Host "Use START_PLANNER.bat to run the planner or TRAIN_HYBRID_RL_GPU.bat to train the selective intraday gate." -ForegroundColor Cyan

Write-Host "A newer v1.5 activation script is available: .\activate_v15_windows.ps1" -ForegroundColor Yellow
