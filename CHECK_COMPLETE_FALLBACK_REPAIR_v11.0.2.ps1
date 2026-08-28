$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v11_0_2\complete_fallback_routing_repair_runs"
$Pointer = Join-Path $RunRoot "LATEST_MOVEMENT_AUDIT_REPAIR_RUN.txt"

if (-not (Test-Path $Pointer)) {
    Write-Host "No completed v11.0.2 repair run was found." -ForegroundColor Yellow
    exit 1
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$SummaryPath = Join-Path $RunFolder "run_summary.json"
$GatePath = Join-Path $RunFolder "quality\movement_audit_repair_gate.csv"
$ReviewPath = Join-Path $RunFolder "quality\remaining_policy_review_cases.csv"
$MoveFailurePath = Join-Path $RunFolder "quality\movement_reconciliation_failures.csv"
$RoutePath = Join-Path $RunFolder "policy\repaired_shadow_route_register.csv"

$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "TTE complete fallback routing repair v11.0.2" -ForegroundColor Cyan
Write-Host ("Run folder: {0}" -f $RunFolder)
Write-Host ("Status: {0}" -f $Summary.status)
Write-Host ("Device used: {0}" -f $Summary.device_used)
Write-Host ("CUDA available: {0}" -f $Summary.cuda_available)
Write-Host ("Episodes: {0}" -f $Summary.episodes)
Write-Host ("Routed cases: {0}" -f $Summary.routed_episode_shock_cases)
Write-Host ("Episode fallback rules: {0}" -f $Summary.episode_level_greedy_fallback_rules)
Write-Host ("Prior exact fallback rules: {0}" -f $Summary.prior_exact_fallback_rules)
Write-Host ("Additional exact fallback rules: {0}" -f $Summary.additional_exact_fallback_rules)
Write-Host ("Total exact fallback rules: {0}" -f $Summary.total_exact_fallback_rules)
Write-Host ("All-case noninferiority: {0}%" -f $Summary.all_case_routed_noninferiority_rate_pct)
Write-Host ("Required all-case rate: {0}%" -f $Summary.required_all_case_rate_pct)
Write-Host ("Unseen SHOCK_05 noninferiority: {0}%" -f $Summary.unseen_shock_05_noninferiority_rate_pct)
Write-Host ("Remaining policy review cases: {0}" -f $Summary.remaining_policy_review_cases)
Write-Host ("Accepted routed movements: {0}" -f $Summary.accepted_routed_movements)
Write-Host ("Rejected routed movements: {0}" -f $Summary.rejected_routed_movements)
Write-Host ("Movement reconciliation failures: {0}" -f $Summary.movement_reconciliation_failures)
Write-Host ("Safety violations: {0}" -f $Summary.routed_safety_violations)
Write-Host ("Duplicate assignment failures: {0}" -f $Summary.routed_duplicate_assignment_failures)
Write-Host ("No-shock baseline degradation failures: {0}" -f $Summary.no_shock_baseline_degradation_failures)
Write-Host ("Repair gate: {0}" -f $Summary.repair_gate)
Write-Host ("Supervisor review started: {0}" -f $Summary.supervisor_review_started)
Write-Host ("Live deployment started: {0}" -f $Summary.live_deployment_started)

Write-Host ""
Write-Host "Complete fallback repair gate:" -ForegroundColor Cyan
Import-Csv $GatePath | Format-Table -AutoSize

Write-Host ""
Write-Host "Final route counts:" -ForegroundColor Cyan
Import-Csv $RoutePath |
    Group-Object routed_shadow_policy |
    Select-Object Name, Count |
    Sort-Object Name |
    Format-Table -AutoSize

Write-Host ""
Write-Host "Remaining policy review cases:" -ForegroundColor Cyan
$Review = Import-Csv $ReviewPath
if (@($Review).Count -eq 0) {
    Write-Host "None." -ForegroundColor Green
}
else {
    $Review |
        Select-Object shock_group, scenario, estate,
            shock_id, routed_shadow_policy,
            greedy_final_objective,
            routed_final_objective,
            routed_accepted_moves |
        Format-Table -AutoSize
}

Write-Host ""
Write-Host "Movement reconciliation failures:" -ForegroundColor Cyan
$MoveFailures = Import-Csv $MoveFailurePath
if (@($MoveFailures).Count -eq 0) {
    Write-Host "None." -ForegroundColor Green
}
else {
    $MoveFailures | Format-Table -AutoSize
}

Write-Host ""
Write-Host "This remains simulation-only. Passing permits supervisor shadow review, not live assignment." -ForegroundColor Yellow
