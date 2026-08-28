param(
    [Parameter(Mandatory = $false)]
    [string]$CropRoot = "C:\Users\user\Desktop\HG 2",

    [Parameter(Mandatory = $false)]
    [int]$ForecastDays = 28,

    [Parameter(Mandatory = $false)]
    [string]$ForecastStart = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ProjectRoot "workforce_planner\v4\daily_hierarchy\build_daily_hierarchy.py"
$IdentityRegistry = Join-Path $ProjectRoot "workforce_planner\v4\daily_hierarchy\verified_identity_registry.csv"
$AuditRoot = Join-Path $ProjectRoot "workforce_planner\v3\data_audit_runs"
$OutputRoot = Join-Path $ProjectRoot "workforce_planner\v4\daily_hierarchy_runs"

if (-not (Test-Path $PythonScript)) {
    throw "Daily hierarchy script is missing: $PythonScript"
}
if (-not (Test-Path $IdentityRegistry)) {
    throw "Verified identity registry is missing: $IdentityRegistry"
}
if (-not (Test-Path $CropRoot)) {
    throw "Crop archive folder does not exist: $CropRoot"
}
if (-not (Test-Path (Join-Path $AuditRoot "LATEST_DATA_AUDIT.txt"))) {
    throw "The corrected v3.0.1 audit must be completed first."
}

if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCommand = "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCommand = "python"
} else {
    throw "Python was not found."
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$LogPath = Join-Path $OutputRoot ("daily_hierarchy_launcher_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogPath -Force
try {
    Write-Host "Starting 33-estate daily hierarchy development candidate..." -ForegroundColor Cyan
    Write-Host "Stage: estate daily candidate -> division share -> field share -> reconciliation."
    Write-Host "No live portal, allocator or RL policy will be changed."
    Write-Host "Forecast days: $ForecastDays"

    $Arguments = @(
        $PythonScript,
        "--crop-root", $CropRoot,
        "--audit-root", $AuditRoot,
        "--identity-registry", $IdentityRegistry,
        "--output-root", $OutputRoot,
        "--expected-estates", "33",
        "--forecast-days", "$ForecastDays"
    )
    if (-not [string]::IsNullOrWhiteSpace($ForecastStart)) {
        $Arguments += @("--forecast-start", $ForecastStart)
    }

    & $PythonCommand @Arguments

    if ($LASTEXITCODE -ne 0) {
        throw "Daily hierarchy candidate returned exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Daily hierarchy candidate completed." -ForegroundColor Green
    Write-Host "Run .\CHECK_DAILY_HIERARCHY_CANDIDATE_v4.0.0.ps1"
}
finally {
    Stop-Transcript | Out-Null
}
