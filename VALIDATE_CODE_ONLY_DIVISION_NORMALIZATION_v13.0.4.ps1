$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v13_0_4\code_only_division_normalization\code_only_division_normalization_v1304.py"
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_4\code_only_division_normalization_runs"
$Pointer = Join-Path $RunRoot "LATEST_CODE_ONLY_DIVISION_NORMALIZATION_V1304_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v13.0.4 code-only division run was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()

& py -3.12 $PythonScript --validate-run $RunFolder

if ($LASTEXITCODE -ne 0) {
    throw "Code-only division validation returned exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Run .\CHECK_CODE_ONLY_DIVISION_NORMALIZATION_v13.0.4.ps1" -ForegroundColor Cyan
