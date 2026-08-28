param(
    [Parameter(Mandatory = $true)]
    [string]$Source
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "backend\.venv\Scripts\python.exe"
$Daily = Join-Path $Root "data\weather_daily.csv.gz"
$Metadata = Join-Path $Root "data\weather_metadata.json"
$Backup = Join-Path $Root "data\weather-update-backup"

if (-not (Test-Path $Python)) { throw "Python environment not found." }
if (-not (Test-Path -LiteralPath $Source)) { throw "Weather source not found: $Source" }

Set-Location $Root
New-Item -ItemType Directory -Force $Backup | Out-Null
Copy-Item -LiteralPath $Daily -Destination (Join-Path $Backup "weather_daily.csv.gz") -Force
Copy-Item -LiteralPath $Metadata -Destination (Join-Path $Backup "weather_metadata.json") -Force

try {
    & $Python "scripts\prepare_weather_data.py" $Source
    if ($LASTEXITCODE -ne 0) { throw "Weather preparation failed." }
    & $Python "scripts\check_weather_data.py"
    if ($LASTEXITCODE -ne 0) { throw "New weather data failed validation." }
    & $Python "scripts\check_forecast_data.py"
    if ($LASTEXITCODE -ne 0) {
        throw "The historical weather used for model training changed. Retraining is required."
    }
} catch {
    Copy-Item -LiteralPath (Join-Path $Backup "weather_daily.csv.gz") -Destination $Daily -Force
    Copy-Item -LiteralPath (Join-Path $Backup "weather_metadata.json") -Destination $Metadata -Force
    throw
}

& $Python "scripts\check_forecast.py"
Write-Host "Weather history updated safely. Restart the dashboard." -ForegroundColor Green
