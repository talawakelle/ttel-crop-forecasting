$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v13_0_5\mixed_division_capacity\mixed_division_capacity_v1305.py"
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_5\mixed_division_capacity_runs"
$Pointer = Join-Path $RunRoot "LATEST_MIXED_DIVISION_CAPACITY_V1305_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v13.0.5 mixed-division capacity run was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()

& py -3.12 $PythonScript --validate-run $RunFolder

if ($LASTEXITCODE -ne 0) {
    throw "Mixed-division capacity validation returned exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Run .\CHECK_MIXED_DIVISION_CAPACITY_v13.0.5.ps1" -ForegroundColor Cyan
