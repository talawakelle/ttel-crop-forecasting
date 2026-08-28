$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v13_0_4\code_only_division_normalization\code_only_division_normalization_v1304.py"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_4\code_only_division_normalization_runs"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$LogPath = Join-Path $OutputRoot ("code_only_division_normalization_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force

try {
    Write-Host "Starting code-only division normalization v13.0.4..." -ForegroundColor Cyan
    Write-Host "Official long division names are not required."
    Write-Host "The latest v13.0.3 or v13.0.2 allocation preview will be used."
    Write-Host "Official assigned division codes will be collected at field-context level."
    Write-Host "Employee home codes remain historical context until supervisor verification."
    Write-Host "No employee notification or live allocation will run."

    & py -3.12 $PythonScript `
        --project-root $ProjectRoot `
        --output-root $OutputRoot

    if ($LASTEXITCODE -ne 0) {
        throw "Code-only division normalization returned exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Code-only division evidence pack created." -ForegroundColor Green
    Write-Host "Run .\CHECK_CODE_ONLY_DIVISION_NORMALIZATION_v13.0.4.ps1"
    Write-Host "Run .\OPEN_CODE_ONLY_DIVISION_EVIDENCE_v13.0.4.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
