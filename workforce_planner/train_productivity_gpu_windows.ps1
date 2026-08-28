param(
    [ValidateRange(200, 20000)]
    [int]$Iterations = 3000,
    [ValidateRange(4, 10)]
    [int]$Depth = 8
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run setup_gpu_windows.ps1 first." }
Set-Location $Root
& $Python "scripts\check_gpu.py"
if ($LASTEXITCODE -ne 0) { throw "CUDA is unavailable." }
& $Python "scripts\train_productivity.py" --iterations $Iterations --depth $Depth --task-type gpu --devices 0 --gpu-ram-part 0.90
if ($LASTEXITCODE -ne 0) { throw "GPU forecast training failed." }
& $Python "scripts\check_forecast.py" --require-ready
if ($LASTEXITCODE -ne 0) { throw "The forecast candidate did not pass its safety gate." }
Write-Host "Forecast approved. Retrain RL because the forecast fingerprint changed." -ForegroundColor Yellow
