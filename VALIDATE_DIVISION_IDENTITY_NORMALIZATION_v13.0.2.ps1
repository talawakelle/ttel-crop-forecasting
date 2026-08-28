$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v13_0_2\division_identity_normalization\division_identity_normalization_v1302.py"
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_2\division_identity_normalization_runs"
$Pointer = Join-Path $RunRoot "LATEST_DIVISION_IDENTITY_NORMALIZATION_V1302_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v13.0.2 division normalization run was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()

& py -3.12 $PythonScript --validate-run $RunFolder

if ($LASTEXITCODE -ne 0) {
    throw "Division identity validation returned exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Run .\CHECK_DIVISION_IDENTITY_NORMALIZATION_v13.0.2.ps1" -ForegroundColor Cyan
