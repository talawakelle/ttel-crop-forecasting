$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$CandidateRoot = Join-Path $ProjectRoot "workforce_planner\v2\model_candidates"
$Run = Get-ChildItem $CandidateRoot -Directory -Filter "productivity_gpu_*" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $Run) { throw "No all-estate workforce productivity candidate run was found." }

$BatchPath = Join-Path $Run.FullName "productivity_gpu_batch_summary.csv"
if (-not (Test-Path $BatchPath)) {
    $Log = Join-Path $Run.FullName "all_estate_productivity_gpu.log"
    Write-Host "Training is still running or stopped before the final summary: $($Run.FullName)" -ForegroundColor Yellow
    if (Test-Path $Log) { Get-Content $Log -Tail 40 }
    exit 0
}

$Rows = @(Import-Csv $BatchPath)
$Approved = @($Rows | Where-Object status -eq "APPROVED_CANDIDATE")
$Rejected = @($Rows | Where-Object status -eq "REJECTED")
$Failed = @($Rows | Where-Object status -eq "FAILED")
Write-Host "Workforce productivity GPU run: $($Run.FullName)" -ForegroundColor Cyan
Write-Host "Approved candidates: $($Approved.Count) / $($Rows.Count)" -ForegroundColor Green
Write-Host "Rejected by accuracy gate: $($Rejected.Count)" -ForegroundColor Yellow
Write-Host "Failed: $($Failed.Count)" -ForegroundColor $(if ($Failed.Count) { "Red" } else { "Green" })
$Rows | Sort-Object estate | Format-Table estate,status,history_class,test_mae_improvement_pct,duration_minutes,message -AutoSize
Write-Host "No candidate is approved for live employee allocation until estate-specific shadow mode is completed." -ForegroundColor Yellow
