$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v13_0_1\named_plucker_allocation\create_named_plucker_allocation_v1301.py"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_1\named_plucker_allocation_runs"

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$LogPath = Join-Path $OutputRoot ("named_plucker_allocation_kg_repair_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force

try {
    Write-Host "Starting named plucker allocation kg repair v13.0.1..." -ForegroundColor Cyan
    Write-Host "This repairs the blank crop and capacity columns in v13.0.0."
    Write-Host "Source mappings:"
    Write-Host "  target_crop_kg -> field_crop_kg"
    Write-Host "  expected_productivity_kg -> plucker_capacity_kg"
    Write-Host "  field_assigned_capacity_kg -> field_assigned_capacity_kg"
    Write-Host "All supervisor decisions remain ACCEPT for simulation only."
    Write-Host "No employee notification or live deployment will run."

    & py -3.12 $PythonScript `
        --project-root $ProjectRoot `
        --output-root $OutputRoot

    if ($LASTEXITCODE -ne 0) {
        throw "Named plucker allocation kg repair returned exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Named allocation kg repair completed." -ForegroundColor Green
    Write-Host "Run .\CHECK_NAMED_PLUCKER_ALLOCATION_v13.0.1.ps1"
    Write-Host "Run .\OPEN_NAMED_PLUCKER_ALLOCATION_v13.0.1.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
