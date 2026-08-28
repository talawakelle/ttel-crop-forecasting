[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$CropRoot,

    [Parameter(Mandatory = $true)]
    [string]$TriWeather,

    [Parameter(Mandatory = $true)]
    [string]$PedroWeather,

    [ValidateRange(200, 20000)]
    [int]$Iterations = 3000,

    [switch]$WaitForCrop,
    [switch]$SkipSetup
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not ("TteWorkforceBatchExecutionState" -as [type])) {
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class TteWorkforceBatchExecutionState {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint esFlags);
}
"@
}
$ES_CONTINUOUS = [Convert]::ToUInt32("80000000", 16)
$ES_KEEP_AWAKE = [Convert]::ToUInt32("80000041", 16)
[TteWorkforceBatchExecutionState]::SetThreadExecutionState($ES_KEEP_AWAKE) | Out-Null

$Arguments = @{
    CropRoot = $CropRoot
    TriWeather = $TriWeather
    PedroWeather = $PedroWeather
    Iterations = $Iterations
}
if ($WaitForCrop) { $Arguments.WaitForCrop = $true }
if ($SkipSetup) { $Arguments.SkipSetup = $true }

try {
    & "$ProjectRoot\TRAIN_ALL_33_WORKFORCE_PRODUCTIVITY_GPU.ps1" @Arguments
}
finally {
    [TteWorkforceBatchExecutionState]::SetThreadExecutionState($ES_CONTINUOUS) | Out-Null
    Write-Host "Normal Windows sleep behaviour has been restored." -ForegroundColor Cyan
}
