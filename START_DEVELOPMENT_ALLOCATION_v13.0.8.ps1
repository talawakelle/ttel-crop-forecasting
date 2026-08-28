$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v13_0_8\development_allocation_consolidation\development_allocation_consolidation_v1308.py"
$ReferenceRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_8\development_allocation_consolidation"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_8\development_allocation_consolidation_runs"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

Write-Host "Starting development allocation consolidation v13.0.8..." -ForegroundColor Cyan
Write-Host "The project will continue in management simulation-review mode."
Write-Host "Blank supervisor fields will not be treated as verified facts."
Write-Host "Open field-code and employee home-code exceptions will remain flagged."
Write-Host "No employee notification, payroll connection or live allocation will run."

& py -3.12 $PythonScript `
    --project-root $ProjectRoot `
    --output-root $OutputRoot `
    --field-reference (Join-Path $ReferenceRoot "official_field_division_code_reference.csv") `
    --home-context (Join-Path $ReferenceRoot "employee_home_code_context_reference.csv") `
    --home-exceptions (Join-Path $ReferenceRoot "employee_home_code_exception_reference.csv")

if ($LASTEXITCODE -ne 0) {
    throw "Development allocation consolidation returned exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Run .\CHECK_DEVELOPMENT_ALLOCATION_v13.0.8.ps1"
Write-Host "Run .\OPEN_DEVELOPMENT_ALLOCATION_v13.0.8.ps1"
