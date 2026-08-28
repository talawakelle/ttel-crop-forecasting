param(
    [string]$ProjectRoot = "C:\TTE_Integrated_Platform\ttel_crop_forecasting",
    [string]$StartDate = "2026-07-27",
    [string]$EndDate = "2026-10-24",
    [double]$CpSatTimeLimitSeconds = 45,
    [int]$CpSatWorkers = 0,
    [switch]$SkipExcel
)

$ErrorActionPreference = "Stop"

function Ensure-DailyCandidateGate {
    param([string]$V4Run)

    $selectedModels = Join-Path $V4Run "backtest\estate_selected_models.csv"
    $gateFile = Join-Path $V4Run "backtest\daily_candidate_gate.csv"

    if (Test-Path $gateFile) { return $gateFile }
    if (-not (Test-Path $selectedModels)) {
        throw "Selected model file not found: $selectedModels"
    }

    $gateRows = foreach ($row in Import-Csv $selectedModels) {
        $wape = [double]$row.selected_wape_pct
        $gate = "REJECTED_DAILY_BASELINE"
        if ($wape -le 30) { $gate = "PROVISIONAL_DAILY_CANDIDATE" }
        if ($wape -le 25) { $gate = "ACCEPTED_WITH_REVIEW" }
        if ($wape -le 20) { $gate = "ACCEPTED_DEVELOPMENT_CANDIDATE" }
        if ($row.estate -in @("Tillicoultry", "EildonHall", "bambarakelly")) {
            if ($gate -ne "REJECTED_DAILY_BASELINE") { $gate = "PROVISIONAL_SHORT_HISTORY" }
        }
        [PSCustomObject]@{
            estate = $row.estate
            selected_method = $row.selected_method
            test_observed_days = [int]$row.test_observed_days
            mae_kg = [double]$row.selected_mae_kg
            rmse_kg = [double]$row.selected_rmse_kg
            wape_pct = $wape
            development_gate = $gate
            live_status = "BLOCKED_STALE_SOURCE_DATA"
        }
    }

    $gateRows | Sort-Object wape_pct | Export-Csv $gateFile -NoTypeInformation -Encoding UTF8
    Write-Host "Created missing daily candidate gate." -ForegroundColor Green
    return $gateFile
}

function Test-PassingDailyResult {
    param([string]$Folder)

    $summaryPath = Join-Path $Folder "run_summary.json"
    if (-not (Test-Path $summaryPath)) { return $false }
    try {
        $summary = Get-Content $summaryPath -Raw | ConvertFrom-Json
        return $summary.status -eq "PASS_PROTECTED_HYBRID_RL_DAILY_SHADOW_ALLOCATION"
    }
    catch {
        return $false
    }
}

Write-Host ""
Write-Host "TTE PROTECTED HYBRID RL 90-DAY SHADOW ALLOCATION v15.0.0" -ForegroundColor Cyan
Write-Host "Forecast and allocation period: $StartDate to $EndDate"
Write-Host "This is resumable. Passing dates are skipped when rerun."
Write-Host ""

$Start = [datetime]::ParseExact($StartDate, "yyyy-MM-dd", [System.Globalization.CultureInfo]::InvariantCulture)
$End = [datetime]::ParseExact($EndDate, "yyyy-MM-dd", [System.Globalization.CultureInfo]::InvariantCulture)
if ($End -lt $Start) { throw "EndDate must not be earlier than StartDate." }
$TotalDays = ($End - $Start).Days + 1

if ($TotalDays -ne 90) {
    Write-Host "Requested period contains $TotalDays days. Default validated period contains 90 days." -ForegroundColor Yellow
}

if (-not (Test-Path $ProjectRoot -PathType Container)) {
    throw "Project folder not found: $ProjectRoot"
}

$DayRunner = Join-Path $ProjectRoot "RUN_TTE_PROTECTED_HYBRID_RL_ONE_DAY_v15.0.0.ps1"
$Consolidator = Join-Path $ProjectRoot "workforce_planner\v15_0_0\batch\build_90_day_outputs_v1500.py"
foreach ($required in @($DayRunner, $Consolidator)) {
    if (-not (Test-Path $required -PathType Leaf)) {
        throw "Required v15 file not found: $required"
    }
}

& py -3.12 -c "import torch, ortools"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.12 requires PyTorch and OR-Tools."
}

if (-not $SkipExcel) {
    & py -3.12 -c "import openpyxl"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing openpyxl for monthly Excel workbooks..." -ForegroundColor Yellow
        & py -3.12 -m pip install openpyxl
        if ($LASTEXITCODE -ne 0) {
            throw "openpyxl installation failed. Rerun with -SkipExcel to create CSV results only."
        }
    }
}

$V4Pointer = Join-Path $ProjectRoot "workforce_planner\v4\daily_hierarchy_runs\LATEST_DAILY_HIERARCHY_RUN.txt"
if (-not (Test-Path $V4Pointer)) { throw "Latest v4 pointer not found: $V4Pointer" }
$V4Run = (Get-Content $V4Pointer -Raw).Trim()
$V4SummaryPath = Join-Path $V4Run "run_summary.json"
if (-not (Test-Path $V4SummaryPath)) { throw "v4 run summary not found: $V4SummaryPath" }
$V4Summary = Get-Content $V4SummaryPath -Raw | ConvertFrom-Json
$V4Start = [datetime]::Parse($V4Summary.forecast_start)
$V4End = $V4Start.AddDays([int]$V4Summary.forecast_days - 1)

if ($Start -lt $V4Start -or $End -gt $V4End) {
    throw (("Latest v4 forecast covers {0} to {1}. It does not cover the requested period {2} to {3}." -f `
        $V4Start.ToString("yyyy-MM-dd"), $V4End.ToString("yyyy-MM-dd"), $StartDate, $EndDate))
}

Write-Host "Using v4 forecast run:" -ForegroundColor Cyan
Write-Host $V4Run
$null = Ensure-DailyCandidateGate -V4Run $V4Run

$V5Launcher = Join-Path $ProjectRoot "START_FINAL_METHOD_GATE_PLANNING_v5.0.3.ps1"
if (-not (Test-Path $V5Launcher)) { throw "v5 launcher not found: $V5Launcher" }

Write-Host ""
Write-Host "Preparing the 90-day field and plucker-demand planning run once..." -ForegroundColor Cyan
& $V5Launcher

$V5Pointer = Join-Path $ProjectRoot "workforce_planner\v5\final_method_gate_runs_v503\LATEST_BEST_AVAILABLE_PLANNING_RUN.txt"
if (-not (Test-Path $V5Pointer)) { throw "Final planning pointer not found: $V5Pointer" }
$PlanningRun = (Get-Content $V5Pointer -Raw).Trim()
$PlanningSummaryPath = Join-Path $PlanningRun "run_summary.json"
if (-not (Test-Path $PlanningSummaryPath)) { throw "Planning summary not found: $PlanningSummaryPath" }
$PlanningSummary = Get-Content $PlanningSummaryPath -Raw | ConvertFrom-Json
if ($PlanningSummary.status -ne "PASS_DEVELOPMENT_OUTPUTS") {
    throw "Final field and plucker-demand planning did not pass."
}

$Desktop = [Environment]::GetFolderPath("Desktop")
$OutputRoot = Join-Path $Desktop ("TTE_Protected_Hybrid_RL_{0}_{1}" -f $Start.ToString("yyyyMMdd"), $End.ToString("yyyyMMdd"))
$DaysRoot = Join-Path $OutputRoot "days"
$LogsRoot = Join-Path $OutputRoot "logs"
New-Item -ItemType Directory -Force -Path $DaysRoot, $LogsRoot | Out-Null

$TranscriptPath = Join-Path $LogsRoot ("batch_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
Start-Transcript -Path $TranscriptPath | Out-Null

try {
    $Completed = 0
    $Reused = 0
    $Built = 0

    for ($offset = 0; $offset -lt $TotalDays; $offset++) {
        $Date = $Start.AddDays($offset)
        $DateText = $Date.ToString("yyyy-MM-dd")
        $DateKey = $Date.ToString("yyyyMMdd")
        $DayOutput = Join-Path $DaysRoot $DateKey

        Write-Host ""
        Write-Host ("============================================================") -ForegroundColor DarkCyan
        Write-Host ("DATE {0} OF {1}: {2}" -f ($offset + 1), $TotalDays, $DateText) -ForegroundColor Cyan
        Write-Host ("============================================================") -ForegroundColor DarkCyan

        if (Test-PassingDailyResult -Folder $DayOutput) {
            Write-Host "Passing batch result already exists. Skipping." -ForegroundColor Green
            $Completed++
            continue
        }

        $LegacyOutput = Join-Path $Desktop ("TTE_Protected_Hybrid_RL_{0}" -f $DateKey)
        if (Test-PassingDailyResult -Folder $LegacyOutput) {
            if (Test-Path $DayOutput) { Remove-Item $DayOutput -Recurse -Force }
            Copy-Item -Path $LegacyOutput -Destination $DayOutput -Recurse -Force
            Write-Host "Reused the existing passing one-day result." -ForegroundColor Green
            $Reused++
            $Completed++
            continue
        }

        & $DayRunner `
            -ProjectRoot $ProjectRoot `
            -AllocationDate $DateText `
            -PlanningRunOverride $PlanningRun `
            -OutputFolder $DayOutput `
            -CpSatTimeLimitSeconds $CpSatTimeLimitSeconds `
            -CpSatWorkers $CpSatWorkers `
            -NoOpen

        if (-not (Test-PassingDailyResult -Folder $DayOutput)) {
            throw "Protected hybrid RL daily gate did not pass for $DateText."
        }

        $Built++
        $Completed++

        [PSCustomObject]@{
            status = "IN_PROGRESS"
            package_version = "15.0.0"
            start_date = $StartDate
            end_date = $EndDate
            total_days = $TotalDays
            completed_days = $Completed
            last_completed_date = $DateText
            reused_existing_days = $Reused
            newly_built_days = $Built
            protected_hybrid_rl_shadow_only = $true
            operational_use_allowed = $false
            live_assignment_authorized = $false
        } | ConvertTo-Json -Depth 4 | Set-Content -Path (Join-Path $OutputRoot "batch_progress.json") -Encoding UTF8
    }

    Write-Host ""
    Write-Host "All daily protected hybrid RL runs passed. Building combined CSV and Excel results..." -ForegroundColor Cyan

    $ConsolidatorArgs = @(
        $Consolidator,
        "--days-root", $DaysRoot,
        "--output-root", $OutputRoot,
        "--start-date", $StartDate,
        "--end-date", $EndDate,
        "--expected-days", $TotalDays
    )
    if ($SkipExcel) { $ConsolidatorArgs += "--skip-excel" }

    & py -3.12 @ConsolidatorArgs
    if ($LASTEXITCODE -ne 0) {
        throw "90-day output consolidation failed."
    }

    $BatchSummaryPath = Join-Path $OutputRoot "run_summary.json"
    if (-not (Test-Path $BatchSummaryPath)) { throw "90-day run summary was not created." }
    $BatchSummary = Get-Content $BatchSummaryPath -Raw | ConvertFrom-Json
    if ($BatchSummary.status -ne "PASS_PROTECTED_HYBRID_RL_MULTI_DAY_SHADOW_ALLOCATION") {
        throw "90-day protected hybrid RL gate requires review."
    }

    Write-Host ""
    Write-Host "TTE 90-DAY PROTECTED HYBRID RL RESULTS CREATED" -ForegroundColor Green
    Write-Host ("Output folder: {0}" -f $OutputRoot)
    Write-Host ("Dates passed: {0} of {1}" -f $BatchSummary.completed_days, $BatchSummary.expected_days)
    Write-Host ("Named employee rows: {0}" -f $BatchSummary.employee_allocation_rows)
    Write-Host ("RL model-invoked episodes: {0}" -f $BatchSummary.rl_model_invoked_episodes)
    Write-Host ("Safety violations: {0}" -f $BatchSummary.safety_violations)
    Write-Host "Operational use allowed: NO"
    Write-Host "Live assignment authorized: NO"

    $StartPage = Join-Path $OutputRoot "START_HERE.html"
    if (Test-Path $StartPage) { Invoke-Item $StartPage }
}
finally {
    try { Stop-Transcript | Out-Null } catch { }
}
