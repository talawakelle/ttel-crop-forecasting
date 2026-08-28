$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_4\code_only_division_normalization_runs"
$Pointer = Join-Path $RunRoot "LATEST_CODE_ONLY_DIVISION_NORMALIZATION_V1304_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v13.0.4 code-only division run was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$ReviewFolder = Join-Path $RunFolder "review_input"

Write-Host ("Opening: {0}" -f $ReviewFolder) -ForegroundColor Cyan
Invoke-Item $ReviewFolder
