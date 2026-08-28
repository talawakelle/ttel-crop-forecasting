$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v13_0_6\rare_cross_division_exception\rare_cross_division_exception_v1306.py"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_6\rare_cross_division_exception_runs"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

Write-Host "Starting rare cross-division exception review v13.0.6..." -ForegroundColor Cyan
Write-Host "Same-division allocation remains the normal model."
Write-Host "Cross-division work is treated only as a small exception activity."
Write-Host "No percentage threshold is invented; the actual rate will be reported."
Write-Host "No employee notification or live allocation will run."

& py -3.12 $PythonScript `
    --project-root $ProjectRoot `
    --output-root $OutputRoot

if ($LASTEXITCODE -ne 0) {
    throw "Rare exception review returned exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Run .\CHECK_RARE_CROSS_DIVISION_EXCEPTION_v13.0.6.ps1"
Write-Host "Run .\OPEN_RARE_CROSS_DIVISION_EXCEPTION_REVIEW_v13.0.6.ps1"
