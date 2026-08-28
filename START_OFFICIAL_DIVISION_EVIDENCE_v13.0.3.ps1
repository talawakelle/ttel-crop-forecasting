$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v13_0_3\official_division_evidence\official_division_evidence_v1303.py"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_3\official_division_evidence_runs"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$LogPath = Join-Path $OutputRoot ("official_division_evidence_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force

try {
    Write-Host "Starting official division evidence intake v13.0.3..." -ForegroundColor Cyan
    Write-Host "The latest v13.0.2 mapping and allocation preview will be used."
    Write-Host "The template supports one division code mapping to several valid divisions."
    Write-Host "System suggestions will not be treated as official evidence."
    Write-Host "No employee notification or live allocation will run."

    & py -3.12 $PythonScript `
        --project-root $ProjectRoot `
        --output-root $OutputRoot

    if ($LASTEXITCODE -ne 0) {
        throw "Official division evidence intake returned exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Official evidence intake pack created." -ForegroundColor Green
    Write-Host "Run .\CHECK_OFFICIAL_DIVISION_EVIDENCE_v13.0.3.ps1"
    Write-Host "Run .\OPEN_OFFICIAL_DIVISION_EVIDENCE_v13.0.3.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
