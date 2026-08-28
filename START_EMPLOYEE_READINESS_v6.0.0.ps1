$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

$ProductivityRoot = Join-Path $ProjectRoot "workforce_planner\v2\model_candidates"
$ProductivityRun = Get-ChildItem $ProductivityRoot -Directory `
    -Filter "productivity_gpu_*" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if ($null -eq $ProductivityRun) {
    throw "No productivity_gpu run was found under $ProductivityRoot"
}

$PlanningPointer = Join-Path $ProjectRoot "workforce_planner\v5\final_method_gate_runs_v503\LATEST_BEST_AVAILABLE_PLANNING_RUN.txt"
if (-not (Test-Path $PlanningPointer)) {
    throw "Final v5.0.3 planning pointer is missing: $PlanningPointer"
}
$PlanningRun = (Get-Content $PlanningPointer -Raw).Trim()

$PythonScript = Join-Path $ProjectRoot "workforce_planner\v6\employee_readiness\build_employee_readiness_v600.py"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v6\employee_readiness_runs"

if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCommand = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCommand = "python"
} else {
    throw "Python was not found."
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$LogPath = Join-Path $OutputRoot ("employee_readiness_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force
try {
    Write-Host "Starting employee readiness layer v6.0.0..." -ForegroundColor Cyan
    Write-Host "Productivity run: $($ProductivityRun.FullName)"
    Write-Host "Planning run: $PlanningRun"
    Write-Host "This creates employee registers, templates and candidate matrices."
    Write-Host "No CP-SAT allocation or RL policy will run."

    & $PythonCommand $PythonScript `
        --productivity-run $ProductivityRun.FullName `
        --planning-run $PlanningRun `
        --output-root $OutputRoot

    if ($LASTEXITCODE -ne 0) {
        throw "Employee readiness build returned exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Employee readiness inputs completed." -ForegroundColor Green
    Write-Host "Run .\CHECK_EMPLOYEE_READINESS_v6.0.0.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
