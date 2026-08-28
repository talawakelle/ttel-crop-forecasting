$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v13\named_plucker_allocation\create_named_plucker_allocation_v1300.py"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v13\named_plucker_allocation_runs"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$LogPath = Join-Path $OutputRoot ("named_plucker_allocation_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force

try {
    Write-Host "Starting simulation named plucker allocation v13.0.0..." -ForegroundColor Cyan
    Write-Host "The latest passed CP-SAT named assignment output will be used."
    Write-Host "All supervisor decisions will be labelled ACCEPT for simulation only."
    Write-Host "This is not proof of actual supervisor approval."
    Write-Host "Attendance, leave, fitness and restrictions remain unverified."
    Write-Host "No employee notification or live deployment will run."

    & py -3.12 $PythonScript `
        --project-root $ProjectRoot `
        --output-root $OutputRoot

    if ($LASTEXITCODE -ne 0) {
        throw "Named plucker allocation returned exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Simulation named plucker allocation created." -ForegroundColor Green
    Write-Host "Run .\CHECK_NAMED_PLUCKER_ALLOCATION_v13.0.0.ps1"
    Write-Host "Run .\OPEN_NAMED_PLUCKER_ALLOCATION_v13.0.0.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
