$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Run = Get-ChildItem (Join-Path $ProjectRoot "outputs") -Directory -Filter "gpu_candidates_*" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $Run) { Write-Host "No crop candidate run found." -ForegroundColor Red; exit 1 }

$SummaryPath = Join-Path $Run.FullName "gpu_batch_summary.csv"
if (Test-Path $SummaryPath) {
    $Rows = @(Import-Csv $SummaryPath)
    $Pass = @($Rows | Where-Object status -eq "PASS").Count
    $Fail = @($Rows | Where-Object status -ne "PASS")
    Write-Host "Crop status: $Pass / $($Rows.Count) PASS" -ForegroundColor Cyan
    if ($Fail.Count) { $Fail | Format-Table estate,status,mode,message -AutoSize }
}

$RepairLog = Join-Path $Run.FullName "repair_8_estates_v2.1.4.log"
if (Test-Path $RepairLog) {
    Write-Host "`nLatest repair messages:" -ForegroundColor Cyan
    Get-Content $RepairLog -Tail 20
}

$WorkforceRuns = Get-ChildItem (Join-Path $ProjectRoot "workforce_planner\v2\model_candidates") `
    -Directory -Filter "productivity_gpu_*" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending
$Workforce = $WorkforceRuns | Select-Object -First 1
if ($Workforce) {
    Write-Host "`nLatest workforce run: $($Workforce.FullName)" -ForegroundColor Cyan
    $WorkforceSummary = Join-Path $Workforce.FullName "productivity_gpu_batch_summary.csv"
    if (Test-Path $WorkforceSummary) {
        Import-Csv $WorkforceSummary | Group-Object status | Select-Object Name,Count | Format-Table -AutoSize
    }
    else {
        $WorkforceLog = Join-Path $Workforce.FullName "all_estate_productivity_gpu.log"
        if (Test-Path $WorkforceLog) { Get-Content $WorkforceLog -Tail 15 }
        else { Write-Host "Workforce run folder exists; training is preparing inputs." -ForegroundColor Yellow }
    }
}
else {
    Write-Host "`nWorkforce-productivity training has not started yet." -ForegroundColor Yellow
}
