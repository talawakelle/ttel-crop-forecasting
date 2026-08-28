$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScenarioPointer = Join-Path $ProjectRoot "workforce_planner\v6\all_employee_scenario_runs\LATEST_ALL_EMPLOYEE_SCENARIO_RUN.txt"
$PlanningPointer = Join-Path $ProjectRoot "workforce_planner\v5\final_method_gate_runs_v503\LATEST_BEST_AVAILABLE_PLANNING_RUN.txt"
$ScenarioRun = (Get-Content $ScenarioPointer -Raw).Trim()
$PlanningRun = (Get-Content $PlanningPointer -Raw).Trim()
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v7\cp_sat_development\run_cp_sat_development_v700.py"

if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCommand = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCommand = "python"
} else {
    throw "Python was not found."
}

& $PythonCommand $PythonScript `
    --scenario-run $ScenarioRun `
    --planning-run $PlanningRun `
    --output-root (Join-Path $ProjectRoot "workforce_planner\v7\cp_sat_development_runs") `
    --preflight-only
