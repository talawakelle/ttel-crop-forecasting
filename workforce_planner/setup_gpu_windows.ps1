$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Python = Join-Path $Backend ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Host "Creating the Python 3.12 environment..." -ForegroundColor Cyan
    py -3.12 -m venv (Join-Path $Backend ".venv")
}

Write-Host "Installing project packages..." -ForegroundColor Cyan
& $Python -m pip install --upgrade pip
& $Python -m pip install --timeout 3600 -r (Join-Path $Backend "requirements.txt")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$CudaReady = & $Python -c "import torch; print('1' if torch.cuda.is_available() else '0')"
if ($CudaReady.Trim() -ne "1") {
    Write-Host "Replacing CPU PyTorch with the official CUDA 12.6 build..." -ForegroundColor Cyan
    & $Python -m pip uninstall -y torch
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Python -m pip install --no-cache-dir --timeout 3600 torch --index-url https://download.pytorch.org/whl/cu126
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    Write-Host "CUDA-enabled PyTorch is already installed." -ForegroundColor Green
}

Write-Host "Checking the NVIDIA GPU..." -ForegroundColor Cyan
& $Python (Join-Path $Root "scripts\check_gpu.py")
if ($LASTEXITCODE -ne 0) {
    throw "GPU setup failed. Restart Windows after updating the NVIDIA driver, then run this script again."
}

Write-Host "GPU setup complete." -ForegroundColor Green
Write-Host "Best next command: .\TRAIN_HYBRID_RL_GPU.bat" -ForegroundColor Green
Write-Host "The older TRAIN_DYNAMIC_RL_GPU.bat is retained only for comparison research." -ForegroundColor Yellow
