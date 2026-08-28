$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v3\data_audit_runs"
$Pointer = Join-Path $OutputRoot "LATEST_DATA_AUDIT.txt"

if (-not (Test-Path $Pointer)) {
    Write-Host "No completed corrected audit was found." -ForegroundColor Yellow
    exit 1
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$SummaryPath = Join-Path $RunFolder "audit_summary.json"
$EstatePath = Join-Path $RunFolder "estate_data_audit.csv"

if (-not (Test-Path $SummaryPath)) {
    throw "Audit summary is missing: $SummaryPath"
}

$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "TTE corrected data audit: $RunFolder" -ForegroundColor Cyan
Write-Host ("Package version: {0}" -f $Summary.package_version)
Write-Host ("Archives: {0} / {1}" -f $Summary.archives_found, $Summary.expected_estates)
Write-Host ("READY: {0}" -f $Summary.ready) -ForegroundColor Green
Write-Host ("CONDITIONAL: {0}" -f $Summary.conditional) -ForegroundColor Yellow
Write-Host ("NOT READY: {0}" -f $Summary.not_ready) -ForegroundColor Red
Write-Host ("Duration: {0} minutes" -f $Summary.duration_minutes)

if ($Summary.identity_mismatch_estates.Count -gt 0) {
    Write-Host ""
    Write-Host "Archive/workbook identity verification required:" -ForegroundColor Yellow
    $Summary.identity_mismatch_estates | ForEach-Object { Write-Host " - $_" }
}

if (Test-Path $EstatePath) {
    Write-Host ""
    Write-Host "Estates requiring review:" -ForegroundColor Yellow
    Import-Csv $EstatePath |
        Where-Object {
            $_.readiness_status -ne "READY" -or
            [int]$_.identity_mismatch_count -gt 0
        } |
        Sort-Object @{Expression={[int]$_.readiness_score}} |
        Select-Object estate, readiness_status, readiness_score,
            identity_mismatch_count, valid_rows, date_max, blocking_reasons |
        Format-Table -AutoSize -Wrap
}

Write-Host ""
Write-Host "No live model, portal, allocator or RL policy was changed." -ForegroundColor Green
