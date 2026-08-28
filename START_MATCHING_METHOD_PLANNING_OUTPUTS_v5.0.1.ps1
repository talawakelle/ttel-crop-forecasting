$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v5\best_available_planning_v501\build_best_available_outputs_v501.py"
$V4Root = Join-Path $ProjectRoot "workforce_planner\v4\daily_hierarchy_runs"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v5\best_available_planning_runs_v501"

if (-not (Test-Path $PythonScript)) {
    throw "Matching-method planning script is missing: $PythonScript"
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
$LogPath = Join-Path $OutputRoot ("matching_method_planning_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force
try {
    Write-Host "Starting corrected existing-data planning v5.0.1..." -ForegroundColor Cyan
    Write-Host "Bambarakelly, Tillicoultry and EildonHall: MATCHED ESTATE METHOD."
    Write-Host "All other estates: EXISTING PLANNING METHODS."
    Write-Host "No portal, CP-SAT, allocator or RL policy will change."

    & $PythonCommand $PythonScript `
        --v4-root $V4Root `
        --output-root $OutputRoot

    if ($LASTEXITCODE -ne 0) {
        throw "Corrected matching-method planning returned exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Corrected matching-method outputs completed." -ForegroundColor Green
    Write-Host "Run .\CHECK_MATCHING_METHOD_PLANNING_OUTPUTS_v5.0.1.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
