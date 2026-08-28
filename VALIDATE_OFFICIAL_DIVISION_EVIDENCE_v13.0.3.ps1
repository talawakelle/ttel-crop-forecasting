$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v13_0_3\official_division_evidence\official_division_evidence_v1303.py"
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_3\official_division_evidence_runs"
$Pointer = Join-Path $RunRoot "LATEST_OFFICIAL_DIVISION_EVIDENCE_V1303_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v13.0.3 official evidence run was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()

& py -3.12 $PythonScript --validate-run $RunFolder

if ($LASTEXITCODE -ne 0) {
    throw "Official division evidence validation returned exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Run .\CHECK_OFFICIAL_DIVISION_EVIDENCE_v13.0.3.ps1" -ForegroundColor Cyan
