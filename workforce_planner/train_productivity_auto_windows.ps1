param(
    [ValidateRange(200, 20000)]
    [int]$Iterations = 3000,
    [ValidateRange(4, 10)]
    [int]$Depth = 8
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run setup_windows.ps1 or setup_gpu_windows.ps1 first." }
Set-Location $Root
& $Python "scripts\check_forecast_data.py"
if ($LASTEXITCODE -ne 0) { throw "Forecast data validation failed." }
& $Python "scripts\train_productivity.py" --iterations $Iterations --depth $Depth --task-type auto
if ($LASTEXITCODE -ne 0) { throw "Forecast training failed." }
& $Python "scripts\check_forecast.py" --require-ready
if ($LASTEXITCODE -ne 0) { throw "The forecast candidate did not pass its safety gate." }
Write-Host "Forecast approved. Any previous RL model is now incompatible until retrained against this new forecast." -ForegroundColor Yellow
