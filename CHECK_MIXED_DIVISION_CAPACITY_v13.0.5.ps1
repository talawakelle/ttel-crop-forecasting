$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_5\mixed_division_capacity_runs"
$Pointer = Join-Path $RunRoot "LATEST_MIXED_DIVISION_CAPACITY_V1305_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v13.0.5 mixed-division capacity run was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$CreationSummaryPath = Join-Path $RunFolder "run_summary.json"
$CreationGatePath = Join-Path $RunFolder "quality\mixed_division_capacity_creation_gate.csv"
$ValidationSummaryPath = Join-Path $RunFolder "validation_summary.json"
$ValidationGatePath = Join-Path $RunFolder "quality\mixed_division_capacity_validation_gate.csv"

$Creation = Get-Content $CreationSummaryPath -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "TTE mixed-division capacity-safe allocation v13.0.5" -ForegroundColor Cyan
Write-Host ("Run folder: {0}" -f $RunFolder)
Write-Host ("Creation status: {0}" -f $Creation.status)
Write-Host ("Source assignment rows: {0}" -f $Creation.source_assignment_rows)
Write-Host ("Employee daily groups: {0}" -f $Creation.employee_daily_groups)
Write-Host ("Single-row groups: {0}" -f $Creation.single_row_employee_groups)
Write-Host ("Multi-row groups: {0}" -f $Creation.multi_row_employee_groups)
Write-Host ("Mixed-division groups: {0}" -f $Creation.mixed_division_employee_groups)
Write-Host ("Field groups: {0}" -f $Creation.field_groups)
Write-Host ("Review gate: {0}" -f $Creation.review_gate)
Write-Host ("Live deployment started: {0}" -f $Creation.live_deployment_started)

Write-Host ""
Import-Csv $CreationGatePath | Format-Table -AutoSize

if (Test-Path $ValidationSummaryPath) {
    $Validation = Get-Content $ValidationSummaryPath -Raw | ConvertFrom-Json

    Write-Host ""
    Write-Host "Latest mixed-division capacity validation:" -ForegroundColor Cyan
    Write-Host ("Validation failures: {0}" -f $Validation.validation_failures)
    Write-Host ("Field reconciliation failures: {0}" -f $Validation.field_reconciliation_failures)
    Write-Host ("Multi-row employee groups: {0}" -f $Validation.multi_row_employee_groups)
    Write-Host ("Mixed-division employee groups: {0}" -f $Validation.mixed_division_employee_groups)
    Write-Host ("EXPECTED primary rows: {0}" -f $Validation.expected_primary_rows)
    Write-Host ("CONSERVATIVE backup rows: {0}" -f $Validation.conservative_backup_rows)
    Write-Host ("Review gate: {0}" -f $Validation.review_gate)
    Write-Host ("Employee home-code verification completed: {0}" -f $Validation.employee_home_code_verification_completed)
    Write-Host ("Live deployment started: {0}" -f $Validation.live_deployment_started)

    Write-Host ""
    Import-Csv $ValidationGatePath | Format-Table -AutoSize
}
else {
    Write-Host ""
    Write-Host "Capacity split and mixed-division review has not yet been validated." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "This remains supervisor review only. It does not permit live employee allocation." -ForegroundColor Yellow
