param(
    [string]$ProjectRoot = "C:\TTE_Integrated_Platform\ttel_crop_forecasting",
    [string]$CropRoot = "C:\Users\user\Desktop\HG 2",
    [string]$StartDate = "2026-07-27",
    [string]$EndDate = "2031-07-26",
    [int]$BlockDays = 90,
    [int]$MaxBlocksThisRun = 0,
    [double]$CpSatTimeLimitSeconds = 45,
    [int]$CpSatWorkers = 0,
    [switch]$ForceForecastRebuild,
    [switch]$SkipExcel,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"

function Test-PassingBlockResult {
    param([string]$Folder)

    $summaryPath = Join-Path $Folder "run_summary.json"
    if (-not (Test-Path $summaryPath -PathType Leaf)) {
        return $false
    }

    try {
        $summary = Get-Content $summaryPath -Raw | ConvertFrom-Json
        return $summary.status -eq `
            "PASS_PROTECTED_HYBRID_RL_MULTI_DAY_SHADOW_ALLOCATION"
    }
    catch {
        return $false
    }
}

function Update-MasterIndex {
    param(
        [string]$Builder,
        [string]$MasterRoot,
        [string]$PlanFile,
        [string]$StartDate,
        [string]$EndDate,
        [bool]$SkipExcel
    )

    $args = @(
        $Builder,
        "--master-root", $MasterRoot,
        "--plan-file", $PlanFile,
        "--start-date", $StartDate,
        "--end-date", $EndDate
    )
    if ($SkipExcel) {
        $args += "--skip-excel"
    }

    & py -3.12 @args
    if ($LASTEXITCODE -ne 0) {
        throw "Continuous project master-index update failed."
    }
}

Write-Host ""
Write-Host "TTE CONTINUOUS FORECASTING + PROTECTED HYBRID RL v16.0.0" -ForegroundColor Cyan
Write-Host "This is resumable block processing. Completed passing blocks are skipped."
Write-Host "This runs protected hybrid RL inference; it does not retrain the RL model."
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
if ($BlockDays -lt 7 -or $BlockDays -gt 90) {
    throw "BlockDays must be between 7 and 90. The forecasting engine has a 90-day maximum."
}
if ($MaxBlocksThisRun -lt 0) {
    throw "MaxBlocksThisRun must be 0 or greater. Use 0 to continue through every remaining block."
}
if (-not (Test-Path $ProjectRoot -PathType Container)) {
    throw "Project folder not found: $ProjectRoot"
}
if (-not (Test-Path $CropRoot -PathType Container)) {
    throw "Crop archive folder not found: $CropRoot"
}

$BlockRunner = Join-Path $ProjectRoot "RUN_TTE_FORECASTING_RL_BLOCK_v16.0.0.ps1"
$MasterBuilder = Join-Path $ProjectRoot "workforce_planner\v16_0_0\batch\build_continuous_master_index_v1600.py"
foreach ($required in @($BlockRunner, $MasterBuilder)) {
    if (-not (Test-Path $required -PathType Leaf)) {
        throw "Required continuous project file not found: $required"
    }
}

& py -3.12 -c "import torch; from ortools.sat.python import cp_model"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.12 requires both PyTorch and OR-Tools."
}

$CudaResult = (& py -3.12 -c "import torch; print('YES' if torch.cuda.is_available() else 'NO')").Trim()
if ($LASTEXITCODE -ne 0 -or $CudaResult -ne "YES") {
    throw "CUDA is not available in Python 3.12. This package requires protected hybrid RL inference on CUDA."
}

if (-not $SkipExcel) {
    & py -3.12 -c "import openpyxl"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing openpyxl for monthly Excel workbooks..." -ForegroundColor Yellow
        & py -3.12 -m pip install openpyxl
        if ($LASTEXITCODE -ne 0) {
            throw "openpyxl installation failed. Rerun with -SkipExcel for CSV-only results."
        }
    }
}

$Desktop = [Environment]::GetFolderPath("Desktop")
$MasterRoot = Join-Path $Desktop (
    "TTE_Forecasting_RL_Continuous_{0}_{1}" -f `
        $Start.ToString("yyyyMMdd"), `
        $End.ToString("yyyyMMdd")
)
$BlocksRoot = Join-Path $MasterRoot "blocks"
$MasterFolder = Join-Path $MasterRoot "master"
$LogsRoot = Join-Path $MasterRoot "logs"
New-Item -ItemType Directory -Force -Path `
    $MasterRoot, $BlocksRoot, $MasterFolder, $LogsRoot | Out-Null

$PlanFile = Join-Path $MasterFolder "master_plan.csv"
$TotalDays = ($End - $Start).Days + 1
$Rows = New-Object System.Collections.Generic.List[object]
$Current = $Start
$Remaining = $TotalDays
$BlockNumber = 1

while ($Remaining -gt 0) {
    $DaysThisBlock = [Math]::Min($BlockDays, $Remaining)

    # The v4 forecast engine requires at least 7 days. Avoid a final block below 7.
    if (
        $Remaining -gt $BlockDays -and
        ($Remaining - $BlockDays) -lt 7
    ) {
        $DaysThisBlock = $Remaining - 7
    }

    $BlockEnd = $Current.AddDays($DaysThisBlock - 1)
    $RelativeFolder = (
        "blocks\block_{0:D3}_{1}_{2}" -f `
            $BlockNumber, `
            $Current.ToString("yyyyMMdd"), `
            $BlockEnd.ToString("yyyyMMdd")
    )

    $Rows.Add([PSCustomObject]@{
        block_number = $BlockNumber
        start_date = $Current.ToString("yyyy-MM-dd")
        end_date = $BlockEnd.ToString("yyyy-MM-dd")
        days = $DaysThisBlock
        output_folder = $RelativeFolder
    })

    $Current = $BlockEnd.AddDays(1)
    $Remaining -= $DaysThisBlock
    $BlockNumber++
}

$Rows | Export-Csv $PlanFile -NoTypeInformation -Encoding UTF8

$DriveRoot = [System.IO.Path]::GetPathRoot($MasterRoot)
$DriveName = $DriveRoot.Substring(0, 1)
$DriveInfo = Get-PSDrive -Name $DriveName -ErrorAction SilentlyContinue
if ($null -ne $DriveInfo) {
    $FreeGB = [Math]::Round($DriveInfo.Free / 1GB, 1)
    Write-Host ("Available disk space on {0}: {1} GB" -f $DriveName, $FreeGB)
    if ($FreeGB -lt 20) {
        Write-Host "WARNING: less than 20 GB is free. Multi-year named employee outputs may require substantial disk space." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host ("Project period: {0} to {1}" -f $StartDate, $EndDate)
Write-Host ("Total dates: {0}" -f $TotalDays)
Write-Host ("Planned blocks: {0}" -f $Rows.Count)
Write-Host ("Maximum days per block: {0}" -f $BlockDays)
if ($MaxBlocksThisRun -eq 0) {
    Write-Host "Session limit: ALL remaining blocks"
}
else {
    Write-Host ("Session limit: {0} new block(s)" -f $MaxBlocksThisRun)
}
Write-Host ""
Write-Host "Included workflow:" -ForegroundColor Cyan
Write-Host "Forecasting: YES"
Write-Host "Plucker-demand calculation: YES"
Write-Host "Named employee allocation: YES"
Write-Host "Protected hybrid RL inference on CUDA: YES"
Write-Host "RL model retraining: NO"
Write-Host "Safety shield: YES"
Write-Host "Greedy fallback: YES"
Write-Host "Monthly Excel workbooks: YES"
Write-Host "Live operational authorization: NO"
Write-Host ""

Update-MasterIndex `
    -Builder $MasterBuilder `
    -MasterRoot $MasterRoot `
    -PlanFile $PlanFile `
    -StartDate $StartDate `
    -EndDate $EndDate `
    -SkipExcel ([bool]$SkipExcel)

$TranscriptPath = Join-Path $LogsRoot (
    "continuous_project_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss")
)
Start-Transcript -Path $TranscriptPath | Out-Null

$NewBlocksProcessed = 0
$AllPassed = $true

try {
    foreach ($row in $Rows) {
        $BlockOutput = Join-Path $MasterRoot $row.output_folder
        $BlockLabel = (
            "BLOCK {0} OF {1}: {2} TO {3} ({4} DAYS)" -f `
                $row.block_number, `
                $Rows.Count, `
                $row.start_date, `
                $row.end_date, `
                $row.days
        )

        Write-Host ""
        Write-Host "================================================================" -ForegroundColor DarkCyan
        Write-Host $BlockLabel -ForegroundColor Cyan
        Write-Host "================================================================" -ForegroundColor DarkCyan

        if (Test-PassingBlockResult -Folder $BlockOutput) {
            Write-Host "Passing block already exists. Skipping." -ForegroundColor Green
            continue
        }

        if (
            $MaxBlocksThisRun -gt 0 -and
            $NewBlocksProcessed -ge $MaxBlocksThisRun
        ) {
            Write-Host "The requested session block limit has been reached." -ForegroundColor Yellow
            $AllPassed = $false
            break
        }

        try {
            $BlockArgs = @{
                ProjectRoot = $ProjectRoot
                CropRoot = $CropRoot
                StartDate = $row.start_date
                EndDate = $row.end_date
                OutputFolder = $BlockOutput
                CpSatTimeLimitSeconds = $CpSatTimeLimitSeconds
                CpSatWorkers = $CpSatWorkers
                NoOpen = $true
            }
            if ($ForceForecastRebuild) {
                $BlockArgs["ForceForecastRebuild"] = $true
            }
            if ($SkipExcel) {
                $BlockArgs["SkipExcel"] = $true
            }

            & $BlockRunner @BlockArgs

            if (-not (Test-PassingBlockResult -Folder $BlockOutput)) {
                throw "The block did not create a passing protected hybrid RL summary."
            }

            $NewBlocksProcessed++

            Update-MasterIndex `
                -Builder $MasterBuilder `
                -MasterRoot $MasterRoot `
                -PlanFile $PlanFile `
                -StartDate $StartDate `
                -EndDate $EndDate `
                -SkipExcel ([bool]$SkipExcel)
        }
        catch {
            $Failure = [PSCustomObject]@{
                status = "BLOCK_FAILED"
                package_version = "16.0.0"
                block_number = $row.block_number
                block_start_date = $row.start_date
                block_end_date = $row.end_date
                error_message = $_.Exception.Message
                failed_at = (Get-Date).ToString("s")
                forecasting = $true
                plucker_demand_calculation = $true
                named_employee_allocation = $true
                protected_hybrid_rl_inference = $true
                rl_model_retraining = $false
                safety_shield = $true
                greedy_fallback = $true
                operational_use_allowed = $false
                live_assignment_authorized = $false
            }
            $Failure |
                ConvertTo-Json -Depth 4 |
                Set-Content `
                    -Path (Join-Path $MasterRoot "last_failure.json") `
                    -Encoding UTF8

            try {
                Update-MasterIndex `
                    -Builder $MasterBuilder `
                    -MasterRoot $MasterRoot `
                    -PlanFile $PlanFile `
                    -StartDate $StartDate `
                    -EndDate $EndDate `
                    -SkipExcel ([bool]$SkipExcel)
            }
            catch {
            }

            Write-Host ""
            Write-Host "BLOCK FAILED. Rerun the same master command to resume." -ForegroundColor Red
            throw
        }
    }

    Update-MasterIndex `
        -Builder $MasterBuilder `
        -MasterRoot $MasterRoot `
        -PlanFile $PlanFile `
        -StartDate $StartDate `
        -EndDate $EndDate `
        -SkipExcel ([bool]$SkipExcel)

    $MasterSummaryPath = Join-Path $MasterRoot "run_summary.json"
    $MasterSummary = Get-Content $MasterSummaryPath -Raw | ConvertFrom-Json

    Write-Host ""
    Write-Host "CONTINUOUS PROJECT SESSION FINISHED" -ForegroundColor Green
    Write-Host ("Output folder: {0}" -f $MasterRoot)
    Write-Host (
        "Completed blocks: {0} of {1}" -f `
            $MasterSummary.completed_blocks, `
            $MasterSummary.planned_blocks
    )
    Write-Host (
        "Completed dates: {0} of {1}" -f `
            $MasterSummary.completed_days, `
            $MasterSummary.planned_days
    )
    Write-Host ("Named employee rows: {0}" -f $MasterSummary.employee_allocation_rows)
    Write-Host ("RL model-invoked episodes: {0}" -f $MasterSummary.rl_model_invoked_episodes)
    Write-Host ("Safety violations: {0}" -f $MasterSummary.safety_violations)
    Write-Host "Forecasting: YES"
    Write-Host "Plucker-demand calculation: YES"
    Write-Host "Named employee allocation: YES"
    Write-Host "Protected hybrid RL inference on CUDA: YES"
    Write-Host "RL model retraining: NO"
    Write-Host "Safety shield: YES"
    Write-Host "Greedy fallback: YES"
    Write-Host "Monthly Excel workbooks: YES"
    Write-Host "Live operational authorization: NO"

    if (
        (-not $NoOpen) -and
        (Test-Path (Join-Path $MasterRoot "START_HERE.html") -PathType Leaf)
    ) {
        Invoke-Item (Join-Path $MasterRoot "START_HERE.html")
    }
}
finally {
    try {
        Stop-Transcript | Out-Null
    }
    catch {
    }
}
