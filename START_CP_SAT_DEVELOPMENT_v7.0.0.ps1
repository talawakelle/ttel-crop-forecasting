$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

$ScenarioPointer = Join-Path $ProjectRoot "workforce_planner\v6\all_employee_scenario_runs\LATEST_ALL_EMPLOYEE_SCENARIO_RUN.txt"
$PlanningPointer = Join-Path $ProjectRoot "workforce_planner\v5\final_method_gate_runs_v503\LATEST_BEST_AVAILABLE_PLANNING_RUN.txt"

if (-not (Test-Path $ScenarioPointer)) {
    throw "Latest all-employee scenario pointer was not found: $ScenarioPointer"
}
if (-not (Test-Path $PlanningPointer)) {
    throw "Latest final planning pointer was not found: $PlanningPointer"
}

$ScenarioRun = (Get-Content $ScenarioPointer -Raw).Trim()
$PlanningRun = (Get-Content $PlanningPointer -Raw).Trim()
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v7\cp_sat_development\run_cp_sat_development_v700.py"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v7\cp_sat_development_runs"

if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCommand = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCommand = "python"
} else {
    throw "Python was not found."
}

Write-Host "Checking OR-Tools..." -ForegroundColor Cyan
& $PythonCommand -c "from ortools.sat.python import cp_model; print('OR-Tools available')"

if ($LASTEXITCODE -ne 0) {
    Write-Host "OR-Tools is not installed. Installing it now..." -ForegroundColor Yellow
    & $PythonCommand -m pip install --upgrade ortools

    if ($LASTEXITCODE -ne 0) {
        throw "OR-Tools installation failed. Check internet access and run: py -m pip install ortools"
    }
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$LogPath = Join-Path $OutputRoot ("cp_sat_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force
try {
    Write-Host "Starting CP-SAT development allocation v7.0.0..." -ForegroundColor Cyan
    Write-Host "Expected and conservative scenarios will be solved."
    Write-Host "Each employee can be assigned to at most one field per scenario."
    Write-Host "No live allocation or RL training will run."

    & $PythonCommand $PythonScript `
        --scenario-run $ScenarioRun `
        --planning-run $PlanningRun `
        --output-root $OutputRoot `
        --scenarios BOTH `
        --time-limit-seconds 30

    if ($LASTEXITCODE -ne 0) {
        throw "CP-SAT development run returned exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "CP-SAT development allocation completed." -ForegroundColor Green
    Write-Host "Run .\CHECK_CP_SAT_DEVELOPMENT_v7.0.0.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
