$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v7\cp_sat_development_runs"
$Pointer = Join-Path $OutputRoot "LATEST_CP_SAT_DEVELOPMENT_RUN.txt"

if (-not (Test-Path $Pointer)) {
    Write-Host "No completed CP-SAT development run was found." -ForegroundColor Yellow
    exit 1
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$Summary = Get-Content (Join-Path $RunFolder "run_summary.json") -Raw | ConvertFrom-Json
$EstateResults = Join-Path $RunFolder "quality\cp_sat_estate_results.csv"
$FieldResults = Join-Path $RunFolder "quality\cp_sat_field_results.csv"

Write-Host ""
Write-Host "TTE CP-SAT development allocation v7.0.0" -ForegroundColor Cyan
Write-Host ("Run folder: {0}" -f $RunFolder)
Write-Host ("Status: {0}" -f $Summary.status)
Write-Host ("Planning date: {0}" -f $Summary.planning_date)
Write-Host ("Scenarios: {0}" -f ($Summary.scenarios -join ", "))
Write-Host ("Estates solved: {0}" -f $Summary.estates_solved)
Write-Host ("Assignment rows: {0}" -f $Summary.assignment_rows)
Write-Host ("Field result rows: {0}" -f $Summary.field_result_rows)
Write-Host ("Solver failures: {0}" -f $Summary.solver_failures)
Write-Host ("Duplicate employee assignment failures: {0}" -f $Summary.duplicate_employee_assignment_failures)
Write-Host ("Field reconciliation failures: {0}" -f $Summary.field_reconciliation_failures)
Write-Host ("Operational status: {0}" -f $Summary.operational_status)
Write-Host ("RL started: {0}" -f $Summary.rl_started)

Write-Host ""
Write-Host "Estate results:" -ForegroundColor Cyan
Import-Csv $EstateResults |
    Sort-Object scenario, estate |
    Select-Object scenario, estate, solver_status,
        employees_assigned, fields, fields_fully_covered,
        total_target_crop_kg, total_assigned_capacity_kg,
        total_under_kg, total_over_kg, coverage_pct,
        duplicate_employee_assignments, wall_time_seconds |
    Format-Table -AutoSize

Write-Host ""
Write-Host "Fields requiring review:" -ForegroundColor Cyan
$Review = Import-Csv $FieldResults |
    Where-Object {
        [double]$_.under_kg -gt 0.5 -or
        [double]$_.over_kg -gt 10
    } |
    Sort-Object scenario, estate, division, field

if (@($Review).Count -eq 0) {
    Write-Host "No field exceeded the review thresholds." -ForegroundColor Green
} else {
    $Review |
        Select-Object scenario, estate, division, field,
            target_crop_kg, assigned_employee_count,
            assigned_capacity_kg, under_kg, over_kg,
            coverage_pct, field_status |
        Format-Table -AutoSize
}

Write-Host ""
Write-Host "Assignment file:" -ForegroundColor Cyan
Write-Host (Join-Path $RunFolder "assignments\cp_sat_employee_field_assignments.csv")
Write-Host ""
Write-Host "This remains development simulation only. No live employee assignment has been made." -ForegroundColor Yellow
