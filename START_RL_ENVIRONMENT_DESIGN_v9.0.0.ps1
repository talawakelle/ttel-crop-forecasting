$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$CapacityPointer = Join-Path $ProjectRoot "workforce_planner\v7\cp_sat_capacity_matching_runs\LATEST_CP_SAT_CAPACITY_MATCHING_RUN.txt"
$ComparisonPointer = Join-Path $ProjectRoot "workforce_planner\v8\greedy_comparison_runs\LATEST_GREEDY_COMPARISON_RUN.txt"
$BalancedPointer = Join-Path $ProjectRoot "workforce_planner\v8\balanced_baseline_review_runs\LATEST_BALANCED_BASELINE_REVIEW.txt"
foreach ($Pointer in @($CapacityPointer, $ComparisonPointer, $BalancedPointer)) {
    if (-not (Test-Path $Pointer)) { throw "Required pointer not found: $Pointer" }
}
$CapacityRun = (Get-Content $CapacityPointer -Raw).Trim()
$ComparisonRun = (Get-Content $ComparisonPointer -Raw).Trim()
$BalancedRun = (Get-Content $BalancedPointer -Raw).Trim()
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v9\rl_environment\build_rl_environment_v900.py"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v9\rl_environment_runs"
if (Get-Command py -ErrorAction SilentlyContinue) { $PythonCommand = "py" }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $PythonCommand = "python" }
else { throw "Python was not found." }
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$LogPath = Join-Path $OutputRoot ("rl_environment_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
Start-Transcript -Path $LogPath -Force
try {
    Write-Host "Starting safe RL environment design v9.0.0..." -ForegroundColor Cyan
    Write-Host "This creates 66 estate-scenario environments."
    Write-Host "No RL model training will run."
    & $PythonCommand $PythonScript --capacity-run $CapacityRun --comparison-run $ComparisonRun --balanced-run $BalancedRun --output-root $OutputRoot --shock-count 5 --expected-field-rows 894
    if ($LASTEXITCODE -ne 0) { throw "RL environment design returned exit code $LASTEXITCODE" }
    Write-Host ""
    Write-Host "RL environment design completed." -ForegroundColor Green
    Write-Host "Run .\CHECK_RL_ENVIRONMENT_DESIGN_v9.0.0.ps1"
}
finally { Stop-Transcript | Out-Null }
