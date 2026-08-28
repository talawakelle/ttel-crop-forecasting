param(
    [string]$StartDate = "2026-07-27",
    [string]$EndDate = "2031-07-26",
    [switch]$OpenResults
)

$ErrorActionPreference = "Stop"

$Start = [datetime]::ParseExact(
    $StartDate,
    "yyyy-MM-dd",
    [System.Globalization.CultureInfo]::InvariantCulture
)
$End = [datetime]::ParseExact(
    $EndDate,
    "yyyy-MM-dd",
    [System.Globalization.CultureInfo]::InvariantCulture
)

$Desktop = [Environment]::GetFolderPath("Desktop")
$MasterRoot = Join-Path $Desktop (
    "TTE_Forecasting_RL_Continuous_{0}_{1}" -f `
        $Start.ToString("yyyyMMdd"), `
        $End.ToString("yyyyMMdd")
)
$SummaryPath = Join-Path $MasterRoot "run_summary.json"
$BlockIndexPath = Join-Path $MasterRoot "master\master_block_index.csv"

if (-not (Test-Path $SummaryPath -PathType Leaf)) {
    throw "Continuous project summary not found: $SummaryPath"
}

$Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "TTE CONTINUOUS FORECASTING + PROTECTED HYBRID RL STATUS" -ForegroundColor Cyan
Write-Host ("Status: {0}" -f $Summary.status)
Write-Host ("Period: {0} to {1}" -f $Summary.start_date, $Summary.end_date)
Write-Host (
    "Blocks completed: {0} of {1}" -f `
        $Summary.completed_blocks, `
        $Summary.planned_blocks
)
Write-Host (
    "Dates completed: {0} of {1}" -f `
        $Summary.completed_days, `
        $Summary.planned_days
)
Write-Host ("Named employee rows: {0}" -f $Summary.employee_allocation_rows)
Write-Host ("RL model-invoked episodes: {0}" -f $Summary.rl_model_invoked_episodes)
Write-Host ("RL actions used: {0}" -f $Summary.rl_actions_used)
Write-Host ("Accepted moves: {0}" -f $Summary.accepted_move_count)
Write-Host ("Safety violations: {0}" -f $Summary.safety_violations)
Write-Host ("Duplicate failures: {0}" -f $Summary.duplicate_assignment_failures)
Write-Host ""
Write-Host "Forecasting: YES"
Write-Host "Plucker-demand calculation: YES"
Write-Host "Named employee allocation: YES"
Write-Host "Protected hybrid RL inference on CUDA: YES"
Write-Host "RL model retraining: NO"
Write-Host "Safety shield: YES"
Write-Host "Greedy fallback: YES"
Write-Host "Monthly Excel workbooks: YES"
Write-Host "Live operational authorization: NO"

if (Test-Path $BlockIndexPath -PathType Leaf) {
    $Next = Import-Csv $BlockIndexPath |
        Where-Object {
            $_.status -ne "PASS_PROTECTED_HYBRID_RL_MULTI_DAY_SHADOW_ALLOCATION"
        } |
        Select-Object -First 1

    if ($null -ne $Next) {
        Write-Host ""
        Write-Host (
            "Next incomplete block: {0} to {1}" -f `
                $Next.start_date, `
                $Next.end_date
        ) -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host ("Results folder: {0}" -f $MasterRoot)

if ($OpenResults) {
    $StartPage = Join-Path $MasterRoot "START_HERE.html"
    if (Test-Path $StartPage -PathType Leaf) {
        Invoke-Item $StartPage
    }
}
