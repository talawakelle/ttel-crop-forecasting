$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v11_0_1\movement_audit_fallback_repair_runs"
$Pointer = Join-Path $RunRoot "LATEST_MOVEMENT_AUDIT_REPAIR_RUN.txt"

if (-not (Test-Path $Pointer)) {
    Write-Host "No completed movement audit repair run was found." -ForegroundColor Yellow
    exit 1
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$SummaryPath = Join-Path $RunFolder "run_summary.json"
$GatePath = Join-Path $RunFolder "quality\movement_audit_repair_gate.csv"
$PolicyReviewPath = Join-Path $RunFolder "quality\remaining_policy_review_cases.csv"
$MovementFailurePath = Join-Path $RunFolder "quality\movement_reconciliation_failures.csv"
$RoutePath = Join-Path $RunFolder "policy\repaired_shadow_route_register.csv"

$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "TTE movement audit and fallback repair v11.0.1" -ForegroundColor Cyan
Write-Host ("Run folder: {0}" -f $RunFolder)
Write-Host ("Status: {0}" -f $Summary.status)
Write-Host ("Device used: {0}" -f $Summary.device_used)
Write-Host ("CUDA available: {0}" -f $Summary.cuda_available)
Write-Host ("Episodes: {0}" -f $Summary.episodes)
Write-Host ("Routed cases: {0}" -f $Summary.routed_episode_shock_cases)
Write-Host ("Episode fallback rules: {0}" -f $Summary.episode_level_greedy_fallback_rules)
Write-Host ("Exact replay fallback rules: {0}" -f $Summary.exact_replay_case_greedy_fallback_rules)
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
Write-Host "Movement audit and repair gate:" -ForegroundColor Cyan
Import-Csv $GatePath | Format-Table -AutoSize

Write-Host ""
Write-Host "Repaired route counts:" -ForegroundColor Cyan
Import-Csv $RoutePath |
    Group-Object routed_shadow_policy |
    Select-Object Name, Count |
    Sort-Object Name |
    Format-Table -AutoSize

Write-Host ""
Write-Host "Remaining policy review cases:" -ForegroundColor Cyan
$PolicyReview = Import-Csv $PolicyReviewPath

if (@($PolicyReview).Count -eq 0) {
    Write-Host "None." -ForegroundColor Green
}
else {
    $PolicyReview |
        Select-Object shock_group, scenario, estate,
            shock_id, routed_shadow_policy,
            greedy_final_objective,
            routed_final_objective,
            routed_accepted_moves |
        Format-Table -AutoSize
}

Write-Host ""
Write-Host "Movement reconciliation failures:" -ForegroundColor Cyan
$MovementFailures = Import-Csv $MovementFailurePath

if (@($MovementFailures).Count -eq 0) {
    Write-Host "None." -ForegroundColor Green
}
else {
    $MovementFailures |
        Select-Object scenario, estate, shock_id,
            policy, accepted_move_count,
            state_move_field,
            state_reported_move_count,
            history_move_field,
            history_reported_move_count |
        Format-Table -AutoSize
}

Write-Host ""
Write-Host "This remains simulation-only. Passing permits supervisor shadow review, not live assignment." -ForegroundColor Yellow
