$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v5\final_method_gate_runs_v503"
$Pointer = Join-Path $OutputRoot "LATEST_BEST_AVAILABLE_PLANNING_RUN.txt"

if (-not (Test-Path $Pointer)) {
    Write-Host "No completed v5.0.3 final method-gate run was found." -ForegroundColor Yellow
    exit 1
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$SummaryPath = Join-Path $RunFolder "run_summary.json"
$GatePath = Join-Path $RunFolder "quality\final_three_estate_method_gate.csv"
$MethodPath = Join-Path $RunFolder "quality\method_and_gate_register.csv"
$EstateDemandPath = Join-Path $RunFolder "planning\estate_required_plucker_assignments.csv"
$ReconciliationPath = Join-Path $RunFolder "quality\hierarchy_reconciliation.csv"

if (-not (Test-Path $SummaryPath)) {
    throw "Run summary is missing: $SummaryPath"
}

$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "TTE final method-gated planning run" -ForegroundColor Cyan
Write-Host ("Run folder: {0}" -f $RunFolder)
Write-Host ("Status: {0}" -f $Summary.status)
Write-Host ("Estates: {0}" -f $Summary.estates)
Write-Host ("Forecast dates: {0}" -f $Summary.forecast_dates)
Write-Host ("Estate rows: {0}" -f $Summary.estate_planning_rows)
Write-Host ("Division rows: {0}" -f $Summary.division_planning_rows)
Write-Host ("Active field rows: {0}" -f $Summary.active_field_planning_rows)
Write-Host ("Field demand rows: {0}" -f $Summary.field_plucker_demand_rows)
Write-Host ("Reconciliation failures: {0}" -f $Summary.reconciliation_failures)
Write-Host ("Schedule failures: {0}" -f $Summary.schedule_failures)
Write-Host ("Method gate: {0}" -f $Summary.technical_method)
Write-Host ("Operational status: {0}" -f $Summary.operational_status) -ForegroundColor Yellow
Write-Host ("Duration: {0} minutes" -f $Summary.duration_minutes)

if (Test-Path $GatePath) {
    Write-Host ""
    Write-Host "Final three-estate method gate:" -ForegroundColor Cyan
    Import-Csv $GatePath |
        Sort-Object estate |
        Select-Object estate, original_method, original_wape_pct,
            pooled_method, pooled_wape_pct, improvement_points,
            final_method, decision |
        Format-Table -AutoSize
}

if (Test-Path $MethodPath) {
    Write-Host ""
    Write-Host "Final method confirmation:" -ForegroundColor Cyan
    Import-Csv $MethodPath |
        Where-Object {
            $_.estate -in @("bambarakelly", "Tillicoultry", "EildonHall")
        } |
        Select-Object estate, ensemble_policy, technical_method_status,
            final_method_decision |
        Format-Table -AutoSize
}

if (Test-Path $EstateDemandPath) {
    Write-Host ""
    Write-Host "First forecast date - estate assignment demand:" -ForegroundColor Cyan
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

    Write-Host ""
    if (@($Bad).Count -eq 0) {
        Write-Host "Hierarchy reconciliation: PASS" -ForegroundColor Green
    } else {
        Write-Host "Hierarchy reconciliation failures found." -ForegroundColor Red
        $Bad | Select-Object -First 20 | Format-Table -AutoSize
    }
}

Write-Host ""
Write-Host "Main output files:" -ForegroundColor Cyan
Write-Host (Join-Path $RunFolder "planning\estate_required_plucker_assignments.csv")
Write-Host (Join-Path $RunFolder "planning\division_crop_and_plucker_demand.csv")
Write-Host (Join-Path $RunFolder "planning\field_required_plucker_assignments.csv")
Write-Host ""
Write-Host "This version is the final existing-data method selection." -ForegroundColor Green
