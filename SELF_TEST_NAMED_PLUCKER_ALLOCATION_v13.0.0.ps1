$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v13\named_plucker_allocation\create_named_plucker_allocation_v1300.py"

& py -3.12 $PythonScript --self-test

if ($LASTEXITCODE -ne 0) {
    throw "Named plucker allocation self-test failed."
}
