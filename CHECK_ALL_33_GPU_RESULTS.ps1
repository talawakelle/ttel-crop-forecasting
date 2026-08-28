$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Run = Get-ChildItem (Join-Path $ProjectRoot "outputs") -Directory `
    -Filter "gpu_candidates_*" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $Run) { throw "No all-estate GPU candidate run was found." }
$SummaryPath = Join-Path $Run.FullName "gpu_batch_summary.csv"
if (-not (Test-Path $SummaryPath)) { throw "GPU batch summary not found: $SummaryPath" }
$Summary = @(Import-Csv $SummaryPath)
$Passed = @($Summary | Where-Object status -eq "PASS")
$Failed = @($Summary | Where-Object status -ne "PASS")

$Selections = foreach ($EstateRun in Get-ChildItem $Run.FullName -Directory -Filter "*_provisional") {
    $MetricsPath = Join-Path $EstateRun.FullName "model_metrics.csv"
    if (-not (Test-Path $MetricsPath)) { continue }
    $Metrics = Import-Csv $MetricsPath
    foreach ($Row in $Metrics | Where-Object { $_.selected -eq "True" }) {
        [PSCustomObject]@{
            estate = $EstateRun.Name -replace '_provisional$',''
            horizon_weeks = $Row.horizon_weeks
            selected_method = $Row.method
            validation_wape_pct = [math]::Round([double]$Row.wape_pct, 2)
            gpu_selected = $Row.method -like "*GPU CatBoost*"
        }
    }
}

Write-Host "GPU candidate run: $($Run.FullName)" -ForegroundColor Cyan
Write-Host "Estates passed: $($Passed.Count) / $($Summary.Count)" -ForegroundColor Green
Write-Host "Estates failed: $($Failed.Count)" -ForegroundColor $(if ($Failed.Count) { "Red" } else { "Green" })
$Summary | Sort-Object estate | Format-Table estate,status,mode,duration_minutes,message -AutoSize
Write-Host "Selected method by estate and horizon:" -ForegroundColor Cyan
$Selections | Sort-Object estate,horizon_weeks | Format-Table -AutoSize
Write-Host "GPU CatBoost selected horizons: $(@($Selections | Where-Object gpu_selected).Count) / $($Selections.Count)" -ForegroundColor Yellow

if ($Failed.Count) {
    Write-Warning "Do not promote this run. Correct the failed estates and rerun."
}
else {
    Write-Host "Candidate training completed. Review WAPE before replacing the live portfolio." -ForegroundColor Green
}

