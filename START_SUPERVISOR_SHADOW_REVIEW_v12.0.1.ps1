$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v12_0_1\supervisor_shadow_review\supervisor_shadow_review_v1201.py"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v12_0_1\supervisor_shadow_review_runs"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$LogPath = Join-Path $OutputRoot ("supervisor_shadow_review_identity_repair_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force

try {
    Write-Host "Starting supervisor shadow review identity repair v12.0.1..." -ForegroundColor Cyan
    Write-Host "Employee identity will use estate plus employee_id."
    Write-Host "All 23,043 estate-employee records must be preserved."
    Write-Host "Historical records will not be treated as current attendance, leave, fitness or availability."
    Write-Host "No employee notification, payroll connection or live assignment will run."

    & py -3.12 $PythonScript `
        --project-root $ProjectRoot `
        --output-root $OutputRoot

    if ($LASTEXITCODE -ne 0) {
        throw "Supervisor shadow review identity repair returned exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Identity-repaired supervisor review pack created." -ForegroundColor Green
    Write-Host "Run .\OPEN_SUPERVISOR_SHADOW_REVIEW_v12.0.1.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
