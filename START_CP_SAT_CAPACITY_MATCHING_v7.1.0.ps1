$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

$EmployeePointer = Join-Path $ProjectRoot "workforce_planner\v6\employee_readiness_runs\LATEST_EMPLOYEE_READINESS_RUN.txt"
$PlanningPointer = Join-Path $ProjectRoot "workforce_planner\v5\final_method_gate_runs_v503\LATEST_BEST_AVAILABLE_PLANNING_RUN.txt"

if (-not (Test-Path $EmployeePointer)) {
    throw "Employee readiness pointer not found: $EmployeePointer"
}
if (-not (Test-Path $PlanningPointer)) {
    throw "Planning pointer not found: $PlanningPointer"
}

$EmployeeRun = (Get-Content $EmployeePointer -Raw).Trim()
$PlanningRun = (Get-Content $PlanningPointer -Raw).Trim()
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v7\cp_sat_capacity_matching\run_cp_sat_capacity_matching_v710.py"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v7\cp_sat_capacity_matching_runs"

if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCommand = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCommand = "python"
} else {
    throw "Python was not found."
}

& $PythonCommand -c "from ortools.sat.python import cp_model; print('OR-Tools available')"
if ($LASTEXITCODE -ne 0) {
    throw "OR-Tools is missing. Run: py -m pip install --upgrade ortools"
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$LogPath = Join-Path $OutputRoot ("capacity_matching_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force
try {
    Write-Host "Starting CP-SAT capacity-matching repair v7.1.0..." -ForegroundColor Cyan
    Write-Host "Every employee record remains in the audit roster."
    Write-Host "Every unique employee ID is considered for every active field in its estate."
    Write-Host "Field identity is estate + division + field."
    Write-Host "The old staffing demand is a soft reference, not a hard maximum."
    Write-Host "No live allocation or RL training will run."

    & $PythonCommand $PythonScript `
        --employee-run $EmployeeRun `
        --planning-run $PlanningRun `
        --output-root $OutputRoot `
        --scenarios BOTH `
        --time-limit-seconds 45

    if ($LASTEXITCODE -ne 0) {
        throw "Capacity-matching repair returned exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Capacity-matching repair completed." -ForegroundColor Green
    Write-Host "Run .\CHECK_CP_SAT_CAPACITY_MATCHING_v7.1.0.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
