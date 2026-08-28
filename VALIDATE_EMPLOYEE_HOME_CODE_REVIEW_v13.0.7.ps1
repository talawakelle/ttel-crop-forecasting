$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v13_0_7\employee_home_code_supervisor_review\employee_home_code_supervisor_review_v1307.py"
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_7\employee_home_code_supervisor_review_runs"
$Pointer = Join-Path $RunRoot "LATEST_EMPLOYEE_HOME_CODE_REVIEW_V1307_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v13.0.7 employee home-code review run was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()

& py -3.12 $PythonScript --validate-run $RunFolder

if ($LASTEXITCODE -ne 0) {
    throw "Employee home-code review validation returned exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Run .\CHECK_EMPLOYEE_HOME_CODE_REVIEW_v13.0.7.ps1"
