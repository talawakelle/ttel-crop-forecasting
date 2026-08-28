$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v12\supervisor_shadow_review\supervisor_shadow_review_v1200.py"
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v12\supervisor_shadow_review_runs"
$Pointer = Join-Path $RunRoot "LATEST_SUPERVISOR_SHADOW_REVIEW_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No supervisor shadow review pack was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()

& py -3.12 $PythonScript --validate-run $RunFolder

if ($LASTEXITCODE -ne 0) {
    throw "Supervisor shadow review validation returned exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Run .\CHECK_SUPERVISOR_SHADOW_REVIEW_v12.0.0.ps1" -ForegroundColor Cyan
