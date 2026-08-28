[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InputPath,

    [string]$ReportPath = "outputs\input_validation_report.csv"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "The Python environment is missing. Run .\setup_windows.ps1 first."
}
if (-not (Test-Path $InputPath)) {
    throw "Input workbook or CSV directory not found: $InputPath"
}

& $Python validate_inputs.py $InputPath --report $ReportPath
if ($LASTEXITCODE -ne 0) {
    Write-Host "Validation found blocking errors. Open $ReportPath and correct them before training." -ForegroundColor Yellow
    exit $LASTEXITCODE
}

Write-Host "Validation passed. Report: $ReportPath" -ForegroundColor Green

