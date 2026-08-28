$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "backend\.venv\Scripts\python.exe"
$Profile = Join-Path $Root "data\workforce_profile.json"
$Models = Join-Path $Root "models"
$Backup = Join-Path $Models "june-sample-backup"

if (-not (Test-Path $Profile)) {
    throw "The full Clarendon profile is missing from data\workforce_profile.json."
}

New-Item -ItemType Directory -Force $Backup | Out-Null
foreach ($Name in @("maskable_ppo_allocator.zip", "training_metrics.json")) {
    $Current = Join-Path $Models $Name
    if (Test-Path $Current) {
        Move-Item $Current (Join-Path $Backup $Name) -Force
    }
}
if (Test-Path (Join-Path $Models "candidates")) {
    $CandidateBackup = Join-Path $Backup "candidates"
    if (-not (Test-Path $CandidateBackup)) {
        Move-Item (Join-Path $Models "candidates") $CandidateBackup
    }
}

if (Test-Path $Python) {
    & $Python (Join-Path $Root "scripts\check_profile.py") --require-full
} else {
    py -3.12 (Join-Path $Root "scripts\check_profile.py") --require-full
}
if ($LASTEXITCODE -ne 0) {
    throw "Full Clarendon profile validation failed."
}

Write-Host "Full Clarendon profile is active." -ForegroundColor Green
Write-Host "Old June-sample models were moved to models\june-sample-backup." -ForegroundColor Yellow
Write-Host "Next: .\train_gpu_windows.ps1 -Timesteps 20000" -ForegroundColor Green
