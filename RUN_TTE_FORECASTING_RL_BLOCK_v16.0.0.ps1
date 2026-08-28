param(
    [string]$ProjectRoot = "C:\TTE_Integrated_Platform\ttel_crop_forecasting",
    [string]$CropRoot = "C:\Users\user\Desktop\HG 2",
    [string]$StartDate = "2026-07-27",
    [string]$EndDate = "2026-10-24",
    [string]$OutputFolder = "",
    [double]$CpSatTimeLimitSeconds = 45,
    [int]$CpSatWorkers = 0,
    [switch]$ForceForecastRebuild,
    [switch]$SkipExcel,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"

function Ensure-DailyCandidateGate {
    param([string]$V4Run)

    $selectedModels = Join-Path $V4Run "backtest\estate_selected_models.csv"
    $gateFile = Join-Path $V4Run "backtest\daily_candidate_gate.csv"

    if (Test-Path $gateFile -PathType Leaf) {
        return $gateFile
    }
    if (-not (Test-Path $selectedModels -PathType Leaf)) {
        throw "Selected model file not found: $selectedModels"
    }

    $gateRows = foreach ($row in Import-Csv $selectedModels) {
        $wape = [double]$row.selected_wape_pct
        $gate = "REJECTED_DAILY_BASELINE"
        if ($wape -le 30) { $gate = "PROVISIONAL_DAILY_CANDIDATE" }
        if ($wape -le 25) { $gate = "ACCEPTED_WITH_REVIEW" }
        if ($wape -le 20) { $gate = "ACCEPTED_DEVELOPMENT_CANDIDATE" }

        if ($row.estate -in @("Tillicoultry", "EildonHall", "bambarakelly")) {
            if ($gate -ne "REJECTED_DAILY_BASELINE") {
                $gate = "PROVISIONAL_SHORT_HISTORY"
            }
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

    $gateRows |
        Sort-Object wape_pct |
        Export-Csv $gateFile -NoTypeInformation -Encoding UTF8

    Write-Host "Created missing daily candidate gate: $gateFile" -ForegroundColor Green
    return $gateFile
}

function Test-PassingDailyResult {
    param([string]$Folder)

    $summaryPath = Join-Path $Folder "run_summary.json"
    if (-not (Test-Path $summaryPath -PathType Leaf)) {
        return $false
    }

    try {
        $summary = Get-Content $summaryPath -Raw | ConvertFrom-Json
        return $summary.status -eq "PASS_PROTECTED_HYBRID_RL_DAILY_SHADOW_ALLOCATION"
    }
    catch {
        return $false
    }
}

function Get-PassingV4Coverage {
    param(
        [string]$PointerPath,
        [datetime]$RequestedStart,
        [datetime]$RequestedEnd
    )

    if (-not (Test-Path $PointerPath -PathType Leaf)) {
        return $null
    }

    try {
        $run = (Get-Content $PointerPath -Raw).Trim()
        $summaryPath = Join-Path $run "run_summary.json"
        if (-not (Test-Path $summaryPath -PathType Leaf)) {
            return $null
        }

        $summary = Get-Content $summaryPath -Raw | ConvertFrom-Json
        $start = [datetime]::Parse($summary.forecast_start)
        $end = $start.AddDays([int]$summary.forecast_days - 1)

        if (
            $summary.status -eq "PASS_CANDIDATE" -and
            $RequestedStart -ge $start -and
            $RequestedEnd -le $end
        ) {
            return [PSCustomObject]@{
                run = $run
                summary = $summary
                start = $start
                end = $end
            }
        }
    }
    catch {
        return $null
    }

    return $null
}

Write-Host ""
Write-Host "TTE FORECASTING + PROTECTED HYBRID RL BLOCK v16.0.0" -ForegroundColor Cyan
Write-Host "Forecast and allocation block: $StartDate to $EndDate"
Write-Host "Passing daily dates are skipped when this script is rerun."
Write-Host ""

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
if ($End -lt $Start) {
    throw "EndDate must not be earlier than StartDate."
}

$TotalDays = ($End - $Start).Days + 1
if ($TotalDays -lt 7 -or $TotalDays -gt 90) {
    throw "Each block must contain between 7 and 90 consecutive dates. Requested range contains $TotalDays dates."
}

if (-not (Test-Path $ProjectRoot -PathType Container)) {
    throw "Project folder not found: $ProjectRoot"
}
if (-not (Test-Path $CropRoot -PathType Container)) {
    throw "Crop archive folder not found: $CropRoot"
}

$V4Launcher = Join-Path $ProjectRoot "START_DAILY_HIERARCHY_CANDIDATE_v4.0.0.ps1"
$V4Pointer = Join-Path $ProjectRoot "workforce_planner\v4\daily_hierarchy_runs\LATEST_DAILY_HIERARCHY_RUN.txt"
$V5Launcher = Join-Path $ProjectRoot "START_FINAL_METHOD_GATE_PLANNING_v5.0.3.ps1"
$DayRunner = Join-Path $ProjectRoot "RUN_TTE_PROTECTED_HYBRID_RL_ONE_DAY_v15.0.0.ps1"
$Consolidator = Join-Path $ProjectRoot "workforce_planner\v16_0_0\batch\build_block_outputs_v1600.py"

foreach ($required in @($V4Launcher, $V5Launcher, $DayRunner, $Consolidator)) {
    if (-not (Test-Path $required -PathType Leaf)) {
        throw "Required project file not found: $required"
    }
}

& py -3.12 -c "import torch; from ortools.sat.python import cp_model"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.12 requires both PyTorch and OR-Tools."
}

if (-not $SkipExcel) {
    & py -3.12 -c "import openpyxl"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing openpyxl for Excel workbooks..." -ForegroundColor Yellow
        & py -3.12 -m pip install openpyxl
        if ($LASTEXITCODE -ne 0) {
            throw "openpyxl installation failed. Rerun with -SkipExcel to create CSV results only."
        }
    }
}

Write-Host "Stage A: crop forecasting for this block" -ForegroundColor Cyan
$V4Coverage = $null
if (-not $ForceForecastRebuild) {
    $V4Coverage = Get-PassingV4Coverage `
        -PointerPath $V4Pointer `
        -RequestedStart $Start `
        -RequestedEnd $End
}

if ($null -eq $V4Coverage) {
    Write-Host "Building a new 33-estate forecast for $StartDate to $EndDate..." -ForegroundColor Yellow
    & $V4Launcher `
        -CropRoot $CropRoot `
        -ForecastDays $TotalDays `
        -ForecastStart $StartDate

    $V4Coverage = Get-PassingV4Coverage `
        -PointerPath $V4Pointer `
        -RequestedStart $Start `
        -RequestedEnd $End

    if ($null -eq $V4Coverage) {
        throw "The new v4 forecast did not create a passing run covering $StartDate to $EndDate."
    }
}
else {
    Write-Host "A passing v4 forecast already covers the requested period. Reusing it." -ForegroundColor Green
}

$V4Run = $V4Coverage.run
Write-Host "Using v4 forecast run:" -ForegroundColor Cyan
Write-Host $V4Run
$null = Ensure-DailyCandidateGate -V4Run $V4Run

Write-Host ""
Write-Host "Stage B: field crop and plucker-demand calculation" -ForegroundColor Cyan
& $V5Launcher

$V5Pointer = Join-Path $ProjectRoot "workforce_planner\v5\final_method_gate_runs_v503\LATEST_BEST_AVAILABLE_PLANNING_RUN.txt"
if (-not (Test-Path $V5Pointer -PathType Leaf)) {
    throw "Final planning pointer not found: $V5Pointer"
}

$PlanningRun = (Get-Content $V5Pointer -Raw).Trim()
$PlanningSummaryPath = Join-Path $PlanningRun "run_summary.json"
if (-not (Test-Path $PlanningSummaryPath -PathType Leaf)) {
    throw "Planning summary not found: $PlanningSummaryPath"
}

$PlanningSummary = Get-Content $PlanningSummaryPath -Raw | ConvertFrom-Json
if ($PlanningSummary.status -ne "PASS_DEVELOPMENT_OUTPUTS") {
    throw "Final field and plucker-demand planning did not pass."
}

$PlanningSourceRun = ([string]$PlanningSummary.source_v4_run).Trim()
if ($PlanningSourceRun -ne $V4Run) {
    throw "v5 planning used a different v4 forecast run. Expected: $V4Run Received: $PlanningSourceRun"
}
if ([int]$PlanningSummary.forecast_dates -ne $TotalDays) {
    throw "v5 planning did not contain the expected $TotalDays dates."
}

$Desktop = [Environment]::GetFolderPath("Desktop")
if ([string]::IsNullOrWhiteSpace($OutputFolder)) {
    $OutputRoot = Join-Path $Desktop (
        "TTE_Forecasting_RL_Block_{0}_{1}" -f `
            $Start.ToString("yyyyMMdd"), `
            $End.ToString("yyyyMMdd")
    )
}
else {
    $OutputRoot = $OutputFolder.Trim()
}
$DaysRoot = Join-Path $OutputRoot "days"
$LogsRoot = Join-Path $OutputRoot "logs"
New-Item -ItemType Directory -Force -Path $DaysRoot, $LogsRoot | Out-Null

$TranscriptPath = Join-Path $LogsRoot (
    "forecasting_rl_block_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss")
)
Start-Transcript -Path $TranscriptPath | Out-Null

try {
    $Completed = 0
    $Reused = 0
    $Built = 0

    Write-Host ""
    Write-Host "Stage C: CP-SAT named allocation + protected hybrid RL inference" -ForegroundColor Cyan

    for ($offset = 0; $offset -lt $TotalDays; $offset++) {
        $Date = $Start.AddDays($offset)
        $DateText = $Date.ToString("yyyy-MM-dd")
        $DateKey = $Date.ToString("yyyyMMdd")
        $DayOutput = Join-Path $DaysRoot $DateKey

        Write-Host ""
        Write-Host "============================================================" -ForegroundColor DarkCyan
        Write-Host (
            "DATE {0} OF {1}: {2}" -f ($offset + 1), $TotalDays, $DateText
        ) -ForegroundColor Cyan
        Write-Host "============================================================" -ForegroundColor DarkCyan

        if (Test-PassingDailyResult -Folder $DayOutput) {
            Write-Host "Passing date result already exists. Skipping." -ForegroundColor Green
            $Completed++
            continue
        }

        $LegacyOutput = Join-Path $Desktop (
            "TTE_Protected_Hybrid_RL_{0}" -f $DateKey
        )
        if (Test-PassingDailyResult -Folder $LegacyOutput) {
            if (Test-Path $DayOutput) {
                Remove-Item $DayOutput -Recurse -Force
            }
            Copy-Item -Path $LegacyOutput -Destination $DayOutput -Recurse -Force
            Write-Host "Reused an existing passing one-day result." -ForegroundColor Green
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
            package_version = "16.0.0"
            start_date = $StartDate
            end_date = $EndDate
            total_days = $TotalDays
            completed_days = $Completed
            last_completed_date = $DateText
            reused_existing_days = $Reused
            newly_built_days = $Built
            forecasting = $true
            plucker_demand_calculation = $true
            named_employee_allocation = $true
            protected_hybrid_rl_inference = $true
            safety_shield = $true
            greedy_fallback = $true
            protected_hybrid_rl_shadow_only = $true
            operational_use_allowed = $false
            live_assignment_authorized = $false
        } |
            ConvertTo-Json -Depth 4 |
            Set-Content `
                -Path (Join-Path $OutputRoot "batch_progress.json") `
                -Encoding UTF8
    }

    Write-Host ""
    Write-Host "Stage D: combined CSV and monthly Excel outputs" -ForegroundColor Cyan

    $ConsolidatorArgs = @(
        $Consolidator,
        "--days-root", $DaysRoot,
        "--output-root", $OutputRoot,
        "--start-date", $StartDate,
        "--end-date", $EndDate,
        "--expected-days", $TotalDays
    )
    if ($SkipExcel) {
        $ConsolidatorArgs += "--skip-excel"
    }

    & py -3.12 @ConsolidatorArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Block output consolidation failed."
    }

    $BatchSummaryPath = Join-Path $OutputRoot "run_summary.json"
    if (-not (Test-Path $BatchSummaryPath -PathType Leaf)) {
        throw "Block run summary was not created."
    }

    $BatchSummary = Get-Content $BatchSummaryPath -Raw | ConvertFrom-Json
    if (
        $BatchSummary.status -ne `
            "PASS_PROTECTED_HYBRID_RL_MULTI_DAY_SHADOW_ALLOCATION"
    ) {
        throw "Block protected hybrid RL gate requires review."
    }

    Write-Host ""
    Write-Host "FORECASTING + PROTECTED HYBRID RL BLOCK RESULTS CREATED" -ForegroundColor Green
    Write-Host ("Output folder: {0}" -f $OutputRoot)
    Write-Host ("Dates passed: {0} of {1}" -f $BatchSummary.completed_days, $BatchSummary.expected_days)
    Write-Host ("Named employee rows: {0}" -f $BatchSummary.employee_allocation_rows)
    Write-Host ("RL model-invoked episodes: {0}" -f $BatchSummary.rl_model_invoked_episodes)
    Write-Host ("Safety violations: {0}" -f $BatchSummary.safety_violations)
    Write-Host "Forecasting: YES"
    Write-Host "Plucker-demand calculation: YES"
    Write-Host "Named employee allocation: YES"
    Write-Host "Protected hybrid RL inference: YES"
    Write-Host "RL model retraining: NO"
    Write-Host "Safety shield: YES"
    Write-Host "Greedy fallback: YES"
    Write-Host "Live operational authorization: NO"

    $StartPage = Join-Path $OutputRoot "START_HERE.html"
    if ((-not $NoOpen) -and (Test-Path $StartPage -PathType Leaf)) {
        Invoke-Item $StartPage
    }
}
finally {
    try {
        Stop-Transcript | Out-Null
    }
    catch {
    }
}
