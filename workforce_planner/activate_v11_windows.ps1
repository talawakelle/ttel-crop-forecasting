Write-Host "This release uses activate_v12_windows.ps1." -ForegroundColor Yellow
& (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "activate_v12_windows.ps1")
