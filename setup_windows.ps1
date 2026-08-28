[CmdletBinding()]
param(
    [switch]$RecreateEnvironment
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Write-Host "Plantation Crop Forecasting - Windows Setup" -ForegroundColor Green

if ($RecreateEnvironment -and (Test-Path ".venv")) {
    Remove-Item ".venv" -Recurse -Force
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m venv .venv
        if ($LASTEXITCODE -ne 0) {
            & py -3 -m venv .venv
        }
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv .venv
    }
    else {
        throw "Python 3.11 or 3.12 is required. Install Python, reopen VS Code, and run this script again."
    }
}

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements.txt

$Folders = @(
    "data\incoming\crop",
    "data\incoming\weather",
    "data\incoming\practice",
    "data\incoming\sundry_work",
    "data\incoming\field_master",
    "data\incoming\financials",
    "data\validated",
    "outputs"
)
foreach ($Folder in $Folders) {
    New-Item -ItemType Directory -Force -Path $Folder | Out-Null
}

& $Python -m py_compile `
    train.py `
    train_pooled_short_history.py `
    build_portfolio_summary.py `
    validate_inputs.py `
    check_crop_gpu.py `
    discover_estate_archives.py `
    prepare_weather_cache.py `
    src\pipeline.py `
    src\modeling.py `
    src\pooled_modeling.py `
    src\data_contract.py
if ($LASTEXITCODE -ne 0) { throw "Crop forecasting source validation failed." }

Write-Host "Setup completed successfully." -ForegroundColor Green
Write-Host "Place estate ZIP files in data\incoming\crop and weather files in data\incoming\weather."
Write-Host "Use .\train_estate.ps1 for the first estate pilot."
