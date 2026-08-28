$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v12_0_1\supervisor_shadow_review_runs"
$Pointer = Join-Path $RunRoot "LATEST_SUPERVISOR_SHADOW_REVIEW_V1201_RUN.txt"

if (-not (Test-Path $Pointer)) {
    Write-Host "No v12.0.1 supervisor shadow review pack was found." -ForegroundColor Yellow
    exit 1
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$CreationSummaryPath = Join-Path $RunFolder "run_summary.json"
$CreationGatePath = Join-Path $RunFolder "quality\review_pack_creation_gate.csv"
$ValidationSummaryPath = Join-Path $RunFolder "validation_summary.json"
$ValidationGatePath = Join-Path $RunFolder "quality\supervisor_shadow_review_gate.csv"

$CreationSummary = Get-Content $CreationSummaryPath -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "TTE supervisor shadow review identity repair v12.0.1" -ForegroundColor Cyan
Write-Host ("Run folder: {0}" -f $RunFolder)
Write-Host ("Creation status: {0}" -f $CreationSummary.status)
Write-Host ("Case review rows: {0}" -f $CreationSummary.case_review_rows)
Write-Host ("Estate context rows: {0}" -f $CreationSummary.estate_context_rows)
Write-Host ("Employee template rows: {0}" -f $CreationSummary.employee_status_template_rows)
Write-Host ("Employee identity key: {0}" -f $CreationSummary.employee_identity_key)
Write-Host ("Employee identity duplicates: {0}" -f $CreationSummary.employee_identity_duplicate_count)
Write-Host ("Employee estates: {0}" -f $CreationSummary.employee_estate_count)
Write-Host ("Employee source: {0}" -f $CreationSummary.employee_source_path)
Write-Host ("Creation review gate: {0}" -f $CreationSummary.review_gate)
Write-Host ("Live deployment started: {0}" -f $CreationSummary.live_deployment_started)

Write-Host ""
Write-Host "Identity-repaired pack creation gate:" -ForegroundColor Cyan
Import-Csv $CreationGatePath | Format-Table -AutoSize

if (Test-Path $ValidationSummaryPath) {
    $ValidationSummary = Get-Content $ValidationSummaryPath -Raw | ConvertFrom-Json
    Write-Host ""
    Write-Host "Latest review validation:" -ForegroundColor Cyan
    Write-Host ("Employee identity rows: {0}" -f $ValidationSummary.employee_template_rows)
    Write-Host ("Unique composite keys: {0}" -f $ValidationSummary.employee_unique_composite_keys)
    Write-Host ("Employee sample selected: {0}" -f $ValidationSummary.employee_sample_rows_selected)
    Write-Host ("Review gate: {0}" -f $ValidationSummary.review_gate)
    Write-Host ("Live deployment started: {0}" -f $ValidationSummary.live_deployment_started)

    Write-Host ""
    Import-Csv $ValidationGatePath | Format-Table -AutoSize
}
else {
    Write-Host ""
    Write-Host "Supervisor input has not yet been validated." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "This remains shadow review only. It does not permit live employee assignment." -ForegroundColor Yellow
