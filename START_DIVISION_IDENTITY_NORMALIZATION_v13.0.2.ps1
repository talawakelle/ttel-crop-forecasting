$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v13_0_2\division_identity_normalization\division_identity_normalization_v1302.py"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_2\division_identity_normalization_runs"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$LogPath = Join-Path $OutputRoot ("division_identity_normalization_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force

try {
    Write-Host "Starting division identity normalization v13.0.2..." -ForegroundColor Cyan
    Write-Host "The latest v13.0.1 named allocation will be used."
    Write-Host "Short home-division codes will be matched to full division names."
    Write-Host "Suggestions will be generated, but no manager confirmation will be auto-filled."
    Write-Host "No employee notification or live allocation will run."

    & py -3.12 $PythonScript `
        --project-root $ProjectRoot `
        --output-root $OutputRoot

    if ($LASTEXITCODE -ne 0) {
        throw "Division identity normalization returned exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Division mapping review pack created." -ForegroundColor Green
    Write-Host "Run .\CHECK_DIVISION_IDENTITY_NORMALIZATION_v13.0.2.ps1"
    Write-Host "Run .\OPEN_DIVISION_MAPPING_REVIEW_v13.0.2.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
