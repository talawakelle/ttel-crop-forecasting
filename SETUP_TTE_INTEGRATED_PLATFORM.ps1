[CmdletBinding()]
param(
    [switch]$IncludeClarendonPilot
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

& (Join-Path $ProjectRoot "setup_windows.ps1")

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js 22 or later is required for the authenticated portal."
}
$NodeMajor = [int]((node --version).TrimStart('v').Split('.')[0])
if ($NodeMajor -lt 22) {
    throw "Node.js 22 or later is required. Current version: $(node --version)"
}

if (-not (Test-Path (Join-Path $ProjectRoot "portal\data\portal.db"))) {
    Push-Location (Join-Path $ProjectRoot "portal")
    try { npm run setup } finally { Pop-Location }
}

if ($IncludeClarendonPilot) {
    $PilotSetup = Join-Path $ProjectRoot "workforce_planner\setup_windows.ps1"
    if (-not (Test-Path $PilotSetup)) {
        throw "Clarendon workforce pilot was not found: $PilotSetup"
    }
    & $PilotSetup
}

Write-Host "Integrated platform setup completed." -ForegroundColor Green
Write-Host "Start it with .\START_TTE_INTEGRATED_PLATFORM.ps1" -ForegroundColor Cyan
