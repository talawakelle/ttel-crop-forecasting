$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

$CapacityPointer = Join-Path $ProjectRoot "workforce_planner\v7\cp_sat_capacity_matching_runs\LATEST_CP_SAT_CAPACITY_MATCHING_RUN.txt"
$PlanningPointer = Join-Path $ProjectRoot "workforce_planner\v5\final_method_gate_runs_v503\LATEST_BEST_AVAILABLE_PLANNING_RUN.txt"

if (-not (Test-Path $CapacityPointer)) {
    throw "Latest CP-SAT capacity run pointer was not found: $CapacityPointer"
}
if (-not (Test-Path $PlanningPointer)) {
    throw "Latest planning pointer was not found: $PlanningPointer"
}

$CapacityRun = (Get-Content $CapacityPointer -Raw).Trim()
$PlanningRun = (Get-Content $PlanningPointer -Raw).Trim()
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v8\greedy_comparison\run_greedy_comparison_v800.py"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v8\greedy_comparison_runs"

if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCommand = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCommand = "python"
} else {
    throw "Python was not found."
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$LogPath = Join-Path $OutputRoot ("greedy_comparison_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force
try {
    Write-Host "Starting CP-SAT versus greedy comparison v8.0.0..." -ForegroundColor Cyan
    Write-Host "The Clarendon-style 80% noninferiority gate will be applied."
    Write-Host "No live allocation or RL training will run."

    & $PythonCommand $PythonScript `
        --capacity-run $CapacityRun `
        --planning-run $PlanningRun `
        --output-root $OutputRoot

    if ($LASTEXITCODE -ne 0) {
        throw "Greedy comparison returned exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "CP-SAT versus greedy comparison completed." -ForegroundColor Green
    Write-Host "Run .\CHECK_CP_SAT_VS_GREEDY_v8.0.0.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
