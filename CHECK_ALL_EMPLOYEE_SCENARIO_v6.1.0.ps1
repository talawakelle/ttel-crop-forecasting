$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v6\all_employee_scenario_runs"
$Pointer = Join-Path $OutputRoot "LATEST_ALL_EMPLOYEE_SCENARIO_RUN.txt"

if (-not (Test-Path $Pointer)) {
    Write-Host "No completed all-employee scenario was found." -ForegroundColor Yellow
    exit 1
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$SummaryPath = Join-Path $RunFolder "run_summary.json"
$InclusionPath = Join-Path $RunFolder "quality\all_employee_inclusion_gate.csv"
$ReadinessPath = Join-Path $RunFolder "quality\all_employee_cp_sat_scenario_readiness.csv"

$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "TTE all-employee development scenario v6.1.0" -ForegroundColor Cyan
Write-Host ("Run folder: {0}" -f $RunFolder)
Write-Host ("Status: {0}" -f $Summary.status)
Write-Host ("Planning date: {0}" -f $Summary.planning_date)
Write-Host ("Employee records: {0}" -f $Summary.employee_records)
Write-Host ("Scenario roster rows: {0}" -f $Summary.scenario_roster_rows)
Write-Host ("Candidate matrix rows: {0}" -f $Summary.candidate_matrix_rows)
Write-Host ("Active field rows: {0}" -f $Summary.active_field_rows)
Write-Host ("Employees skipped: {0}" -f $Summary.employees_skipped)
Write-Host ("Field coverage failures: {0}" -f $Summary.field_candidate_coverage_failures)
Write-Host ("Ready estates for CP-SAT development simulation: {0}" -f $Summary.ready_estates_for_cp_sat_development_simulation)
Write-Host ("Official templates changed: {0}" -f $Summary.official_templates_changed)
Write-Host ("CP-SAT started: {0}" -f $Summary.cp_sat_started)
Write-Host ("RL started: {0}" -f $Summary.rl_started)

Write-Host ""
Write-Host "All-employee inclusion gate:" -ForegroundColor Cyan
Import-Csv $InclusionPath |
    Sort-Object estate |
    Select-Object estate, total_employee_records,
        employees_represented_in_candidate_matrix,
        employees_skipped, all_employee_inclusion_status |
    Format-Table -AutoSize

Write-Host ""
Write-Host "CP-SAT development-scenario readiness:" -ForegroundColor Cyan
Import-Csv $ReadinessPath |
    Sort-Object estate |
    Select-Object estate, total_employee_records,
        expected_assignment_demand, recommended_assignment_demand,
        expected_supply_gap, conservative_supply_gap,
        unique_supply_status, active_fields,
        field_candidate_coverage_pct, employees_skipped,
        cp_sat_scenario_readiness |
    Format-Table -AutoSize

Write-Host ""
Write-Host "Scenario roster:" -ForegroundColor Cyan
Write-Host (Join-Path $RunFolder "registers\all_employee_development_scenario_roster.csv")
Write-Host "Candidate matrix:" -ForegroundColor Cyan
Write-Host (Join-Path $RunFolder "candidates\all_employee_active_field_candidate_matrix.csv")
Write-Host ""
Write-Host "This is development simulation only. No live employee assignment has been made." -ForegroundColor Yellow
