$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v11_0_2\complete_fallback_routing_repair\run_complete_fallback_routing_repair_v1102.py"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v11_0_2\complete_fallback_routing_repair_runs"

& py -3.12 -c "import torch; print('Python 3.12 PyTorch:', torch.__version__); print('CUDA:', torch.cuda.is_available())"

if ($LASTEXITCODE -ne 0) {
    throw "Python 3.12 with PyTorch is required."
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$LogPath = Join-Path $OutputRoot ("complete_fallback_repair_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force

try {
    Write-Host "Starting complete fallback routing repair v11.0.2..." -ForegroundColor Cyan
    Write-Host "The trained RL model will not be retrained."
    Write-Host "Five estate-scenario fallback rules will be retained."
    Write-Host "Twenty-eight exact scenario-estate-shock fallback rules will be applied."
    Write-Host "All 396 routed cases will be recalculated using audited accepted moves."
    Write-Host "No live employee assignment will run."

    & py -3.12 $PythonScript `
        --project-root $ProjectRoot `
        --output-root $OutputRoot `
        --max-moves 5 `
        --max-actions 100 `
        --hybrid-ratio 0.95

    if ($LASTEXITCODE -ne 0) {
        throw "Complete fallback repair returned exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Complete fallback routing repair completed." -ForegroundColor Green
    Write-Host "Run .\CHECK_COMPLETE_FALLBACK_REPAIR_v11.0.2.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
