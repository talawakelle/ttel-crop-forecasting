$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_6\rare_cross_division_exception_runs"
$Pointer = Join-Path $RunRoot "LATEST_RARE_CROSS_DIVISION_EXCEPTION_V1306_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v13.0.6 rare exception run was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$Creation = Get-Content (Join-Path $RunFolder "run_summary.json") -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "TTE rare cross-division exception review v13.0.6" -ForegroundColor Cyan
Write-Host ("Run folder: {0}" -f $RunFolder)
Write-Host ("Creation status: {0}" -f $Creation.status)
Write-Host ("Employee daily groups: {0}" -f $Creation.employee_daily_groups)
Write-Host ("Standard same-division groups: {0}" -f $Creation.standard_same_division_groups)
Write-Host ("Rare exception groups: {0}" -f $Creation.rare_cross_division_exception_groups)
Write-Host ("Current exception rate: {0}%" -f $Creation.current_exception_rate_pct)
Write-Host ("Exact duplicate failures: {0}" -f $Creation.exact_duplicate_assignment_failures)
Write-Host ("Review gate: {0}" -f $Creation.review_gate)
Write-Host ("Live deployment started: {0}" -f $Creation.live_deployment_started)

$ValidationPath = Join-Path $RunFolder "validation_summary.json"
if (Test-Path $ValidationPath) {
    $Validation = Get-Content $ValidationPath -Raw | ConvertFrom-Json
    Write-Host ""
    Write-Host "Latest validation:" -ForegroundColor Cyan
    Write-Host ("Validation failures: {0}" -f $Validation.validation_failures)
    Write-Host ("Rare exception groups: {0}" -f $Validation.rare_cross_division_exception_groups)
    Write-Host ("Exception rate: {0}%" -f $Validation.exception_rate_pct)
    Write-Host ("Review gate: {0}" -f $Validation.review_gate)
    Write-Host ("Live deployment started: {0}" -f $Validation.live_deployment_started)
}

Write-Host ""
Write-Host "This remains review-only and does not authorize live employee allocation." -ForegroundColor Yellow
