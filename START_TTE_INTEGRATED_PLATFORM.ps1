$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "TTE Integrated Crop, GAP and Workforce Planning" -ForegroundColor Green
Write-Host "Manager access remains restricted to one estate per secure link." -ForegroundColor Cyan
& (Join-Path $ProjectRoot "start_portal.ps1")

