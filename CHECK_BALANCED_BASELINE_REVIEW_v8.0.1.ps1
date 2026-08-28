$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v8\balanced_baseline_review_runs"
$Pointer = Join-Path $OutputRoot "LATEST_BALANCED_BASELINE_REVIEW.txt"

if (-not (Test-Path $Pointer)) {
    Write-Host "No balanced baseline review was found." -ForegroundColor Yellow
    exit 1
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$Summary = Get-Content (Join-Path $RunFolder "run_summary.json") -Raw | ConvertFrom-Json
$ReviewPath = Join-Path $RunFolder "quality\balanced_cp_sat_vs_greedy_review.csv"
$ScenarioPath = Join-Path $RunFolder "quality\scenario_baseline_gate.csv"

Write-Host ""
Write-Host "TTE balanced baseline review v8.0.1" -ForegroundColor Cyan
Write-Host ("Run folder: {0}" -f $RunFolder)
Write-Host ("Status: {0}" -f $Summary.status)
Write-Host ("Estate-scenario rows: {0}" -f $Summary.estate_scenario_rows)
Write-Host ("Legacy strict noninferiority rate: {0}%" -f $Summary.legacy_strict_noninferiority_rate_pct)
Write-Host ("Material noninferiority rate: {0}%" -f $Summary.material_noninferiority_rate_pct)
Write-Host ("CP-SAT service-safe rate: {0}%" -f $Summary.cp_sat_service_safe_rate_pct)
Write-Host ("Required gate: {0}%" -f $Summary.minimum_gate_pct)
Write-Host ("Material tolerance: max({0} kg, {1}% of crop)" -f $Summary.absolute_tolerance_kg, $Summary.relative_tolerance_pct)
Write-Host ("Maximum shortfall rate: {0}%" -f $Summary.maximum_shortfall_rate_pct)
Write-Host ("RL environment gate: {0}" -f $Summary.rl_environment_gate)
Write-Host ("RL started: {0}" -f $Summary.rl_started)

Write-Host ""
Write-Host "Scenario gates:" -ForegroundColor Cyan
Import-Csv $ScenarioPath |
    Format-Table scenario, estate_scenarios,
        material_noninferiority_rate_pct,
        cp_sat_service_safe_rate_pct,
        portfolio_effective_coverage_pct,
        uncovered_fields, fields_coverage_95_plus,
        field_rows, scenario_gate -AutoSize

Write-Host ""
Write-Host "Baseline preference counts:" -ForegroundColor Cyan
Import-Csv $ReviewPath |
    Group-Object preferred_baseline |
    Sort-Object Name |
    Select-Object Name, Count |
    Format-Table -AutoSize

Write-Host ""
Write-Host "Material gate failures:" -ForegroundColor Cyan
$Failures = Import-Csv $ReviewPath |
    Where-Object {
        $_.material_noninferior -eq "NO" -or
        $_.cp_sat_service_safe -eq "NO"
    } |
    Sort-Object scenario, estate

if (@($Failures).Count -eq 0) {
    Write-Host "None." -ForegroundColor Green
} else {
    $Failures |
        Select-Object scenario, estate, total_target_crop_kg,
            cp_sat_under_kg, greedy_under_kg,
            material_tolerance_kg,
            cp_sat_under_rate_pct,
            material_noninferior,
            cp_sat_service_safe,
            preferred_baseline,
            decision_reason |
        Format-Table -AutoSize
}

Write-Host ""
Write-Host "Review file:" -ForegroundColor Cyan
Write-Host $ReviewPath
Write-Host ""
Write-Host "Passing this gate permits RL environment design only. RL training has not started." -ForegroundColor Yellow
