$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$python = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Run RUN_FIRST_TIME.bat first." }
& $python "scripts\benchmark_selective_hybrid.py" --full-episodes 80 --extreme-episodes 40
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
