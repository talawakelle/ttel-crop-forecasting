$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v5\final_method_gate_v503\build_final_method_gate_outputs_v503.py"
$V4Root = Join-Path $ProjectRoot "workforce_planner\v4\daily_hierarchy_runs"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v5\final_method_gate_runs_v503"

if (-not (Test-Path $PythonScript)) {
    throw "Final method-gate script is missing: $PythonScript"
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
$LogPath = Join-Path $OutputRoot ("final_method_gate_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force
try {
    Write-Host "Starting final method-gated planning v5.0.3..." -ForegroundColor Cyan
    Write-Host "Bambarakelly, Tillicoultry and EildonHall: compare original vs pooled technical method."
    Write-Host "The lower-WAPE method is selected separately for each estate."
    Write-Host "All other estates continue their existing planning methods."
    Write-Host "No matched donor estates, portal, CP-SAT, allocator or RL changes."

    & $PythonCommand $PythonScript `
        --v4-root $V4Root `
        --output-root $OutputRoot

    if ($LASTEXITCODE -ne 0) {
        throw "Final method-gated planning returned exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Final method-gated outputs completed." -ForegroundColor Green
    Write-Host "Run .\CHECK_FINAL_METHOD_GATE_PLANNING_v5.0.3.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
