param(
    [string]$ProjectRoot = "C:\TTE_Integrated_Platform\ttel_crop_forecasting",
    [string]$CropRoot = "C:\Users\user\Desktop\HG 2",
    [string]$ForecastStart = "2026-07-24",
    [int]$Years = 3
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "TTE 3-YEAR DAILY FORECAST — ALL 33 ESTATES" -ForegroundColor Cyan
Write-Host "This creates a long-range planning projection, not a live operational forecast." -ForegroundColor Yellow
Write-Host ""

if (-not (Test-Path $ProjectRoot)) {
    throw "Project folder not found: $ProjectRoot"
}

if (-not (Test-Path $CropRoot)) {
    throw "Crop data folder not found: $CropRoot"
}

$launcher = Join-Path $ProjectRoot "START_DAILY_HIERARCHY_CANDIDATE_v4.0.0.ps1"
if (-not (Test-Path $launcher)) {
    throw "Required launcher not found: $launcher"
}

$reportBuilder = Join-Path $ProjectRoot "BUILD_TTE_3_YEAR_DAILY_FORECAST_REPORT.py"
if (-not (Test-Path $reportBuilder)) {
    throw "Report builder not found: $reportBuilder"
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
Write-Host ("Calendar days:  {0}" -f $forecastDays)
Write-Host ("Expected estate rows: {0}" -f (33 * $forecastDays))
Write-Host ""
Write-Host "The existing 4-week dashboard will remain unchanged."
Write-Host "A separate 3-year daily supervisor pack will be created on the Desktop."
Write-Host ""

Set-Location $ProjectRoot

& $launcher `
    -CropRoot $CropRoot `
    -ForecastDays $forecastDays `
    -ForecastStart $ForecastStart

if ($LASTEXITCODE -ne 0) {
    throw "The daily hierarchy launcher returned exit code $LASTEXITCODE"
}

$pointer = Join-Path `
    $ProjectRoot `
    "workforce_planner\v4\daily_hierarchy_runs\LATEST_DAILY_HIERARCHY_RUN.txt"

if (-not (Test-Path $pointer)) {
    throw "Latest daily hierarchy run pointer was not created: $pointer"
}

$runFolder = (Get-Content $pointer -Raw).Trim()
if (-not (Test-Path $runFolder)) {
    throw "The latest run folder does not exist: $runFolder"
}

$desktop = [Environment]::GetFolderPath("Desktop")
$outputFolder = Join-Path `
    $desktop `
    ("TTE_3_Year_Daily_Forecast_{0}_to_{1}" -f `
        $startDate.ToString("yyyyMMdd"),
        $endInclusive.ToString("yyyyMMdd"))

if (Test-Path $outputFolder) {
    Remove-Item $outputFolder -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $outputFolder | Out-Null

Write-Host ""
Write-Host "Building the 3-year supervisor report..." -ForegroundColor Cyan

& py -3.12 $reportBuilder `
    --run-folder $runFolder `
    --output-folder $outputFolder `
    --forecast-start $ForecastStart `
    --forecast-days $forecastDays `
    --expected-estates 33

if ($LASTEXITCODE -ne 0) {
    throw "The report builder returned exit code $LASTEXITCODE"
}

$zipPath = "$outputFolder.zip"
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

Compress-Archive `
    -Path (Join-Path $outputFolder "*") `
    -DestinationPath $zipPath `
    -Force

Write-Host ""
Write-Host "3-YEAR DAILY FORECAST PACK CREATED" -ForegroundColor Green
Write-Host ("Folder: {0}" -f $outputFolder)
Write-Host ("ZIP:    {0}" -f $zipPath)
Write-Host ""
Write-Host "Open START_HERE_3_YEAR_FORECAST.html first."
Write-Host "This remains a development and long-range planning projection."
Write-Host "It does not authorize live workforce deployment."

Invoke-Item (Join-Path $outputFolder "START_HERE_3_YEAR_FORECAST.html")
