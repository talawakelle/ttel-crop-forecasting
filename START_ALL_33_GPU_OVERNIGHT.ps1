[CmdletBinding()]
param(
    [string]$CropRoot,
    [string[]]$TriWeather,
    [string[]]$PedroWeather,
    [switch]$SkipSetup
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Add-Type -AssemblyName System.Windows.Forms

function Select-InputFolder([string]$Description) {
    $Dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $Dialog.Description = $Description
    $Dialog.ShowNewFolderButton = $false
    if ($Dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
        throw "Folder selection was cancelled."
    }
    return $Dialog.SelectedPath
}

function Select-InputFiles([string]$Title, [bool]$MultiSelect) {
    $Dialog = New-Object System.Windows.Forms.OpenFileDialog
    $Dialog.Title = $Title
    $Dialog.Filter = "Excel workbooks (*.xlsx)|*.xlsx"
    $Dialog.Multiselect = $MultiSelect
    if ($Dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
        throw "File selection was cancelled."
    }
    return @($Dialog.FileNames)
}

if (-not $CropRoot) {
    $CropRoot = Select-InputFolder "Select the folder containing all 33 estate *_output ZIP files"
}
if (-not $TriWeather -or $TriWeather.Count -eq 0) {
    $TriWeather = Select-InputFiles "Select TRI-Thalawakele weather workbooks (base and latest update)" $true
}
if (-not $PedroWeather -or $PedroWeather.Count -eq 0) {
    $PedroWeather = Select-InputFiles "Select the latest valid Pedro/Nuwara Eliya weather workbook" $true
}

# Apply overlapping weather updates in modification-time order so the newest
# workbook replaces the older daily observations.
$TriWeather = @($TriWeather | ForEach-Object { Get-Item -LiteralPath $_ } | Sort-Object LastWriteTime | Select-Object -ExpandProperty FullName)
$PedroWeather = @($PedroWeather | ForEach-Object { Get-Item -LiteralPath $_ } | Sort-Object LastWriteTime | Select-Object -ExpandProperty FullName)

if (-not ("TteExecutionState" -as [type])) {
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class TteExecutionState {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint esFlags);
}
"@
}

$ES_CONTINUOUS = [Convert]::ToUInt32("80000000", 16)
$ES_KEEP_AWAKE = [Convert]::ToUInt32("80000041", 16)
[TteExecutionState]::SetThreadExecutionState($ES_KEEP_AWAKE) | Out-Null

Write-Host "PC sleep is temporarily blocked while the all-estate crop run is active." -ForegroundColor Cyan
Write-Host "Crop ZIP folder: $CropRoot" -ForegroundColor Cyan
Write-Host "TRI weather: $($TriWeather -join '; ')" -ForegroundColor Cyan
Write-Host "Pedro weather: $($PedroWeather -join '; ')" -ForegroundColor Cyan

$Arguments = @{
    CropRoot = $CropRoot
    TriWeather = $TriWeather
    PedroWeather = $PedroWeather
}
if ($SkipSetup) { $Arguments.SkipSetup = $true }

try {
    & "$ProjectRoot\TRAIN_ALL_33_CROP_GPU.ps1" @Arguments
}
finally {
    [TteExecutionState]::SetThreadExecutionState($ES_CONTINUOUS) | Out-Null
    Write-Host "Normal Windows sleep behaviour has been restored." -ForegroundColor Cyan
}
