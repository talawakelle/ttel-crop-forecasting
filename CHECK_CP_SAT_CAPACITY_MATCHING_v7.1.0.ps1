$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v7\cp_sat_capacity_matching_runs"
$Pointer = Join-Path $OutputRoot "LATEST_CP_SAT_CAPACITY_MATCHING_RUN.txt"

if (-not (Test-Path $Pointer)) {
    Write-Host "No completed capacity-matching run was found." -ForegroundColor Yellow
    exit 1
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$Summary = Get-Content (Join-Path $RunFolder "run_summary.json") -Raw | ConvertFrom-Json
$ScenarioSummary = Join-Path $RunFolder "quality\cp_sat_capacity_scenario_summary.csv"
$EstateResults = Join-Path $RunFolder "quality\cp_sat_capacity_estate_results.csv"
$FieldResults = Join-Path $RunFolder "quality\cp_sat_capacity_field_results.csv"

Write-Host ""
Write-Host "TTE CP-SAT capacity matching v7.1.0" -ForegroundColor Cyan
Write-Host ("Run folder: {0}" -f $RunFolder)
Write-Host ("Status: {0}" -f $Summary.status)
Write-Host ("Performance gate: {0}" -f $Summary.performance_gate)
Write-Host ("Planning date: {0}" -f $Summary.planning_date)
Write-Host ("Employee master records: {0}" -f $Summary.employee_master_records)
Write-Host ("Audit roster records: {0}" -f $Summary.audit_roster_records)
Write-Host ("Unique solver employee IDs: {0}" -f $Summary.unique_solver_employee_ids)
Write-Host ("Duplicate employee ID records: {0}" -f $Summary.duplicate_employee_id_records)
Write-Host ("Expanded candidate edges: {0}" -f $Summary.expanded_candidate_edges)
Write-Host ("Active fields per scenario: {0}" -f $Summary.active_fields_per_scenario)
Write-Host ("Expected field result rows: {0}" -f $Summary.expected_field_result_rows)
Write-Host ("Actual field result rows: {0}" -f $Summary.actual_field_result_rows)
Write-Host ("Field identity failures: {0}" -f $Summary.field_identity_failures)
Write-Host ("Assignment rows: {0}" -f $Summary.assignment_rows)
Write-Host ("Solver failures: {0}" -f $Summary.solver_failures)
Write-Host ("Duplicate employee assignment failures: {0}" -f $Summary.duplicate_employee_assignment_failures)
Write-Host ("Field reconciliation failures: {0}" -f $Summary.field_reconciliation_failures)
Write-Host ("RL started: {0}" -f $Summary.rl_started)

Write-Host ""
Write-Host "Scenario performance:" -ForegroundColor Cyan
Import-Csv $ScenarioSummary |
    Format-Table scenario, field_rows, fields_coverage_95_plus,
        uncovered_fields, total_target_crop_kg, total_under_kg,
        total_over_kg, effective_coverage_pct -AutoSize

Write-Host ""
Write-Host "Estate performance:" -ForegroundColor Cyan
Import-Csv $EstateResults |
    Sort-Object scenario, estate |
    Select-Object scenario, estate, solver_status,
        employees_assigned, fields, fields_coverage_95_plus,
        uncovered_fields, total_target_crop_kg,
        total_under_kg, total_over_kg,
        effective_coverage_pct,
        duplicate_employee_assignments,
        wall_time_seconds |
    Format-Table -AutoSize

Write-Host ""
Write-Host "Top fields requiring review:" -ForegroundColor Cyan
$Review = Import-Csv $FieldResults |
    Where-Object {
        [double]$_.coverage_pct -lt 95 -or
        [double]$_.over_kg -gt 15
    } |
    Sort-Object `
        @{Expression={[double]$_.under_kg}; Descending=$true},
        scenario, estate, division, field |
    Select-Object -First 50

if (@($Review).Count -eq 0) {
    Write-Host "No field exceeded the review thresholds." -ForegroundColor Green
} else {
    $Review |
        Select-Object scenario, estate, division, field,
            target_crop_kg, reference_assignment_demand,
            assigned_employee_count, assigned_capacity_kg,
            under_kg, over_kg, coverage_pct, field_status |
        Format-Table -AutoSize
}

Write-Host ""
Write-Host "Assignment file:" -ForegroundColor Cyan
Write-Host (Join-Path $RunFolder "assignments\cp_sat_capacity_matched_assignments.csv")
Write-Host ""
Write-Host "This is development simulation only. RL training remains blocked until the capacity gate is reviewed." -ForegroundColor Yellow
