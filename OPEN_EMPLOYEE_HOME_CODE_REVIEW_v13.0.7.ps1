$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_7\employee_home_code_supervisor_review_runs"
$Pointer = Join-Path $RunRoot "LATEST_EMPLOYEE_HOME_CODE_REVIEW_V1307_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v13.0.7 employee home-code review run was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
Invoke-Item (Join-Path $RunFolder "review_input")
