param(
    [ValidateRange(50000, 2000000)]
    [int]$TimestepsPerSeed = 400000
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run setup_gpu_windows.ps1 first." }
Set-Location $Root
& $Python "scripts\check_profile.py" --require-full
if ($LASTEXITCODE -ne 0) { throw "Full profile validation failed." }
& $Python "scripts\check_forecast.py" --require-ready
if ($LASTEXITCODE -ne 0) { throw "Approved CatBoost forecast is required before RL training." }
& $Python "scripts\check_gpu.py"
if ($LASTEXITCODE -ne 0) { throw "CUDA is unavailable." }
Write-Host "Training three forecast-aware RL candidates. Only a model that beats the forecast-greedy baseline will be activated." -ForegroundColor Cyan
& $Python "scripts\train_strong.py" --timesteps-per-seed $TimestepsPerSeed --device cuda --seeds 42 2026 3407
if ($LASTEXITCODE -ne 0) { throw "No RL model passed the safety gate. The optimizer and forecast-greedy baseline remain active." }
& $Python "scripts\check_model.py"
if ($LASTEXITCODE -ne 0) { throw "The selected RL model failed compatibility validation." }
Write-Host "Approved forecast-aware RL model is active. Restart the dashboard." -ForegroundColor Green
