$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

$CropRun = Get-ChildItem (Join-Path $ProjectRoot "outputs") -Directory `
    -Filter "gpu_candidates_*" -ErrorAction SilentlyContinue |
    Where-Object { Test-Path (Join-Path $_.FullName "gpu_batch_summary.csv") } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $CropRun) {
    throw "No crop GPU summary was found."
}

$CropSummary = @(Import-Csv (Join-Path $CropRun.FullName "gpu_batch_summary.csv"))
$CropPass = @($CropSummary | Where-Object status -eq "PASS").Count
$CropFail = @($CropSummary | Where-Object status -ne "PASS")
Write-Host "Crop candidate run: $($CropRun.FullName)" -ForegroundColor Cyan
Write-Host "Crop status: $CropPass / 33 PASS" -ForegroundColor $(if ($CropFail.Count -eq 0) { "Green" } else { "Yellow" })
$CropSummary | Sort-Object estate | Format-Table estate,status,mode,duration_minutes,message -AutoSize

$CandidateRoot = Join-Path $ProjectRoot "workforce_planner\v2\model_candidates"
$WorkforceRun = Get-ChildItem $CandidateRoot -Directory -Filter "productivity_gpu_*" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $WorkforceRun) {
    Write-Host "Workforce-productivity training has not created a candidate run yet." -ForegroundColor Yellow
    exit 0
}

$WorkforceSummaryPath = Join-Path $WorkforceRun.FullName "productivity_gpu_batch_summary.csv"
Write-Host "Workforce candidate run: $($WorkforceRun.FullName)" -ForegroundColor Cyan
if (-not (Test-Path $WorkforceSummaryPath)) {
    Write-Host "Workforce-productivity training is still running." -ForegroundColor Yellow
    $Log = Join-Path $WorkforceRun.FullName "all_estate_productivity_gpu.log"
    if (Test-Path $Log) { Get-Content $Log -Tail 30 }
    exit 0
}

$WorkforceSummary = @(Import-Csv $WorkforceSummaryPath)
$WorkforceSummary | Sort-Object estate | Format-Table estate,status,history_class,test_mae_improvement_pct,duration_minutes -AutoSize
Write-Host "Workforce estate results recorded: $($WorkforceSummary.Count) / 33" -ForegroundColor Green
Write-Host "RL has not started. Field demand and a separate multi-estate RL build are required next." -ForegroundColor Yellow
