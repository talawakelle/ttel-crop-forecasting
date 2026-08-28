$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v8\greedy_comparison_runs"
$Pointer = Join-Path $OutputRoot "LATEST_GREEDY_COMPARISON_RUN.txt"

if (-not (Test-Path $Pointer)) {
    Write-Host "No completed greedy comparison run was found." -ForegroundColor Yellow
    exit 1
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$Summary = Get-Content (Join-Path $RunFolder "run_summary.json") -Raw | ConvertFrom-Json
$Comparison = Join-Path $RunFolder "quality\cp_sat_vs_greedy_comparison.csv"
$MethodResults = Join-Path $RunFolder "quality\method_estate_results.csv"

Write-Host ""
Write-Host "TTE CP-SAT versus greedy comparison v8.0.0" -ForegroundColor Cyan
Write-Host ("Run folder: {0}" -f $RunFolder)
Write-Host ("Status: {0}" -f $Summary.status)
Write-Host ("Planning date: {0}" -f $Summary.planning_date)
Write-Host ("Comparison rows expected: {0}" -f $Summary.comparison_rows_expected)
Write-Host ("Comparison rows actual: {0}" -f $Summary.comparison_rows_actual)
Write-Host ("Greedy assignment rows: {0}" -f $Summary.greedy_assignment_rows)
Write-Host ("Greedy field rows expected: {0}" -f $Summary.greedy_field_rows_expected)
Write-Host ("Greedy field rows actual: {0}" -f $Summary.greedy_field_rows_actual)
Write-Host ("Greedy field identity failures: {0}" -f $Summary.greedy_field_identity_failures)
Write-Host ("Greedy duplicate employee failures: {0}" -f $Summary.greedy_duplicate_employee_assignment_failures)
Write-Host ("Greedy expected uncovered fields: {0}" -f $Summary.greedy_expected_uncovered_fields)
Write-Host ("CP-SAT noninferior estate-scenarios: {0}" -f $Summary.cp_sat_noninferior_estate_scenarios)
Write-Host ("CP-SAT noninferiority rate: {0}%" -f $Summary.cp_sat_noninferiority_rate_pct)
Write-Host ("Required gate: {0}%" -f $Summary.minimum_noninferiority_gate_pct)
Write-Host ("RL baseline gate: {0}" -f $Summary.rl_baseline_gate)
Write-Host ("RL started: {0}" -f $Summary.rl_started)

Write-Host ""
Write-Host "Winner counts:" -ForegroundColor Cyan
Import-Csv $Comparison |
    Group-Object scenario, winner |
    Sort-Object Name |
    Select-Object Name, Count |
    Format-Table -AutoSize

Write-Host ""
Write-Host "Estate-scenarios where CP-SAT was not noninferior:" -ForegroundColor Cyan
$Review = Import-Csv $Comparison |
    Where-Object {
        $_.cp_sat_noninferior_on_under_crop -eq "NO"
    } |
    Sort-Object scenario, estate

if (@($Review).Count -eq 0) {
    Write-Host "None." -ForegroundColor Green
} else {
    $Review |
        Select-Object scenario, estate,
            cp_sat_under_kg, greedy_under_kg,
            cp_sat_over_kg, greedy_over_kg,
            cp_sat_employees, greedy_employees,
            winner, winner_reason |
        Format-Table -AutoSize
}

Write-Host ""
Write-Host "Comparison file:" -ForegroundColor Cyan
Write-Host $Comparison
Write-Host ""
Write-Host "This remains development simulation only. RL has not started." -ForegroundColor Yellow
