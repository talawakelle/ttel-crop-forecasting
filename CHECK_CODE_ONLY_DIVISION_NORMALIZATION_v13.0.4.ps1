$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_4\code_only_division_normalization_runs"
$Pointer = Join-Path $RunRoot "LATEST_CODE_ONLY_DIVISION_NORMALIZATION_V1304_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v13.0.4 code-only division run was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$CreationSummaryPath = Join-Path $RunFolder "run_summary.json"
$CreationGatePath = Join-Path $RunFolder "quality\code_only_evidence_pack_gate.csv"
$ValidationSummaryPath = Join-Path $RunFolder "validation_summary.json"
$ValidationGatePath = Join-Path $RunFolder "quality\code_only_division_normalization_gate.csv"

$Creation = Get-Content $CreationSummaryPath -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "TTE code-only division normalization v13.0.4" -ForegroundColor Cyan
Write-Host ("Run folder: {0}" -f $RunFolder)
Write-Host ("Creation status: {0}" -f $Creation.status)
Write-Host ("Source allocation rows: {0}" -f $Creation.source_allocation_rows)
Write-Host ("Field-division context rows: {0}" -f $Creation.field_division_context_rows)
Write-Host ("Employee home-code context keys: {0}" -f $Creation.employee_home_code_context_keys)
Write-Host ("Estates: {0}" -f $Creation.estate_count)
Write-Host ("Review gate: {0}" -f $Creation.review_gate)
Write-Host ("Live deployment started: {0}" -f $Creation.live_deployment_started)

Write-Host ""
Write-Host "Code-only evidence-pack gate:" -ForegroundColor Cyan
Import-Csv $CreationGatePath | Format-Table -AutoSize

if (Test-Path $ValidationSummaryPath) {
    $Validation = Get-Content $ValidationSummaryPath -Raw | ConvertFrom-Json

    Write-Host ""
    Write-Host "Latest code-only validation:" -ForegroundColor Cyan
    Write-Host ("Verified field-context keys: {0}" -f $Validation.verified_field_context_keys)
    Write-Host ("Code evidence failures: {0}" -f $Validation.code_evidence_failures)
    Write-Host ("Normalized allocation rows: {0}" -f $Validation.normalized_allocation_rows)
    Write-Host ("EXPECTED primary rows: {0}" -f $Validation.expected_primary_rows)
    Write-Host ("CONSERVATIVE backup rows: {0}" -f $Validation.conservative_backup_rows)
    Write-Host ("Review gate: {0}" -f $Validation.review_gate)
    Write-Host ("Employee home-code verification completed: {0}" -f $Validation.employee_home_code_verification_completed)
    Write-Host ("Live deployment started: {0}" -f $Validation.live_deployment_started)

    Write-Host ""
    Import-Csv $ValidationGatePath | Format-Table -AutoSize
}
else {
    Write-Host ""
    Write-Host "Official field division-code input has not yet been validated." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "This remains code comparison and supervisor review only. It does not permit live employee allocation." -ForegroundColor Yellow
