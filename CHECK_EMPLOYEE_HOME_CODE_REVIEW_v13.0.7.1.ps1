$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_7_1\employee_home_code_supervisor_review_runs"
$Pointer = Join-Path $RunRoot "LATEST_EMPLOYEE_HOME_CODE_REVIEW_V1307_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v13.0.7.1 employee home-code review run was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$Creation = Get-Content (Join-Path $RunFolder "run_summary.json") -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "TTE employee home-code supervisor review source repair v13.0.7.1" -ForegroundColor Cyan
Write-Host ("Run folder: {0}" -f $RunFolder)
Write-Host ("Creation status: {0}" -f $Creation.status)
Write-Host ("Source allocation: {0}" -f $Creation.source_allocation_path)
Write-Host ("Source assignment rows: {0}" -f $Creation.source_assignment_rows)
Write-Host ("Home-code context rows: {0}" -f $Creation.home_code_context_rows)
Write-Host ("Single-candidate contexts: {0}" -f $Creation.single_candidate_contexts)
Write-Host ("Multiple-candidate contexts: {0}" -f $Creation.multiple_candidate_contexts)
Write-Host ("No-direct-candidate contexts: {0}" -f $Creation.no_direct_candidate_contexts)
Write-Host ("Employee exception review rows: {0}" -f $Creation.employee_exception_review_rows)
Write-Host ("Review gate: {0}" -f $Creation.review_gate)
Write-Host ("Live deployment started: {0}" -f $Creation.live_deployment_started)

$ValidationPath = Join-Path $RunFolder "validation_summary.json"
if (Test-Path $ValidationPath) {
    $Validation = Get-Content $ValidationPath -Raw | ConvertFrom-Json
    Write-Host ""
    Write-Host "Latest validation:" -ForegroundColor Cyan
    Write-Host ("Review failures: {0}" -f $Validation.review_failures)
    Write-Host ("Review gate: {0}" -f $Validation.review_gate)
    Write-Host ("Live deployment started: {0}" -f $Validation.live_deployment_started)
}

Write-Host ""
Write-Host "This stage remains supervisor review only." -ForegroundColor Yellow
