$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_6\rare_cross_division_exception_runs"
$Pointer = Join-Path $RunRoot "LATEST_RARE_CROSS_DIVISION_EXCEPTION_V1306_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v13.0.6 rare exception run was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
Invoke-Item (Join-Path $RunFolder "review_input")
