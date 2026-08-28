$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v13_0_6\rare_cross_division_exception\rare_cross_division_exception_v1306.py"
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_6\rare_cross_division_exception_runs"
$Pointer = Join-Path $RunRoot "LATEST_RARE_CROSS_DIVISION_EXCEPTION_V1306_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v13.0.6 rare exception run was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()

& py -3.12 $PythonScript --validate-run $RunFolder

if ($LASTEXITCODE -ne 0) {
    throw "Rare exception validation returned exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Run .\CHECK_RARE_CROSS_DIVISION_EXCEPTION_v13.0.6.ps1"
