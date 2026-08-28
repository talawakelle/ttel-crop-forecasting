$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v5\best_available_planning\build_best_available_outputs.py"
$V4Root = Join-Path $ProjectRoot "workforce_planner\v4\daily_hierarchy_runs"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v5\best_available_planning_runs"

if (-not (Test-Path $PythonScript)) {
    throw "Best-available planning script is missing: $PythonScript"
}
if (-not (Test-Path (Join-Path $V4Root "LATEST_DAILY_HIERARCHY_RUN.txt"))) {
    throw "The v4 daily hierarchy candidate must be completed first."
}

if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCommand = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCommand = "python"
} else {
    throw "Python was not found."
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$LogPath = Join-Path $OutputRoot ("best_available_planning_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force
try {
    Write-Host "Starting best-available planning with the existing data only..." -ForegroundColor Cyan
    Write-Host "Method: risk-gated ensemble + realistic active-field schedule + conservative productivity."
    Write-Host "Outputs include estate, division and field crop plus plucker-assignment demand."
    Write-Host "No live portal, CP-SAT or RL policy will change."

    & $PythonCommand $PythonScript `
        --v4-root $V4Root `
        --output-root $OutputRoot

    if ($LASTEXITCODE -ne 0) {
        throw "Best-available planning returned exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Best-available outputs completed." -ForegroundColor Green
    Write-Host "Run .\CHECK_BEST_AVAILABLE_PLANNING_OUTPUTS_v5.0.0.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
