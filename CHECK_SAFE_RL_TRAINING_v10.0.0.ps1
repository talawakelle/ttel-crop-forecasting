$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v10\safe_rl_training_runs"
$Pointer = Join-Path $OutputRoot "LATEST_SAFE_RL_TRAINING_RUN.txt"

if (-not (Test-Path $Pointer)) {
    Write-Host "No completed safe RL training run was found." -ForegroundColor Yellow
    exit 1
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$Summary = Get-Content (Join-Path $RunFolder "run_summary.json") -Raw | ConvertFrom-Json
$SafetyGate = Join-Path $RunFolder "quality\rl_training_safety_gate.csv"
$EstateGate = Join-Path $RunFolder "evaluation\estate_policy_gate.csv"
$Evaluation = Join-Path $RunFolder "evaluation\policy_vs_greedy_gate.csv"

Write-Host ""
Write-Host "TTE safe development RL training v10.0.0" -ForegroundColor Cyan
Write-Host ("Run folder: {0}" -f $RunFolder)
Write-Host ("Status: {0}" -f $Summary.status)
Write-Host ("Device used: {0}" -f $Summary.device_used)
Write-Host ("CUDA available: {0}" -f $Summary.cuda_available)
Write-Host ("Episodes: {0}" -f $Summary.episodes)
Write-Host ("Training episode-shocks: {0}" -f $Summary.training_episode_shocks)
Write-Host ("Validation episode-shocks: {0}" -f $Summary.validation_episode_shocks)
Write-Host ("Baseline safety episode-shocks: {0}" -f $Summary.baseline_safety_episode_shocks)
Write-Host ("Warmup examples: {0}" -f $Summary.warmup_examples)
Write-Host ("Training epochs: {0}" -f $Summary.training_epochs)
Write-Host ("Validation hybrid noninferiority rate: {0}%" -f $Summary.validation_hybrid_noninferiority_rate_pct)
Write-Host ("Required noninferiority rate: {0}%" -f $Summary.required_noninferiority_rate_pct)
Write-Host ("Training safety violations: {0}" -f $Summary.training_safety_violations)
Write-Host ("Validation safety violations: {0}" -f $Summary.validation_safety_violations)
Write-Host ("Validation duplicate assignment failures: {0}" -f $Summary.validation_duplicate_assignment_failures)
Write-Host ("Baseline degradation failures: {0}" -f $Summary.baseline_degradation_failures)
Write-Host ("Hybrid RL actions used: {0}" -f $Summary.hybrid_rl_actions_used)
Write-Host ("Hybrid greedy fallbacks: {0}" -f $Summary.hybrid_greedy_fallbacks)
Write-Host ("Hybrid RL usage rate: {0}%" -f $Summary.hybrid_rl_usage_rate_pct)
Write-Host ("Policy gate: {0}" -f $Summary.policy_gate)
Write-Host ("RL training completed: {0}" -f $Summary.rl_training_completed)
Write-Host ("Live deployment started: {0}" -f $Summary.live_deployment_started)

Write-Host ""
Write-Host "Training safety gate:" -ForegroundColor Cyan
Import-Csv $SafetyGate | Format-Table -AutoSize

Write-Host ""
Write-Host "Estate policy gate counts:" -ForegroundColor Cyan
Import-Csv $EstateGate |
    Group-Object scenario, estate_policy_gate |
    Sort-Object Name |
    Select-Object Name, Count |
    Format-Table -AutoSize

Write-Host ""
Write-Host "Validation cases requiring review:" -ForegroundColor Cyan
$Review = Import-Csv $EstateGate |
    Where-Object { $_.estate_policy_gate -ne "PASS" } |
    Sort-Object scenario, estate

if (@($Review).Count -eq 0) {
    Write-Host "None." -ForegroundColor Green
} else {
    $Review |
        Select-Object scenario, estate, shock_id,
            hybrid_noninferior, safety_violations,
            duplicate_assignments, hybrid_rl_actions_used,
            hybrid_greedy_fallbacks, estate_policy_gate |
        Format-Table -AutoSize
}

Write-Host ""
Write-Host "Model file:" -ForegroundColor Cyan
Write-Host $Summary.model_path
Write-Host ""
Write-Host "Evaluation file:" -ForegroundColor Cyan
Write-Host $Evaluation
Write-Host ""
Write-Host "This is development training only. A passing gate permits shadow backtesting, not live assignment." -ForegroundColor Yellow
