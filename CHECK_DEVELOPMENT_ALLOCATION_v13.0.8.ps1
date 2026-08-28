$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunRoot = Join-Path $ProjectRoot "workforce_planner\v13_0_8\development_allocation_consolidation_runs"
$Pointer = Join-Path $RunRoot "LATEST_DEVELOPMENT_ALLOCATION_V1308_RUN.txt"

if (-not (Test-Path $Pointer)) {
    throw "No v13.0.8 development allocation run was found."
}

$RunFolder = (Get-Content $Pointer -Raw).Trim()
$Summary = Get-Content (Join-Path $RunFolder "run_summary.json") -Raw | ConvertFrom-Json

Write-Host ""
Write-Host "TTE development allocation consolidation v13.0.8" -ForegroundColor Cyan
Write-Host ("Run folder: {0}" -f $RunFolder)
Write-Host ("Status: {0}" -f $Summary.status)
Write-Host ("Allocation rows: {0}" -f $Summary.allocation_rows)
Write-Host ("EXPECTED primary rows: {0}" -f $Summary.expected_primary_rows)
Write-Host ("CONSERVATIVE backup rows: {0}" -f $Summary.conservative_backup_rows)
Write-Host ("Estates: {0}" -f $Summary.estate_count)
Write-Host ("Official field-code rows: {0}" -f $Summary.official_field_code_rows)
Write-Host ("Unresolved field-code rows: {0}" -f $Summary.official_field_code_unresolved_rows)
Write-Host ("Home-code exception assignment rows: {0}" -f $Summary.home_code_exception_assignment_rows)
Write-Host ("Home-code exception employees: {0}" -f $Summary.home_code_exception_employees)
Write-Host ("Cross-division exception rows: {0}" -f $Summary.cross_division_exception_rows)
Write-Host ("Duplicate assignment failures: {0}" -f $Summary.duplicate_assignment_failures)
Write-Host ("Safety-control failures: {0}" -f $Summary.safety_control_failures)
Write-Host ("Review gate: {0}" -f $Summary.review_gate)
Write-Host ("Live deployment started: {0}" -f $Summary.live_deployment_started)

Write-Host ""
Import-Csv (Join-Path $RunFolder "quality\development_allocation_gate.csv") |
    Format-Table -AutoSize

Write-Host ""
Write-Host "This output is for development and management simulation review only." -ForegroundColor Yellow
