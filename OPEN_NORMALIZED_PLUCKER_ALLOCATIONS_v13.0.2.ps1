$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_2\division_identity_normalization_runs"
$Pointer = Join-Path $RunRoot "LATEST_DIVISION_IDENTITY_NORMALIZATION_V1302_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v13.0.2 division normalization run was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$AllocationFolder = Join-Path $RunFolder "allocation"

Write-Host ("Opening: {0}" -f $AllocationFolder) -ForegroundColor Cyan
Invoke-Item $AllocationFolder
