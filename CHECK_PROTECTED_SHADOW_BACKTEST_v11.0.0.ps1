$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v11\protected_shadow_backtest_runs"
$Pointer = Join-Path $RunRoot "LATEST_PROTECTED_SHADOW_BACKTEST_RUN.txt"

if (-not (Test-Path $Pointer)) {
    Write-Host "No completed protected shadow backtest was found." -ForegroundColor Yellow
    exit 1
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$SummaryPath = Join-Path $RunFolder "run_summary.json"
$GatePath = Join-Path $RunFolder "quality\protected_shadow_backtest_gate.csv"
$ReviewPath = Join-Path $RunFolder "quality\routed_policy_review_cases.csv"
$UnseenReviewPath = Join-Path $RunFolder "quality\unseen_shock_review_cases.csv"
$PolicyRegister = Join-Path $RunFolder "policy\estate_scenario_shadow_policy_register.csv"

$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "TTE protected shadow backtest v11.0.0" -ForegroundColor Cyan
Write-Host ("Run folder: {0}" -f $RunFolder)
Write-Host ("Status: {0}" -f $Summary.status)
Write-Host ("Device used: {0}" -f $Summary.device_used)
Write-Host ("CUDA available: {0}" -f $Summary.cuda_available)
Write-Host ("Episodes: {0}" -f $Summary.episodes)
Write-Host ("Shock sets per episode: {0}" -f $Summary.shock_sets_per_episode)
Write-Host ("Routed episode-shock cases: {0}" -f $Summary.routed_episode_shock_cases)
Write-Host ("Greedy fallback episodes: {0}" -f $Summary.greedy_fallback_episode_count)
Write-Host ("Protected hybrid episodes: {0}" -f $Summary.protected_hybrid_episode_count)
Write-Host ("All-case routed noninferiority: {0}%" -f $Summary.all_case_routed_noninferiority_rate_pct)
Write-Host ("Required all-case rate: {0}%" -f $Summary.required_all_case_noninferiority_rate_pct)
Write-Host ("Training-shock replay noninferiority: {0}%" -f $Summary.training_shock_replay_noninferiority_rate_pct)
Write-Host ("Unseen SHOCK_05 routed noninferiority: {0}%" -f $Summary.unseen_shock_05_routed_noninferiority_rate_pct)
Write-Host ("Unseen SHOCK_05 review cases: {0}" -f $Summary.unseen_shock_05_review_cases)
Write-Host ("Routed safety violations: {0}" -f $Summary.routed_safety_violations)
Write-Host ("Routed duplicate assignment failures: {0}" -f $Summary.routed_duplicate_assignment_failures)
Write-Host ("No-shock baseline degradation failures: {0}" -f $Summary.no_shock_baseline_degradation_failures)
Write-Host ("Routed RL actions used: {0}" -f $Summary.routed_rl_actions_used)
Write-Host ("Routed hybrid greedy fallbacks: {0}" -f $Summary.routed_hybrid_greedy_fallbacks)
Write-Host ("Shadow gate: {0}" -f $Summary.shadow_gate)
Write-Host ("Supervisor review started: {0}" -f $Summary.supervisor_review_started)
Write-Host ("Live deployment started: {0}" -f $Summary.live_deployment_started)

Write-Host ""
Write-Host "Protected shadow gate:" -ForegroundColor Cyan
Import-Csv $GatePath | Format-Table -AutoSize

Write-Host ""
Write-Host "Episode-level shadow policy counts:" -ForegroundColor Cyan
Import-Csv $PolicyRegister |
    Group-Object routed_shadow_policy |
    Select-Object Name, Count |
    Sort-Object Name |
    Format-Table -AutoSize

Write-Host ""
Write-Host "All routed-policy review cases:" -ForegroundColor Cyan
$AllReview = Import-Csv $ReviewPath

if (@($AllReview).Count -eq 0) {
    Write-Host "None." -ForegroundColor Green
}
else {
    $AllReview |
        Select-Object shock_group, scenario, estate,
            shock_id, routed_shadow_policy,
            greedy_final_objective,
            routed_final_objective,
            routed_final_under_kg |
        Format-Table -AutoSize
}

Write-Host ""
Write-Host "Unseen SHOCK_05 review cases:" -ForegroundColor Cyan
$UnseenReview = Import-Csv $UnseenReviewPath

if (@($UnseenReview).Count -eq 0) {
    Write-Host "None." -ForegroundColor Green
}
else {
    $UnseenReview |
        Select-Object scenario, estate, shock_id,
            routed_shadow_policy,
            greedy_final_objective,
            routed_final_objective |
        Format-Table -AutoSize
}

Write-Host ""
Write-Host "This is simulated shadow backtesting only. It is not observed historical performance or live assignment." -ForegroundColor Yellow
