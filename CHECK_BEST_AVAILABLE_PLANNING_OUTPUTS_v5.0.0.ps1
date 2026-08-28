$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v5\best_available_planning_runs"
$Pointer = Join-Path $OutputRoot "LATEST_BEST_AVAILABLE_PLANNING_RUN.txt"

if (-not (Test-Path $Pointer)) {
    Write-Host "No completed best-available planning run was found." -ForegroundColor Yellow
    exit 1
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$SummaryPath = Join-Path $RunFolder "run_summary.json"
$EstateDemandPath = Join-Path $RunFolder "planning\estate_required_plucker_assignments.csv"
$MethodPath = Join-Path $RunFolder "quality\method_and_gate_register.csv"
$ReconciliationPath = Join-Path $RunFolder "quality\hierarchy_reconciliation.csv"

if (-not (Test-Path $SummaryPath)) {
    throw "Run summary is missing: $SummaryPath"
}

$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "TTE best-available planning run: $RunFolder" -ForegroundColor Cyan
Write-Host ("Status: {0}" -f $Summary.status)
Write-Host ("Estates: {0}" -f $Summary.estates)
Write-Host ("Forecast dates: {0}" -f $Summary.forecast_dates)
Write-Host ("Estate rows: {0}" -f $Summary.estate_planning_rows)
Write-Host ("Division rows: {0}" -f $Summary.division_planning_rows)
Write-Host ("Active field rows: {0}" -f $Summary.active_field_planning_rows)
Write-Host ("Field demand rows: {0}" -f $Summary.field_plucker_demand_rows)
Write-Host ("Reconciliation failures: {0}" -f $Summary.reconciliation_failures)
Write-Host ("Schedule failures: {0}" -f $Summary.schedule_failures)
Write-Host ("Operational status: {0}" -f $Summary.operational_status) -ForegroundColor Yellow
Write-Host ("Duration: {0} minutes" -f $Summary.duration_minutes)

if (Test-Path $MethodPath) {
    Write-Host ""
    Write-Host "Method and gate register:" -ForegroundColor Cyan
    Import-Csv $MethodPath |
        Sort-Object @{Expression={[double]$_.best_selected_wape_pct}} |
        Select-Object estate, development_gate, best_selected_wape_pct,
            ensemble_policy |
        Format-Table -AutoSize
}

if (Test-Path $EstateDemandPath) {
    Write-Host ""
    Write-Host "First forecast date — estate assignment demand:" -ForegroundColor Cyan
    $Rows = Import-Csv $EstateDemandPath
    $FirstDate = ($Rows | Sort-Object date | Select-Object -First 1).date
    $Rows |
        Where-Object { $_.date -eq $FirstDate } |
        Sort-Object estate |
        Select-Object estate, central_crop_kg, upper_conservative_crop_kg,
            expected_plucker_assignments, recommended_plucker_assignments,
            buffer_assignments, development_gate |
        Format-Table -AutoSize
}

if (Test-Path $ReconciliationPath) {
    $Bad = Import-Csv $ReconciliationPath |
        Where-Object { $_.reconciliation_status -ne "PASS" }

    if (@($Bad).Count -eq 0) {
        Write-Host ""
        Write-Host "Hierarchy reconciliation: PASS" -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host "Hierarchy reconciliation failures found." -ForegroundColor Red
        $Bad | Select-Object -First 20 | Format-Table -AutoSize
    }
}

Write-Host ""
Write-Host "Main outputs:" -ForegroundColor Cyan
Write-Host (Join-Path $RunFolder "planning\estate_required_plucker_assignments.csv")
Write-Host (Join-Path $RunFolder "planning\division_crop_and_plucker_demand.csv")
Write-Host (Join-Path $RunFolder "planning\field_required_plucker_assignments.csv")
Write-Host ""
Write-Host "These are development planning outputs, not unique employee allocations." -ForegroundColor Green
