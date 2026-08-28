[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourcePath
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Importer = Join-Path $ProjectRoot "sync_prompt_actuals.ps1"

if (-not (Test-Path $SourcePath)) {
    throw "PROMPT output was not found: $SourcePath"
}

& $Importer -SourcePath $SourcePath
Write-Host "Actual crop is refreshed. Current-practice forecasts remain unchanged until crop models are retrained." -ForegroundColor Yellow
Write-Host "Restart is not required; reload the portal graph." -ForegroundColor Green

