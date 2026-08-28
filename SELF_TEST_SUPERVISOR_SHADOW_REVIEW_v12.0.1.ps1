$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v12_0_1\supervisor_shadow_review\supervisor_shadow_review_v1201.py"

& py -3.12 $PythonScript --self-test

if ($LASTEXITCODE -ne 0) {
    throw "Supervisor shadow review identity repair self-test failed."
}
