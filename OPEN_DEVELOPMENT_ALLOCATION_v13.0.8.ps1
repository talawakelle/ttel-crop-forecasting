$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_8\development_allocation_consolidation_runs"
$Pointer = Join-Path $RunRoot "LATEST_DEVELOPMENT_ALLOCATION_V1308_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v13.0.8 development allocation run was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
Invoke-Item $RunFolder
