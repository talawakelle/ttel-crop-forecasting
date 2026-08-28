$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_5\mixed_division_capacity_runs"
$Pointer = Join-Path $RunRoot "LATEST_MIXED_DIVISION_CAPACITY_V1305_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v13.0.5 mixed-division capacity run was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$ReviewFolder = Join-Path $RunFolder "review_input"

Write-Host ("Opening: {0}" -f $ReviewFolder) -ForegroundColor Cyan
Invoke-Item $ReviewFolder
