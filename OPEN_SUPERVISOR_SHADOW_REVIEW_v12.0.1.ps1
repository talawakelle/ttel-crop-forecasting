$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v12_0_1\supervisor_shadow_review_runs"
$Pointer = Join-Path $RunRoot "LATEST_SUPERVISOR_SHADOW_REVIEW_V1201_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v12.0.1 supervisor shadow review pack was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$InputFolder = Join-Path $RunFolder "review_input"

Write-Host ("Opening: {0}" -f $InputFolder) -ForegroundColor Cyan
Invoke-Item $InputFolder
