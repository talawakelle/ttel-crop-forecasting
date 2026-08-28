param(
    [string]$ProjectRoot = "C:\TTE_Integrated_Platform\ttel_crop_forecasting",
    [string]$CropRoot = "C:\Users\user\Desktop\HG 2",
    [string]$ForecastStart = "2026-07-27",
    [int]$Years = 3,
    [switch]$CreateZip
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "TTE 3-YEAR DAILY FORECAST AND EMPLOYEE ALLOCATION" -ForegroundColor Cyan
Write-Host "All 33 estates, day by day, using the existing project workflow."
Write-Host ""

if (-not (Test-Path $ProjectRoot)) {
    throw "Project folder not found: $ProjectRoot"
}

if (-not (Test-Path $CropRoot)) {
    throw "Crop data folder not found: $CropRoot"
}

$dailyLauncher = Join-Path $ProjectRoot "START_DAILY_HIERARCHY_CANDIDATE_v4.0.0.ps1"
$planningLauncher = Join-Path $ProjectRoot "START_FINAL_METHOD_GATE_PLANNING_v5.0.3.ps1"
$allocationBuilder = Join-Path $ProjectRoot "BUILD_TTE_3_YEAR_EMPLOYEE_ALLOCATIONS.py"

if (-not (Test-Path $dailyLauncher)) {
    throw "Required daily forecast launcher not found: $dailyLauncher"
}

if (-not (Test-Path $planningLauncher)) {
    throw "Required field-demand planning launcher not found: $planningLauncher"
}

if (-not (Test-Path $allocationBuilder)) {
    throw "Required employee allocation builder not found: $allocationBuilder"
}

$startDate = [datetime]::ParseExact(
    $ForecastStart,
    "yyyy-MM-dd",
    [System.Globalization.CultureInfo]::InvariantCulture
)

$endExclusive = $startDate.AddYears($Years)
$forecastDays = [int]($endExclusive - $startDate).TotalDays
$endInclusive = $endExclusive.AddDays(-1)

Write-Host ("Forecast start: {0}" -f $startDate.ToString("yyyy-MM-dd"))
Write-Host ("Forecast end:   {0}" -f $endInclusive.ToString("yyyy-MM-dd"))
Write-Host ("Forecast days:  {0}" -f $forecastDays)
Write-Host ("Estate-day forecasts expected: {0}" -f (33 * $forecastDays))
Write-Host ""
Write-Host "Stage 1: daily crop forecast"
Write-Host "Stage 2: field plucker demand"
Write-Host "Stage 3: named employee allocation simulation"
Write-Host ""
Write-Host "This is a large run. Keep PowerShell open until it finishes." -ForegroundColor Yellow

Set-Location $ProjectRoot

& $dailyLauncher `
    -CropRoot $CropRoot `
    -ForecastDays $forecastDays `
    -ForecastStart $ForecastStart

if ($LASTEXITCODE -ne 0) {
    throw "Daily forecast stage returned exit code $LASTEXITCODE"
}

$v4Pointer = Join-Path `
    $ProjectRoot `
    "workforce_planner\v4\daily_hierarchy_runs\LATEST_DAILY_HIERARCHY_RUN.txt"

if (-not (Test-Path $v4Pointer)) {
    throw "Latest daily forecast pointer was not created: $v4Pointer"
}

$v4Run = (Get-Content $v4Pointer -Raw).Trim()

Write-Host ""
Write-Host "Running field plucker-demand planning..." -ForegroundColor Cyan

& $planningLauncher

if ($LASTEXITCODE -ne 0) {
    throw "Field-demand planning stage returned exit code $LASTEXITCODE"
}

$v5Root = Join-Path `
    $ProjectRoot `
    "workforce_planner\v5\final_method_gate_runs_v503"

$v5Pointer = Join-Path $v5Root "LATEST_BEST_AVAILABLE_PLANNING_RUN.txt"
$v5Run = $null

if (Test-Path $v5Pointer) {
    $candidate = (Get-Content $v5Pointer -Raw).Trim()
    if (Test-Path $candidate) {
        $v5Run = $candidate
    }
}

if ([string]::IsNullOrWhiteSpace($v5Run)) {
    $v5Run = Get-ChildItem `
        -Path $v5Root `
        -Directory `
        -Recurse `
        -ErrorAction SilentlyContinue |
        Where-Object {
            Test-Path (
                Join-Path `
                    $_.FullName `
                    "planning\field_required_plucker_assignments.csv"
            )
        } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}

if ([string]::IsNullOrWhiteSpace($v5Run)) {
    throw "Could not find the final field-demand planning run."
}

$fieldDemand = Join-Path `
    $v5Run `
    "planning\field_required_plucker_assignments.csv"

if (-not (Test-Path $fieldDemand)) {
    throw "Field demand file not found: $fieldDemand"
}

$v13Root = Join-Path `
    $ProjectRoot `
    "workforce_planner\v13_0_8\development_allocation_consolidation_runs"

$v13Pointer = Join-Path `
    $v13Root `
    "LATEST_DEVELOPMENT_ALLOCATION_V1308_RUN.txt"

if (-not (Test-Path $v13Pointer)) {
    throw "Latest v13.0.8 allocation pointer was not found."
}

$v13Run = (Get-Content $v13Pointer -Raw).Trim()
$templateAllocation = Join-Path `
    $v13Run `
    "allocation\all_development_allocation.csv"

if (-not (Test-Path $templateAllocation)) {
    throw "Named employee allocation template was not found: $templateAllocation"
}

$desktop = [Environment]::GetFolderPath("Desktop")
$outputFolder = Join-Path `
    $desktop `
    ("TTE_3_Year_Daily_Forecast_Employee_Allocation_{0}_to_{1}" -f `
        $startDate.ToString("yyyyMMdd"),
        $endInclusive.ToString("yyyyMMdd"))

if (Test-Path $outputFolder) {
    Remove-Item $outputFolder -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $outputFolder | Out-Null

Write-Host ""
Write-Host "Creating named employee allocations for every forecast date..." -ForegroundColor Cyan

& py -3.12 $allocationBuilder `
    --v4-run $v4Run `
    --v5-run $v5Run `
    --field-demand $fieldDemand `
    --employee-template $templateAllocation `
    --output-folder $outputFolder `
    --forecast-start $ForecastStart `
    --forecast-days $forecastDays `
    --expected-estates 33

if ($LASTEXITCODE -ne 0) {
    throw "Employee allocation builder returned exit code $LASTEXITCODE"
}

if ($CreateZip) {
    $zipPath = "$outputFolder.zip"

    if (Test-Path $zipPath) {
        Remove-Item $zipPath -Force
    }

    Write-Host ""
    Write-Host "Compressing the output folder. This can take a long time..." -ForegroundColor Yellow

    Compress-Archive `
        -Path (Join-Path $outputFolder "*") `
        -DestinationPath $zipPath `
        -Force

    Write-Host ("ZIP created: {0}" -f $zipPath) -ForegroundColor Green
}

Write-Host ""
Write-Host "3-YEAR FORECAST AND EMPLOYEE ALLOCATION FINISHED" -ForegroundColor Green
Write-Host ("Output folder: {0}" -f $outputFolder)
Write-Host ""
Write-Host "Open START_HERE.html first."

Invoke-Item (Join-Path $outputFolder "START_HERE.html")
