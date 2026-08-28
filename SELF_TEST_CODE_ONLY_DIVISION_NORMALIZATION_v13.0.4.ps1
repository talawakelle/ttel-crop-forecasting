$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v13_0_4\code_only_division_normalization\code_only_division_normalization_v1304.py"

& py -3.12 $PythonScript --self-test

if ($LASTEXITCODE -ne 0) {
    throw "Code-only division normalization self-test failed."
}
