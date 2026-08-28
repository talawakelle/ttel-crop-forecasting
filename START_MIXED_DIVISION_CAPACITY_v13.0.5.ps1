$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v13_0_5\mixed_division_capacity\mixed_division_capacity_v1305.py"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_5\mixed_division_capacity_runs"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$LogPath = Join-Path $OutputRoot ("mixed_division_capacity_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force

try {
    Write-Host "Starting mixed-division capacity-safe allocation v13.0.5..." -ForegroundColor Cyan
    Write-Host "One employee may have several field or division rows."
    Write-Host "The total allocated capacity must not exceed daily capacity."
    Write-Host "Exact duplicate employee-division-field rows remain invalid."
    Write-Host "Mixed-division assignments require supervisor confirmation."
    Write-Host "TLD and all employee home codes remain unverified."
    Write-Host "No employee notification or live allocation will run."

    & py -3.12 $PythonScript `
        --project-root $ProjectRoot `
        --output-root $OutputRoot

    if ($LASTEXITCODE -ne 0) {
        throw "Mixed-division capacity pack returned exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Mixed-division capacity review pack created." -ForegroundColor Green
    Write-Host "Run .\CHECK_MIXED_DIVISION_CAPACITY_v13.0.5.ps1"
    Write-Host "Run .\OPEN_MIXED_DIVISION_CAPACITY_REVIEW_v13.0.5.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
