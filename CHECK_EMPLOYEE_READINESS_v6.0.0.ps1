$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v6\employee_readiness_runs"
$Pointer = Join-Path $OutputRoot "LATEST_EMPLOYEE_READINESS_RUN.txt"

if (-not (Test-Path $Pointer)) {
    Write-Host "No completed employee readiness run was found." -ForegroundColor Yellow
    exit 1
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$SummaryPath = Join-Path $RunFolder "run_summary.json"
$ReadinessPath = Join-Path $RunFolder "quality\cp_sat_readiness_gate.csv"
$CoveragePath = Join-Path $RunFolder "quality\field_candidate_coverage.csv"

$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "TTE employee readiness layer v6.0.0" -ForegroundColor Cyan
Write-Host ("Run folder: {0}" -f $RunFolder)
Write-Host ("Status: {0}" -f $Summary.status)
Write-Host ("Planning date: {0}" -f $Summary.planning_date)
Write-Host ("Training files: {0}" -f $Summary.training_files)
Write-Host ("Source rows: {0}" -f $Summary.source_rows)
Write-Host ("Employee master rows: {0}" -f $Summary.employee_master_rows)
Write-Host ("Employee-field experience rows: {0}" -f $Summary.employee_field_experience_rows)
Write-Host ("Availability template rows: {0}" -f $Summary.availability_template_rows)
Write-Host ("Constraint template rows: {0}" -f $Summary.constraint_template_rows)
Write-Host ("Candidate matrix rows: {0}" -f $Summary.candidate_matrix_rows)
Write-Host ("First-date active fields: {0}" -f $Summary.active_field_demand_rows_first_date)
Write-Host ("Historical candidate coverage failures: {0}" -f $Summary.historical_candidate_coverage_failures)
Write-Host ("CP-SAT readiness: {0}" -f $Summary.cp_sat_readiness) -ForegroundColor Yellow

Write-Host ""
Write-Host "Estate readiness:" -ForegroundColor Cyan
Import-Csv $ReadinessPath |
    Sort-Object estate |
    Select-Object estate, recommended_assignment_demand,
        recent_employee_pool, historical_candidate_pool,
        active_fields, historical_field_coverage_pct,
        cp_sat_readiness |
    Format-Table -AutoSize

$CoverageFailures = Import-Csv $CoveragePath |
    Where-Object {
        $_.historical_candidate_coverage_status -ne "PASS"
    }

Write-Host ""
if (@($CoverageFailures).Count -eq 0) {
    Write-Host "Historical candidate coverage: PASS" -ForegroundColor Green
} else {
    Write-Host "Historical candidate coverage gaps:" -ForegroundColor Red
    $CoverageFailures |
        Select-Object estate, division, field,
            recommended_plucker_assignments, candidate_pool |
        Format-Table -AutoSize
}

Write-Host ""
Write-Host "Files to complete before CP-SAT:" -ForegroundColor Cyan
Write-Host (Join-Path $RunFolder "templates\employee_availability_template.csv")
Write-Host (Join-Path $RunFolder "templates\employee_constraints_template.csv")
Write-Host ""
Write-Host "Candidate matrix:" -ForegroundColor Cyan
Write-Host (Join-Path $RunFolder "candidates\first_date_field_employee_candidate_matrix.csv")
Write-Host ""
Write-Host "After estate managers complete both templates, run:" -ForegroundColor Yellow
Write-Host ".\RECHECK_EMPLOYEE_INPUT_READINESS_v6.0.0.ps1"
