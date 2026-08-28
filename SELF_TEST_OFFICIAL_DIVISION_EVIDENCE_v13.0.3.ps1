$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v13_0_3\official_division_evidence\official_division_evidence_v1303.py"

& py -3.12 $PythonScript --self-test

if ($LASTEXITCODE -ne 0) {
    throw "Official division evidence self-test failed."
}
