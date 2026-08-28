$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

$EmployeePointer = Join-Path $ProjectRoot "workforce_planner\v6\employee_readiness_runs\LATEST_EMPLOYEE_READINESS_RUN.txt"
$PlanningPointer = Join-Path $ProjectRoot "workforce_planner\v5\final_method_gate_runs_v503\LATEST_BEST_AVAILABLE_PLANNING_RUN.txt"

if (-not (Test-Path $EmployeePointer)) {
    throw "Latest employee-readiness pointer was not found: $EmployeePointer"
}
if (-not (Test-Path $PlanningPointer)) {
    throw "Latest final planning pointer was not found: $PlanningPointer"
}

$EmployeeRun = (Get-Content $EmployeePointer -Raw).Trim()
$PlanningRun = (Get-Content $PlanningPointer -Raw).Trim()
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v6\all_employee_scenario\build_all_employee_scenario_v610.py"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v6\all_employee_scenario_runs"

if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCommand = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCommand = "python"
} else {
    throw "Python was not found."
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$LogPath = Join-Path $OutputRoot ("all_employee_scenario_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force
try {
    Write-Host "Starting all-employee development scenario v6.1.0..." -ForegroundColor Cyan
    Write-Host "Every employee record will be included."
    Write-Host "Official availability and constraint templates will remain unchanged."
    Write-Host "No CP-SAT allocation or RL policy will run."

    & $PythonCommand $PythonScript `
        --employee-run $EmployeeRun `
        --planning-run $PlanningRun `
        --output-root $OutputRoot

    if ($LASTEXITCODE -ne 0) {
        throw "All-employee scenario returned exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "All-employee development scenario completed." -ForegroundColor Green
    Write-Host "Run .\CHECK_ALL_EMPLOYEE_SCENARIO_v6.1.0.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
