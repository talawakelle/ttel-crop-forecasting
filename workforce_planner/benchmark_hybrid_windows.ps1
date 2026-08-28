param(
    [ValidateRange(5, 100)]
    [int]$Episodes = 40,
    [ValidateRange(0.25, 30.0)]
    [double]$TimeLimitSeconds = 5.0
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "backend\.venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment not found. Run setup_windows.ps1 first."
}

Set-Location $Root
Write-Host "Validating the full Clarendon profile..." -ForegroundColor Cyan
& $Python "scripts\check_profile.py" --require-full
if ($LASTEXITCODE -ne 0) {
    throw "Full Clarendon profile validation failed."
}

Write-Host "Comparing hybrid, mathematical optimizer, RL and standard allocation..." -ForegroundColor Cyan
Write-Host "Daily CatBoost inference and CP-SAT optimization use the CPU; low GPU activity is normal." -ForegroundColor Yellow
& $Python "scripts\benchmark_hybrid.py" --episodes $Episodes --time-limit $TimeLimitSeconds
if ($LASTEXITCODE -ne 0) {
    throw "Hybrid benchmark failed. Review the error shown above."
}

Write-Host "Hybrid benchmark complete. Results are saved in models\hybrid_benchmark.json" -ForegroundColor Green
