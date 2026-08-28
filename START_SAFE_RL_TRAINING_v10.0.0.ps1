$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvironmentPointer = Join-Path $ProjectRoot "workforce_planner\v9\rl_environment_runs\LATEST_RL_ENVIRONMENT_DESIGN_RUN.txt"

if (-not (Test-Path $EnvironmentPointer)) {
    throw "Latest RL environment pointer was not found: $EnvironmentPointer"
}

$EnvironmentRun = (Get-Content $EnvironmentPointer -Raw).Trim()
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v10\safe_rl_training\train_safe_rl_policy_v1000.py"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v10\safe_rl_training_runs"

$UsePy312 = $false
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.12 -c "import torch; print('Python 3.12 PyTorch:', torch.__version__); print('CUDA:', torch.cuda.is_available())"
    if ($LASTEXITCODE -eq 0) {
        $UsePy312 = $true
    }
}

if (-not $UsePy312) {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "Python was not found."
    }
    & python -c "import torch; print('PyTorch:', torch.__version__); print('CUDA:', torch.cuda.is_available())"
    if ($LASTEXITCODE -ne 0) {
        throw "PyTorch is missing. Use the Python 3.12 environment where CUDA PyTorch is installed."
    }
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$LogPath = Join-Path $OutputRoot ("safe_rl_training_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force
try {
    Write-Host "Starting safe development RL training v10.0.0..." -ForegroundColor Cyan
    Write-Host "Training shocks: SHOCK_01 to SHOCK_04."
    Write-Host "Validation shock: SHOCK_05."
    Write-Host "No-shock baseline safety test: SHOCK_00."
    Write-Host "The protected hybrid policy falls back to greedy."
    Write-Host "No live deployment will run."

    if ($UsePy312) {
        & py -3.12 $PythonScript `
            --environment-run $EnvironmentRun `
            --output-root $OutputRoot `
            --warmup-epochs 2 `
            --training-epochs 3 `
            --max-moves 5 `
            --max-actions 100
    } else {
        & python $PythonScript `
            --environment-run $EnvironmentRun `
            --output-root $OutputRoot `
            --warmup-epochs 2 `
            --training-epochs 3 `
            --max-moves 5 `
            --max-actions 100
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Safe RL training returned exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Safe development RL training completed." -ForegroundColor Green
    Write-Host "Run .\CHECK_SAFE_RL_TRAINING_v10.0.0.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
