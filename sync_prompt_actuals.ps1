param(
    [Parameter(Mandatory = $true)]
    [string]$SourcePath
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ResolvedSource = (Resolve-Path $SourcePath).Path

Push-Location $ProjectRoot
try {
    $VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path $VenvPython) {
        & $VenvPython import_prompt_actuals.py --source $ResolvedSource
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python import_prompt_actuals.py --source $ResolvedSource
    }
    else {
        throw "Python was not found. Run .\setup_windows.ps1 first."
    }
    Write-Host "PROMPT daily actuals imported successfully. The portal will refresh automatically." -ForegroundColor Green
} finally {
    Pop-Location
}
