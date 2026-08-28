$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v12\supervisor_shadow_review_runs"
$Pointer = Join-Path $RunRoot "LATEST_SUPERVISOR_SHADOW_REVIEW_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No supervisor shadow review pack was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$InputFolder = Join-Path $RunFolder "review_input"

Write-Host ("Opening: {0}" -f $InputFolder) -ForegroundColor Cyan
Invoke-Item $InputFolder
