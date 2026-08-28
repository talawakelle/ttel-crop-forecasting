$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v4\daily_hierarchy_runs"
$Pointer = Join-Path $OutputRoot "LATEST_DAILY_HIERARCHY_RUN.txt"

if (-not (Test-Path $Pointer)) {
    Write-Host "No completed daily hierarchy run was found." -ForegroundColor Yellow
    exit 1
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$SummaryPath = Join-Path $RunFolder "run_summary.json"
$SelectedPath = Join-Path $RunFolder "backtest\estate_selected_models.csv"
$ProfilePath = Join-Path $RunFolder "profiles\estate_hierarchy_profile.csv"
$ReconciliationPath = Join-Path $RunFolder "hierarchy_reconciliation_audit.csv"

if (-not (Test-Path $SummaryPath)) {
    throw "Run summary is missing: $SummaryPath"
}

$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "TTE daily hierarchy candidate: $RunFolder" -ForegroundColor Cyan
Write-Host ("Status: {0}" -f $Summary.status)
Write-Host ("Estates processed: {0} / {1}" -f $Summary.estates_processed, $Summary.archives_expected)
Write-Host ("Failed estates: {0}" -f $Summary.estates_failed)
Write-Host ("Forecast period: {0}, {1} days" -f $Summary.forecast_start, $Summary.forecast_days)
Write-Host ("Estate rows: {0}" -f $Summary.estate_forecast_rows)
Write-Host ("Division rows: {0}" -f $Summary.division_forecast_rows)
Write-Host ("Field rows: {0}" -f $Summary.field_forecast_rows)
Write-Host ("Reconciliation failures: {0}" -f $Summary.reconciliation_failures)
Write-Host ("Operational status: {0}" -f $Summary.operational_status) -ForegroundColor Yellow
Write-Host ("Duration: {0} minutes" -f $Summary.duration_minutes)

if (Test-Path $SelectedPath) {
    Write-Host ""
    Write-Host "Selected daily estate candidates:" -ForegroundColor Cyan
    Import-Csv $SelectedPath |
        Sort-Object @{Expression={[double]$_.selected_wape_pct}} |
        Select-Object estate, selected_method, test_observed_days,
            selected_mae_kg, selected_wape_pct |
        Format-Table -AutoSize
}

if (Test-Path $ProfilePath) {
    Write-Host ""
    Write-Host "Stale-source estates:" -ForegroundColor Yellow
    Import-Csv $ProfilePath |
        Where-Object { $_.data_freshness_status -ne "CURRENT_SOURCE" } |
        Select-Object estate, historical_date_max, data_age_days,
            data_freshness_status |
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
Write-Host "This remains a development candidate. No live allocation or RL has started." -ForegroundColor Green
