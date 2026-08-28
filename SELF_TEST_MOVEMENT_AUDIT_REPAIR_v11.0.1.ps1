$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v11_0_1\movement_audit_fallback_repair\run_movement_audit_fallback_repair_v1101.py"

& py -3.12 $PythonScript --self-test

if ($LASTEXITCODE -ne 0) {
    throw "Movement audit repair self-test failed."
}
