param(
    [ValidateRange(5, 100)]
    [int]$Episodes = 40,
    [ValidateRange(0.25, 30.0)]
    [double]$TimeLimitSeconds = 3.0
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "backend\.venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python environment not found. Run setup_windows.ps1 first."
}

Set-Location $Root
Write-Host "Benchmarking strict, division-flexible, full-attendance and combined plans..." -ForegroundColor Cyan
Write-Host "CP-SAT uses the CPU. The existing CatBoost forecast and RL model are not retrained." -ForegroundColor Yellow
& $Python "scripts\benchmark_coverage_frontier.py" --episodes $Episodes --time-limit $TimeLimitSeconds
if ($LASTEXITCODE -ne 0) {
    throw "Coverage-frontier benchmark failed. Review the error above."
}

Write-Host "Coverage benchmark complete: models\coverage_frontier_benchmark.json" -ForegroundColor Green
