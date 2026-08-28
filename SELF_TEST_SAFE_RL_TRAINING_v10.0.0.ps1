$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v10\safe_rl_training\train_safe_rl_policy_v1000.py"

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.12 $PythonScript --self-test
    if ($LASTEXITCODE -eq 0) {
        exit 0
    }
}

python $PythonScript --self-test
