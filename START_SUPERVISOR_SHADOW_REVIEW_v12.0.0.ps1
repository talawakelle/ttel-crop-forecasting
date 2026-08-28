$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v12\supervisor_shadow_review\supervisor_shadow_review_v1200.py"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v12\supervisor_shadow_review_runs"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$LogPath = Join-Path $OutputRoot ("supervisor_shadow_review_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force

try {
    Write-Host "Starting supervisor shadow review pack v12.0.0..." -ForegroundColor Cyan
    Write-Host "This stage creates review templates and does not start live allocation."
    Write-Host "Supervisors must verify actual attendance, leave, fitness, field access and movement restrictions."
    Write-Host "No employee notification, payroll connection or live assignment will run."

    & py -3.12 $PythonScript `
        --project-root $ProjectRoot `
        --output-root $OutputRoot

    if ($LASTEXITCODE -ne 0) {
        throw "Supervisor shadow review pack returned exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Supervisor shadow review pack created." -ForegroundColor Green
    Write-Host "Run .\OPEN_SUPERVISOR_SHADOW_REVIEW_v12.0.0.ps1"
    Write-Host "After completing the files, run .\VALIDATE_SUPERVISOR_SHADOW_REVIEW_v12.0.0.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
