$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v11_0_1\movement_audit_fallback_repair\run_movement_audit_fallback_repair_v1101.py"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v11_0_1\movement_audit_fallback_repair_runs"

& py -3.12 -c "import torch; print('Python 3.12 PyTorch:', torch.__version__); print('CUDA:', torch.cuda.is_available())"

if ($LASTEXITCODE -ne 0) {
    throw "Python 3.12 with PyTorch is required."
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$LogPath = Join-Path $OutputRoot ("movement_audit_repair_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force

try {
    Write-Host "Starting movement audit and fallback repair v11.0.1..." -ForegroundColor Cyan
    Write-Host "Accepted environment actions will be used as the authoritative move count."
    Write-Host "Five estate-scenario fallback rules will be retained."
    Write-Host "Thirteen exact replay-case fallback rules will be added."
    Write-Host "All 396 routed cases will be recalculated."
    Write-Host "No live employee assignment will run."

    & py -3.12 $PythonScript `
        --project-root $ProjectRoot `
        --output-root $OutputRoot `
        --max-moves 5 `
        --max-actions 100 `
        --hybrid-ratio 0.95

    if ($LASTEXITCODE -ne 0) {
        throw "Movement audit and repair returned exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Movement audit and fallback repair completed." -ForegroundColor Green
    Write-Host "Run .\CHECK_MOVEMENT_AUDIT_REPAIR_v11.0.1.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
