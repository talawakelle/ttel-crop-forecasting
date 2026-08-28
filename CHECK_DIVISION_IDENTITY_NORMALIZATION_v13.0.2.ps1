$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_2\division_identity_normalization_runs"
$Pointer = Join-Path $RunRoot "LATEST_DIVISION_IDENTITY_NORMALIZATION_V1302_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v13.0.2 division normalization run was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$CreationSummaryPath = Join-Path $RunFolder "run_summary.json"
$CreationGatePath = Join-Path $RunFolder "quality\division_normalization_review_pack_gate.csv"
$ValidationSummaryPath = Join-Path $RunFolder "validation_summary.json"
$ValidationGatePath = Join-Path $RunFolder "quality\division_normalization_gate.csv"

$Creation = Get-Content $CreationSummaryPath -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "TTE division identity normalization v13.0.2" -ForegroundColor Cyan
Write-Host ("Run folder: {0}" -f $RunFolder)
Write-Host ("Creation status: {0}" -f $Creation.status)
Write-Host ("Source allocation rows: {0}" -f $Creation.source_allocation_rows)
Write-Host ("Estates: {0}" -f $Creation.estate_count)
Write-Host ("Mapping review rows: {0}" -f $Creation.mapping_review_rows)
Write-Host ("High-confidence suggestions: {0}" -f $Creation.high_confidence_suggestions)
Write-Host ("Medium-confidence suggestions: {0}" -f $Creation.medium_confidence_suggestions)
Write-Host ("Ambiguous or low suggestions: {0}" -f $Creation.ambiguous_or_low_suggestions)
Write-Host ("Review gate: {0}" -f $Creation.review_gate)
Write-Host ("Live deployment started: {0}" -f $Creation.live_deployment_started)

Write-Host ""
Write-Host "Review-pack gate:" -ForegroundColor Cyan
Import-Csv $CreationGatePath | Format-Table -AutoSize

if (Test-Path $ValidationSummaryPath) {
    $Validation = Get-Content $ValidationSummaryPath -Raw | ConvertFrom-Json

    Write-Host ""
    Write-Host "Latest mapping validation:" -ForegroundColor Cyan
    Write-Host ("Confirmed mapping rows: {0}" -f $Validation.confirmed_mapping_rows)
    Write-Host ("Mapping failures: {0}" -f $Validation.mapping_validation_failures)
    Write-Host ("Normalized allocation rows: {0}" -f $Validation.normalized_allocation_rows)
    Write-Host ("EXPECTED primary rows: {0}" -f $Validation.expected_primary_rows)
    Write-Host ("CONSERVATIVE backup rows: {0}" -f $Validation.conservative_backup_rows)
    Write-Host ("Review gate: {0}" -f $Validation.review_gate)
    Write-Host ("Live deployment started: {0}" -f $Validation.live_deployment_started)

    Write-Host ""
    Import-Csv $ValidationGatePath | Format-Table -AutoSize
}
else {
    Write-Host ""
    Write-Host "Manager mapping input has not yet been validated." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "This remains review-only. It does not permit live employee allocation." -ForegroundColor Yellow
