$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$EmployeePointer = Join-Path $ProjectRoot "workforce_planner\v6\employee_readiness_runs\LATEST_EMPLOYEE_READINESS_RUN.txt"
$PlanningPointer = Join-Path $ProjectRoot "workforce_planner\v5\final_method_gate_runs_v503\LATEST_BEST_AVAILABLE_PLANNING_RUN.txt"
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

& $PythonCommand $PythonScript `
    --employee-run $EmployeeRun `
    --planning-run $PlanningRun `
    --output-root $OutputRoot `
    --preflight-only
