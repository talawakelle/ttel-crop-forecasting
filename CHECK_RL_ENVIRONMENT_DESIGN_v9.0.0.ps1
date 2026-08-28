$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v9\rl_environment_runs"
$Pointer = Join-Path $OutputRoot "LATEST_RL_ENVIRONMENT_DESIGN_RUN.txt"
if (-not (Test-Path $Pointer)) { Write-Host "No completed RL environment design run was found." -ForegroundColor Yellow; exit 1 }
$RunFolder = (Get-Content $Pointer -Raw).Trim()
$Summary = Get-Content (Join-Path $RunFolder "run_summary.json") -Raw | ConvertFrom-Json
$SafetyGate = Join-Path $RunFolder "quality\rl_environment_safety_gate.csv"
$SmokeTest = Join-Path $RunFolder "quality\environment_smoke_test.csv"
Write-Host ""
Write-Host "TTE safe RL environment design v9.0.0" -ForegroundColor Cyan
Write-Host ("Run folder: {0}" -f $RunFolder)
Write-Host ("Status: {0}" -f $Summary.status)
Write-Host ("Episodes: {0}" -f $Summary.episodes)
Write-Host ("Baseline field rows: {0}" -f $Summary.baseline_field_rows)
Write-Host ("Baseline assignment rows: {0}" -f $Summary.baseline_assignment_rows)
Write-Host ("Shock sets per episode: {0}" -f $Summary.shock_sets_per_episode)
Write-Host ("Shock field rows: {0}" -f $Summary.shock_field_rows)
Write-Host ("Duplicate assignment failures: {0}" -f $Summary.duplicate_employee_assignment_failures)
Write-Host ("Smoke-test rows: {0}" -f $Summary.smoke_test_rows)
Write-Host ("Smoke-test failures: {0}" -f $Summary.smoke_test_failures)
Write-Host ("Safety-gate failures: {0}" -f $Summary.safety_gate_failures)
Write-Host ("Environment ready for training code: {0}" -f $Summary.environment_ready_for_training_code)
Write-Host ("Operational status: {0}" -f $Summary.operational_status)
Write-Host ("RL started: {0}" -f $Summary.rl_started)
Write-Host ""
Write-Host "Safety gate:" -ForegroundColor Cyan
Import-Csv $SafetyGate | Format-Table -AutoSize
Write-Host ""
Write-Host "Environment smoke test:" -ForegroundColor Cyan
Import-Csv $SmokeTest | Format-Table -AutoSize
Write-Host ""
Write-Host "Environment manifest:" -ForegroundColor Cyan
Write-Host (Join-Path $RunFolder "rl_environment_manifest.json")
Write-Host ""
Write-Host "This stage designs and validates the environment only. RL training has not started." -ForegroundColor Yellow
