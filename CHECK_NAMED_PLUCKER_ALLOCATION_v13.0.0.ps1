$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v13\named_plucker_allocation_runs"
$Pointer = Join-Path $RunRoot "LATEST_NAMED_PLUCKER_ALLOCATION_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v13.0.0 named plucker allocation run was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$SummaryPath = Join-Path $RunFolder "run_summary.json"
$GatePath = Join-Path $RunFolder "quality\named_allocation_creation_gate.csv"

$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "TTE simulation named plucker allocation v13.0.0" -ForegroundColor Cyan
Write-Host ("Run folder: {0}" -f $RunFolder)
Write-Host ("Status: {0}" -f $Summary.status)
Write-Host ("Source CP-SAT run: {0}" -f $Summary.source_cp_sat_run)
Write-Host ("Source assignment file: {0}" -f $Summary.source_assignment_file)
Write-Host ("Named assignment rows: {0}" -f $Summary.named_assignment_rows)
Write-Host ("Estate count: {0}" -f $Summary.estate_count)
Write-Host ("Duplicate employee assignment failures: {0}" -f $Summary.duplicate_employee_assignment_failures)
Write-Host ("Supervisor acceptance mode: {0}" -f $Summary.supervisor_acceptance_mode)
Write-Host ("Actual supervisor verified: {0}" -f $Summary.actual_supervisor_verified)
Write-Host ("Allocation gate: {0}" -f $Summary.allocation_gate)
Write-Host ("Live deployment started: {0}" -f $Summary.live_deployment_started)

Write-Host ""
Write-Host "Named allocation gate:" -ForegroundColor Cyan
Import-Csv $GatePath | Format-Table -AutoSize

Write-Host ""
Write-Host "This allocation remains simulation-only and must not be sent to employees." -ForegroundColor Yellow
