$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$python = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "GPU environment missing. Run setup_gpu_windows.ps1 first."
}
& $python "scripts\train_dynamic_rl.py" `
    --device cuda `
    --candidate-seeds 3 `
    --env-count 4 `
    --easy-steps 150000 `
    --medium-steps 250000 `
    --full-steps 400000 `
    --mixed-steps 300000 `
    --validation-days 120 `
    --test-days 180 `
    --evaluation-episodes 240 `
    --stress-episodes 120

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
