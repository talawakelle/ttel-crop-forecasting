$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v11\protected_shadow_backtest\run_protected_shadow_backtest_v1100.py"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v11\protected_shadow_backtest_runs"

$UsePy312 = $false

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.12 -c "import torch; print('Python 3.12 PyTorch:', torch.__version__); print('CUDA:', torch.cuda.is_available())"
    if ($LASTEXITCODE -eq 0) {
        $UsePy312 = $true
    }
}

if (-not $UsePy312) {
    throw "Python 3.12 with PyTorch is required."
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$LogPath = Join-Path $OutputRoot ("protected_shadow_backtest_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force

try {
    Write-Host "Starting protected shadow backtest v11.0.0..." -ForegroundColor Cyan
    Write-Host "Five reviewed estate-scenarios will use greedy fallback."
    Write-Host "The remaining estate-scenarios will use protected hybrid RL."
    Write-Host "All six deterministic shock sets will be replayed."
    Write-Host "This is simulation-only. No live employee assignment will run."

    & py -3.12 $PythonScript `
        --project-root $ProjectRoot `
        --output-root $OutputRoot `
        --max-moves 5 `
        --max-actions 100 `
        --hybrid-ratio 0.95 `
        --required-all-case-noninferiority-pct 95.0

    if ($LASTEXITCODE -ne 0) {
        throw "Protected shadow backtest returned exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Protected shadow backtest completed." -ForegroundColor Green
    Write-Host "Run .\CHECK_PROTECTED_SHADOW_BACKTEST_v11.0.0.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
