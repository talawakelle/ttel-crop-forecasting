$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PortalRoot = Join-Path $ProjectRoot "portal"

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js 22 or later is required. Install Node.js and reopen VS Code."
}

$NodeMajor = [int]((node --version).TrimStart('v').Split('.')[0])
if ($NodeMajor -lt 22) {
    throw "Node.js 22 or later is required. Current version: $(node --version)"
}

if (-not (Test-Path (Join-Path $PortalRoot "data\portal.db"))) {
    Write-Host "Creating the 33 estate-manager accounts..." -ForegroundColor Cyan
    Push-Location $PortalRoot
    try { npm run setup } finally { Pop-Location }
}

Write-Host "Starting TTE Integrated Crop, GAP and Workforce Planning at http://127.0.0.1:8080" -ForegroundColor Green
Push-Location $PortalRoot
try { npm start } finally { Pop-Location }
