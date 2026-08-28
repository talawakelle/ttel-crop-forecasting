$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v5\pooled_hierarchical_planning_v502\build_pooled_hierarchical_outputs_v502.py"
$V4Root = Join-Path $ProjectRoot "workforce_planner\v4\daily_hierarchy_runs"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v5\pooled_hierarchical_planning_runs_v502"

if (-not (Test-Path $PythonScript)) {
    throw "Pooled hierarchical planning script is missing: $PythonScript"
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
$LogPath = Join-Path $OutputRoot ("pooled_hierarchical_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force
try {
    Write-Host "Starting corrected planning v5.0.2..." -ForegroundColor Cyan
    Write-Host "Bambarakelly, Tillicoultry and EildonHall: POOLED HIERARCHICAL TECHNICAL METHOD."
    Write-Host "All other estates: CONTINUE EXISTING PLANNING METHODS."
    Write-Host "This does not use matched donor estates."
    Write-Host "No portal, CP-SAT, allocator or RL policy will change."

    & $PythonCommand $PythonScript `
        --v4-root $V4Root `
        --output-root $OutputRoot

    if ($LASTEXITCODE -ne 0) {
        throw "Pooled hierarchical planning returned exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Corrected technical-method outputs completed." -ForegroundColor Green
    Write-Host "Run .\CHECK_POOLED_HIERARCHICAL_PLANNING_v5.0.2.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
