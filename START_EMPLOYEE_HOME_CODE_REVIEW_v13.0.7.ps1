$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v13_0_7\employee_home_code_supervisor_review\employee_home_code_supervisor_review_v1307.py"
$MasterPath = Join-Path $ProjectRoot "workforce_planner\v13_0_7\employee_home_code_supervisor_review\official_division_master_sanitized.csv"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_7\employee_home_code_supervisor_review_runs"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

Write-Host "Starting employee home-code supervisor review v13.0.7..." -ForegroundColor Cyan
Write-Host "Automated candidates are review aids only."
Write-Host "Ambiguous historical codes require employee-level review."
Write-Host "Today's assigned division will not be used as proof of home division."
Write-Host "TLD remains unresolved."
Write-Host "No attendance, leave, fitness or live allocation will be verified."

& py -3.12 $PythonScript `
    --project-root $ProjectRoot `
    --master-path $MasterPath `
    --output-root $OutputRoot

if ($LASTEXITCODE -ne 0) {
    throw "Employee home-code review returned exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Run .\CHECK_EMPLOYEE_HOME_CODE_REVIEW_v13.0.7.ps1"
Write-Host "Run .\OPEN_EMPLOYEE_HOME_CODE_REVIEW_v13.0.7.ps1"
