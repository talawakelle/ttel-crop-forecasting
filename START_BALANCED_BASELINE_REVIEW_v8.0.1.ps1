$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

$ComparisonPointer = Join-Path $ProjectRoot "workforce_planner\v8\greedy_comparison_runs\LATEST_GREEDY_COMPARISON_RUN.txt"
$CapacityPointer = Join-Path $ProjectRoot "workforce_planner\v7\cp_sat_capacity_matching_runs\LATEST_CP_SAT_CAPACITY_MATCHING_RUN.txt"

if (-not (Test-Path $ComparisonPointer)) {
    throw "Latest greedy comparison pointer was not found: $ComparisonPointer"
}
if (-not (Test-Path $CapacityPointer)) {
    throw "Latest capacity-matching pointer was not found: $CapacityPointer"
}

$ComparisonRun = (Get-Content $ComparisonPointer -Raw).Trim()
$CapacityRun = (Get-Content $CapacityPointer -Raw).Trim()
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v8\balanced_baseline_review\run_balanced_baseline_review_v801.py"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v8\balanced_baseline_review_runs"

if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCommand = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCommand = "python"
} else {
    throw "Python was not found."
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$LogPath = Join-Path $OutputRoot ("balanced_baseline_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force
try {
    Write-Host "Starting balanced baseline review v8.0.1..." -ForegroundColor Cyan
    Write-Host "The legacy 0.5 kg result will remain visible."
    Write-Host "A material tolerance and service-safety gate will also be applied."
    Write-Host "No RL training will run."

    & $PythonCommand $PythonScript `
        --comparison-run $ComparisonRun `
        --capacity-run $CapacityRun `
        --output-root $OutputRoot `
        --minimum-gate-pct 80 `
        --absolute-tolerance-kg 2 `
        --relative-tolerance-pct 0.05 `
        --maximum-shortfall-rate-pct 0.10

    if ($LASTEXITCODE -ne 0) {
        throw "Balanced baseline review returned exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Balanced baseline review completed." -ForegroundColor Green
    Write-Host "Run .\CHECK_BALANCED_BASELINE_REVIEW_v8.0.1.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
