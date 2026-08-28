$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$python = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "CPU environment missing. Run RUN_FIRST_TIME.bat first."
}
$source = Read-Host "Enter the full path to TTEL_Plantation_Crop_Forecasting_Pilot.xlsx"
if (-not (Test-Path $source)) {
    throw "Forecast workbook not found: $source"
}
& $python "scripts\import_crop_forecast_xlsx.py" $source
Write-Host "Crop forecast imported. Restart the planner." -ForegroundColor Green
