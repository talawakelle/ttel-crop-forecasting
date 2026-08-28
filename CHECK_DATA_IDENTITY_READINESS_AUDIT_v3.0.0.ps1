$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v3\data_audit_runs"
$LatestPointer = Join-Path $OutputRoot "LATEST_DATA_AUDIT.txt"

if (-not (Test-Path $LatestPointer)) {
    Write-Host "No completed data audit was found." -ForegroundColor Yellow
    Write-Host "Start it with: .\START_DATA_IDENTITY_READINESS_AUDIT_v3.0.0.ps1"
    exit 1
}

$RunFolder = (Get-Content $LatestPointer -Raw).Trim()
$SummaryFile = Join-Path $RunFolder "audit_summary.json"
$EstateFile = Join-Path $RunFolder "estate_data_audit.csv"

if (-not (Test-Path $SummaryFile)) {
    throw "Audit summary is missing: $SummaryFile"
}

$Summary = Get-Content $SummaryFile -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "TTE data audit run: $RunFolder" -ForegroundColor Cyan
Write-Host ("Archives: {0} / {1}" -f $Summary.archives_found, $Summary.expected_estates)
Write-Host ("READY: {0}" -f $Summary.ready) -ForegroundColor Green
Write-Host ("CONDITIONAL: {0}" -f $Summary.conditional) -ForegroundColor Yellow
Write-Host ("NOT READY: {0}" -f $Summary.not_ready) -ForegroundColor Red
Write-Host ("Duration: {0} minutes" -f $Summary.duration_minutes)

if ($Summary.identity_mismatch_estates.Count -gt 0) {
    Write-Host ""
    Write-Host "Archive/workbook identity mismatches:" -ForegroundColor Yellow
    $Summary.identity_mismatch_estates | ForEach-Object { Write-Host " - $_" }
}

if (Test-Path $EstateFile) {
    Write-Host ""
    Write-Host "Estates requiring review:" -ForegroundColor Yellow
    Import-Csv $EstateFile |
        Where-Object { $_.readiness_status -ne "READY" -or [int]$_.identity_mismatch_count -gt 0 } |
        Sort-Object @{Expression={[int]$_.readiness_score}} |
        Select-Object estate, readiness_status, readiness_score, identity_mismatch_count, date_max, blocking_reasons |
        Format-Table -AutoSize -Wrap
}

Write-Host ""
Write-Host "This audit did not change any live model or portal." -ForegroundColor Green
