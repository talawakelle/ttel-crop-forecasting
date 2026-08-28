$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v12_0_1\supervisor_shadow_review\supervisor_shadow_review_v1201.py"
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v12_0_1\supervisor_shadow_review_runs"
$Pointer = Join-Path $RunRoot "LATEST_SUPERVISOR_SHADOW_REVIEW_V1201_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v12.0.1 supervisor shadow review pack was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()

& py -3.12 $PythonScript --validate-run $RunFolder

if ($LASTEXITCODE -ne 0) {
    throw "Supervisor shadow review validation returned exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Run .\CHECK_SUPERVISOR_SHADOW_REVIEW_v12.0.1.ps1" -ForegroundColor Cyan
