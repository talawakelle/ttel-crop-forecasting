$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v6\employee_readiness_runs"
$Pointer = Join-Path $OutputRoot "LATEST_EMPLOYEE_READINESS_RUN.txt"
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v6\employee_readiness\recheck_employee_inputs_v600.py"

if (-not (Test-Path $Pointer)) {
    throw "No completed employee readiness run was found."
}
$RunFolder = (Get-Content $Pointer -Raw).Trim()

if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCommand = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCommand = "python"
} else {
    throw "Python was not found."
}

& $PythonCommand $PythonScript --run-folder $RunFolder
if ($LASTEXITCODE -ne 0) {
    throw "Employee input recheck returned exit code $LASTEXITCODE"
}

$ResultPath = Join-Path $RunFolder "quality\cp_sat_input_recheck.csv"

Write-Host ""
Write-Host "Updated CP-SAT input readiness:" -ForegroundColor Cyan
Import-Csv $ResultPath |
    Sort-Object estate |
    Select-Object estate, recommended_assignment_demand,
        availability_confirmed_employees,
        constraints_confirmed_employees, eligible_employee_pool,
        confirmed_field_coverage_pct, necessary_supply_check,
        cp_sat_readiness |
    Format-Table -AutoSize

Write-Host ""
Write-Host "CP-SAT has not been started by this check." -ForegroundColor Green
