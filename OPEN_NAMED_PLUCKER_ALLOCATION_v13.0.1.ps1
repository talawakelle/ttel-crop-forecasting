$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_1\named_plucker_allocation_runs"
$Pointer = Join-Path $RunRoot "LATEST_NAMED_PLUCKER_ALLOCATION_V1301_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v13.0.1 named plucker allocation run was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$AllocationFolder = Join-Path $RunFolder "allocation"

Write-Host ("Opening: {0}" -f $AllocationFolder) -ForegroundColor Cyan
Invoke-Item $AllocationFolder
