$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$python = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Python environment missing. Run RUN_FIRST_TIME.bat first."
}
& $python "scripts\evaluate_dynamic_rl.py" --device auto --episodes 240 --stress-episodes 120

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
