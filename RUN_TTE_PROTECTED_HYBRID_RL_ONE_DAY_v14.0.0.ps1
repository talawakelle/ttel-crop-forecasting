param(
    [string]$ProjectRoot = "C:\TTE_Integrated_Platform\ttel_crop_forecasting",
    [string]$AllocationDate = "2026-07-27",
    [double]$CpSatTimeLimitSeconds = 45,
    [int]$CpSatWorkers = 0
)

$ErrorActionPreference = "Stop"

function Get-LatestChildFolder {
    param([string]$Root)

    $folder = Get-ChildItem `
        -Path $Root `
        -Directory `
        -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if ($null -eq $folder) {
        throw "No run folder was created under: $Root"
    }

    return $folder.FullName
}

function Ensure-DailyCandidateGate {
    param([string]$V4Run)

    $selectedModels = Join-Path `
        $V4Run `
        "backtest\estate_selected_models.csv"

    $gateFile = Join-Path `
        $V4Run `
        "backtest\daily_candidate_gate.csv"

    if (Test-Path $gateFile) {
        Write-Host "Daily candidate gate already exists." -ForegroundColor Green
        return $gateFile
    }

    if (-not (Test-Path $selectedModels)) {
        throw "Selected model file not found: $selectedModels"
    }

    $gateRows = foreach ($row in Import-Csv $selectedModels) {
        $wape = [double]$row.selected_wape_pct
        $gate = "REJECTED_DAILY_BASELINE"

        if ($wape -le 30) {
            $gate = "PROVISIONAL_DAILY_CANDIDATE"
        }
        if ($wape -le 25) {
            $gate = "ACCEPTED_WITH_REVIEW"
        }
        if ($wape -le 20) {
            $gate = "ACCEPTED_DEVELOPMENT_CANDIDATE"
        }

        if ($row.estate -in @(
            "Tillicoultry",
            "EildonHall",
            "bambarakelly"
        )) {
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
        Export-Csv `
            $gateFile `
            -NoTypeInformation `
            -Encoding UTF8

    Write-Host "Created missing daily candidate gate:" -ForegroundColor Green
    Write-Host $gateFile
    return $gateFile
}

Write-Host ""
Write-Host "TTE PROTECTED HYBRID RL DAILY ALLOCATION v14.0.0" -ForegroundColor Cyan
Write-Host "Allocation date: $AllocationDate"
Write-Host ""

if (-not (Test-Path $ProjectRoot -PathType Container)) {
    throw "Project folder not found: $ProjectRoot"
}

$TargetDate = [datetime]::ParseExact(
    $AllocationDate,
    "yyyy-MM-dd",
    [System.Globalization.CultureInfo]::InvariantCulture
)

$RuntimeRoot = Join-Path `
    $ProjectRoot `
    "workforce_planner\v14_0_0"

$CpSatScript = Join-Path `
    $RuntimeRoot `
    "runtime_sources\v7\run_cp_sat_capacity_matching_v710.py"

$GreedyScript = Join-Path `
    $RuntimeRoot `
    "runtime_sources\v8\run_greedy_comparison_v800.py"

$BalancedScript = Join-Path `
    $RuntimeRoot `
    "runtime_sources\v8\run_balanced_baseline_review_v801.py"

$EnvironmentScript = Join-Path `
    $RuntimeRoot `
    "runtime_sources\v9\build_rl_environment_v900.py"

$InferenceScript = Join-Path `
    $RuntimeRoot `
    "protected_hybrid_daily\run_protected_hybrid_daily_v1400.py"

$ModelPath = Join-Path `
    $RuntimeRoot `
    "model\safe_action_q_network.pt"

$RouteRegister = Join-Path `
    $RuntimeRoot `
    "policy\repaired_shadow_route_register.csv"

foreach ($requiredFile in @(
    $CpSatScript,
    $GreedyScript,
    $BalancedScript,
    $EnvironmentScript,
    $InferenceScript,
    $ModelPath,
    $RouteRegister
)) {
    if (-not (Test-Path $requiredFile -PathType Leaf)) {
        throw "Required v14 file not found: $requiredFile"
    }
}

& py -3.12 -c "import torch; from ortools.sat.python import cp_model; print('PyTorch:', torch.__version__); print('CUDA:', torch.cuda.is_available()); print('OR-Tools: available')"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.12 requires both PyTorch and OR-Tools."
}

$V4Pointer = Join-Path `
    $ProjectRoot `
    "workforce_planner\v4\daily_hierarchy_runs\LATEST_DAILY_HIERARCHY_RUN.txt"

if (-not (Test-Path $V4Pointer)) {
    throw "Latest v4 daily hierarchy pointer was not found: $V4Pointer"
}

$V4Run = (Get-Content $V4Pointer -Raw).Trim()
$V4SummaryPath = Join-Path $V4Run "run_summary.json"

if (-not (Test-Path $V4SummaryPath)) {
    throw "v4 run summary not found: $V4SummaryPath"
}

$V4Summary = Get-Content $V4SummaryPath -Raw | ConvertFrom-Json
$V4Start = [datetime]::Parse($V4Summary.forecast_start)
$V4End = $V4Start.AddDays([int]$V4Summary.forecast_days - 1)

if ($TargetDate -lt $V4Start -or $TargetDate -gt $V4End) {
    $CoverageMessage = (
        "The latest v4 forecast covers {0} to {1}, not {2}. " +
        "Create a v4 forecast that includes the requested date."
    ) -f `
        $V4Start.ToString("yyyy-MM-dd"), `
        $V4End.ToString("yyyy-MM-dd"), `
        $AllocationDate

    throw $CoverageMessage
}

Write-Host "Using v4 forecast run:" -ForegroundColor Cyan
Write-Host $V4Run

$null = Ensure-DailyCandidateGate -V4Run $V4Run

$V5Launcher = Join-Path `
    $ProjectRoot `
    "START_FINAL_METHOD_GATE_PLANNING_v5.0.3.ps1"

if (-not (Test-Path $V5Launcher)) {
    throw "v5 launcher not found: $V5Launcher"
}

Write-Host ""
Write-Host "Stage 1 of 6: final field and plucker demand" -ForegroundColor Cyan
& $V5Launcher
if ($LASTEXITCODE -ne 0) {
    throw "Final method-gated planning failed."
}

$V5Pointer = Join-Path `
    $ProjectRoot `
    "workforce_planner\v5\final_method_gate_runs_v503\LATEST_BEST_AVAILABLE_PLANNING_RUN.txt"

if (-not (Test-Path $V5Pointer)) {
    throw "Final planning pointer not found: $V5Pointer"
}

$PlanningRun = (Get-Content $V5Pointer -Raw).Trim()
$FullDemandPath = Join-Path `
    $PlanningRun `
    "planning\field_required_plucker_assignments.csv"

if (-not (Test-Path $FullDemandPath)) {
    throw "Field demand file not found: $FullDemandPath"
}

$DayRows = Import-Csv $FullDemandPath | Where-Object {
    $_.date -eq $AllocationDate
}

if ($DayRows.Count -eq 0) {
    throw "No field demand rows were found for $AllocationDate."
}

$DayInputRoot = Join-Path `
    $RuntimeRoot `
    ("daily_inputs\planning_{0}" -f $TargetDate.ToString("yyyyMMdd"))

$DayPlanningFolder = Join-Path $DayInputRoot "planning"
New-Item -ItemType Directory -Force -Path $DayPlanningFolder | Out-Null

$DayDemandPath = Join-Path `
    $DayPlanningFolder `
    "field_required_plucker_assignments.csv"

$DayRows |
    Export-Csv `
        $DayDemandPath `
        -NoTypeInformation `
        -Encoding UTF8

$EmployeePointer = Join-Path `
    $ProjectRoot `
    "workforce_planner\v6\employee_readiness_runs\LATEST_EMPLOYEE_READINESS_RUN.txt"

if (-not (Test-Path $EmployeePointer)) {
    throw "Employee readiness pointer not found: $EmployeePointer"
}

$EmployeeRun = (Get-Content $EmployeePointer -Raw).Trim()

$RunRoot = Join-Path `
    $RuntimeRoot `
    ("daily_runs\{0}" -f $TargetDate.ToString("yyyyMMdd"))

$Desktop = [Environment]::GetFolderPath("Desktop")
$FinalOutput = Join-Path `
    $Desktop `
    ("TTE_Protected_Hybrid_RL_{0}" -f $TargetDate.ToString("yyyyMMdd"))

$ExistingSummary = Join-Path $FinalOutput "run_summary.json"
if (Test-Path $ExistingSummary) {
    try {
        $Existing = Get-Content $ExistingSummary -Raw | ConvertFrom-Json
        if ($Existing.status -eq "PASS_PROTECTED_HYBRID_RL_DAILY_SHADOW_ALLOCATION") {
            Write-Host "A passing result already exists. Opening it." -ForegroundColor Green
            Invoke-Item (Join-Path $FinalOutput "START_HERE.html")
            return
        }
    }
    catch {
        Write-Host "Existing result is incomplete. Rebuilding." -ForegroundColor Yellow
    }
}

if (Test-Path $RunRoot) {
    Remove-Item $RunRoot -Recurse -Force
}
if (Test-Path $FinalOutput) {
    Remove-Item $FinalOutput -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $RunRoot, $FinalOutput | Out-Null

if ($CpSatWorkers -le 0) {
    $CpSatWorkers = [math]::Max(1, [Environment]::ProcessorCount - 1)
}

Write-Host ""
Write-Host "Stage 2 of 6: CP-SAT morning allocation" -ForegroundColor Cyan
$CpSatRoot = Join-Path $RunRoot "01_cp_sat"
New-Item -ItemType Directory -Force -Path $CpSatRoot | Out-Null

& py -3.12 $CpSatScript `
    --employee-run $EmployeeRun `
    --planning-run $DayInputRoot `
    --output-root $CpSatRoot `
    --scenarios BOTH `
    --time-limit-seconds $CpSatTimeLimitSeconds `
    --workers $CpSatWorkers

if ($LASTEXITCODE -ne 0) {
    throw "CP-SAT morning allocation failed."
}

$CapacityRun = Get-LatestChildFolder -Root $CpSatRoot

Write-Host ""
Write-Host "Stage 3 of 6: CP-SAT versus greedy comparison" -ForegroundColor Cyan
$GreedyRoot = Join-Path $RunRoot "02_greedy_comparison"
New-Item -ItemType Directory -Force -Path $GreedyRoot | Out-Null

& py -3.12 $GreedyScript `
    --capacity-run $CapacityRun `
    --planning-run $DayInputRoot `
    --output-root $GreedyRoot

if ($LASTEXITCODE -ne 0) {
    throw "CP-SAT versus greedy comparison failed."
}

$GreedyRun = Get-LatestChildFolder -Root $GreedyRoot

Write-Host ""
Write-Host "Stage 4 of 6: balanced baseline safety gate" -ForegroundColor Cyan
$BalancedRoot = Join-Path $RunRoot "03_balanced_baseline"
New-Item -ItemType Directory -Force -Path $BalancedRoot | Out-Null

& py -3.12 $BalancedScript `
    --comparison-run $GreedyRun `
    --capacity-run $CapacityRun `
    --output-root $BalancedRoot `
    --minimum-gate-pct 80 `
    --absolute-tolerance-kg 2 `
    --relative-tolerance-pct 0.05 `
    --maximum-shortfall-rate-pct 0.10

if ($LASTEXITCODE -ne 0) {
    throw "Balanced baseline safety gate failed."
}

$BalancedRun = Get-LatestChildFolder -Root $BalancedRoot

$FieldResultPath = Join-Path `
    $CapacityRun `
    "quality\cp_sat_capacity_field_results.csv"

if (-not (Test-Path $FieldResultPath)) {
    throw "CP-SAT field result not found: $FieldResultPath"
}

$ExpectedFieldRows = (Import-Csv $FieldResultPath).Count

Write-Host ""
Write-Host "Stage 5 of 6: dynamic RL environment" -ForegroundColor Cyan
$EnvironmentRoot = Join-Path $RunRoot "04_rl_environment"
New-Item -ItemType Directory -Force -Path $EnvironmentRoot | Out-Null

& py -3.12 $EnvironmentScript `
    --capacity-run $CapacityRun `
    --comparison-run $GreedyRun `
    --balanced-run $BalancedRun `
    --output-root $EnvironmentRoot `
    --shock-count 5 `
    --expected-field-rows $ExpectedFieldRows

if ($LASTEXITCODE -ne 0) {
    throw "Dynamic RL environment creation failed."
}

$EnvironmentRun = Get-LatestChildFolder -Root $EnvironmentRoot
$ManifestPath = Join-Path $EnvironmentRun "rl_environment_manifest.json"

Write-Host ""
Write-Host "Stage 6 of 6: protected hybrid RL inference" -ForegroundColor Cyan

& py -3.12 $InferenceScript `
    --manifest $ManifestPath `
    --model-path $ModelPath `
    --route-register $RouteRegister `
    --allocation-date $AllocationDate `
    --output-folder $FinalOutput `
    --max-moves 5 `
    --max-actions 100 `
    --hybrid-ratio 0.95 `
    --expected-episodes 66

if ($LASTEXITCODE -ne 0) {
    throw "Protected hybrid RL inference failed."
}

$PipelineSources = [PSCustomObject]@{
    allocation_date = $AllocationDate
    v4_forecast_run = $V4Run
    v5_planning_run = $PlanningRun
    employee_readiness_run = $EmployeeRun
    cp_sat_run = $CapacityRun
    greedy_comparison_run = $GreedyRun
    balanced_baseline_run = $BalancedRun
    rl_environment_run = $EnvironmentRun
    rl_model_path = $ModelPath
    route_register = $RouteRegister
}

$PipelineSources |
    ConvertTo-Json -Depth 4 |
    Set-Content `
        -Path (Join-Path $FinalOutput "pipeline_sources.json") `
        -Encoding UTF8

Write-Host ""
Write-Host "PROTECTED HYBRID RL DAILY RESULT CREATED" -ForegroundColor Green
Write-Host ("Output: {0}" -f $FinalOutput)
Write-Host "Open START_HERE.html first."
Write-Host ""
Write-Host "Protected hybrid RL system: YES"
Write-Host "Safety shield: YES"
Write-Host "Greedy fallback: YES"
Write-Host "Live assignment authorized: NO"

Invoke-Item (Join-Path $FinalOutput "START_HERE.html")
