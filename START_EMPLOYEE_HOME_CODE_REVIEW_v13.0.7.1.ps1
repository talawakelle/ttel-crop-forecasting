$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v13_0_7_1\employee_home_code_supervisor_review\employee_home_code_supervisor_review_v13071.py"
$MasterPath = Join-Path $ProjectRoot "workforce_planner\v13_0_7_1\employee_home_code_supervisor_review\official_division_master_sanitized.csv"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_7_1\employee_home_code_supervisor_review_runs"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

Write-Host "Starting employee home-code supervisor review source repair v13.0.7.1..." -ForegroundColor Cyan
Write-Host "The actual v13.0.6 review file will be used instead of the older source preview."
Write-Host "Automated candidates remain review aids only."
Write-Host "TLD remains unresolved."
Write-Host "No attendance, leave, fitness or live allocation will be verified."

& py -3.12 $PythonScript `
    --project-root $ProjectRoot `
    --master-path $MasterPath `
    --output-root $OutputRoot

if ($LASTEXITCODE -ne 0) {
    throw "Employee home-code review source repair returned exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Run .\CHECK_EMPLOYEE_HOME_CODE_REVIEW_v13.0.7.1.ps1"
Write-Host "Run .\OPEN_EMPLOYEE_HOME_CODE_REVIEW_v13.0.7.1.ps1"
