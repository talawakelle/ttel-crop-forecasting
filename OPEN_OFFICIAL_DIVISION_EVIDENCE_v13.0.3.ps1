$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_3\official_division_evidence_runs"
$Pointer = Join-Path $RunRoot "LATEST_OFFICIAL_DIVISION_EVIDENCE_V1303_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v13.0.3 official evidence run was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$ReviewFolder = Join-Path $RunFolder "review_input"

Write-Host ("Opening: {0}" -f $ReviewFolder) -ForegroundColor Cyan
Invoke-Item $ReviewFolder
