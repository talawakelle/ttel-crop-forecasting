$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_3\official_division_evidence_runs"
$Pointer = Join-Path $RunRoot "LATEST_OFFICIAL_DIVISION_EVIDENCE_V1303_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v13.0.3 official evidence run was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$CreationSummaryPath = Join-Path $RunFolder "run_summary.json"
$CreationGatePath = Join-Path $RunFolder "quality\official_evidence_pack_gate.csv"
$ValidationSummaryPath = Join-Path $RunFolder "validation_summary.json"
$ValidationGatePath = Join-Path $RunFolder "quality\official_division_evidence_gate.csv"

$Creation = Get-Content $CreationSummaryPath -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "TTE official division evidence intake v13.0.3" -ForegroundColor Cyan
Write-Host ("Run folder: {0}" -f $RunFolder)
Write-Host ("Creation status: {0}" -f $Creation.status)
Write-Host ("Source mapping keys: {0}" -f $Creation.source_mapping_keys)
Write-Host ("Source allocation rows: {0}" -f $Creation.source_allocation_rows)
Write-Host ("Evidence candidate rows: {0}" -f $Creation.evidence_candidate_rows)
Write-Host ("Priority unresolved keys: {0}" -f $Creation.priority_unresolved_keys)
Write-Host ("Estates: {0}" -f $Creation.estate_count)
Write-Host ("Review gate: {0}" -f $Creation.review_gate)
Write-Host ("Live deployment started: {0}" -f $Creation.live_deployment_started)

Write-Host ""
Write-Host "Evidence-pack gate:" -ForegroundColor Cyan
Import-Csv $CreationGatePath | Format-Table -AutoSize

if (Test-Path $ValidationSummaryPath) {
    $Validation = Get-Content $ValidationSummaryPath -Raw | ConvertFrom-Json

    Write-Host ""
    Write-Host "Latest official evidence validation:" -ForegroundColor Cyan
    Write-Host ("Verified valid mapping keys: {0}" -f $Validation.verified_valid_mapping_keys)
    Write-Host ("Evidence failures: {0}" -f $Validation.official_evidence_failures)
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
    Write-Host "Official source-document input has not yet been validated." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "This remains evidence collection and review only. It does not permit live employee allocation." -ForegroundColor Yellow
