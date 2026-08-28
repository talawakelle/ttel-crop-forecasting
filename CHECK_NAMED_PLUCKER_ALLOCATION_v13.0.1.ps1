$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_1\named_plucker_allocation_runs"
$Pointer = Join-Path $RunRoot "LATEST_NAMED_PLUCKER_ALLOCATION_V1301_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v13.0.1 named plucker allocation run was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$SummaryPath = Join-Path $RunFolder "run_summary.json"
$GatePath = Join-Path $RunFolder "quality\named_allocation_creation_gate.csv"
$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "TTE named plucker allocation kg repair v13.0.1" -ForegroundColor Cyan
Write-Host ("Run folder: {0}" -f $RunFolder)
Write-Host ("Status: {0}" -f $Summary.status)
Write-Host ("Named assignment rows: {0}" -f $Summary.named_assignment_rows)
Write-Host ("Estate count: {0}" -f $Summary.estate_count)
Write-Host ("Duplicate employee assignments: {0}" -f $Summary.duplicate_employee_assignment_failures)
Write-Host ("Missing field crop kg rows: {0}" -f $Summary.missing_field_crop_kg_rows)
Write-Host ("Missing plucker capacity kg rows: {0}" -f $Summary.missing_plucker_capacity_kg_rows)
Write-Host ("Missing field assigned capacity kg rows: {0}" -f $Summary.missing_field_assigned_capacity_kg_rows)
Write-Host ("Allocation gate: {0}" -f $Summary.allocation_gate)
Write-Host ("Live deployment started: {0}" -f $Summary.live_deployment_started)

Write-Host ""
Import-Csv $GatePath | Format-Table -AutoSize

Write-Host ""
Write-Host "This remains simulation-only and must not be issued to employees." -ForegroundColor Yellow
