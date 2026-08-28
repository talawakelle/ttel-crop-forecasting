[CmdletBinding()]
param(
    [string]$Manifest = "config\estate_training_manifest.csv",
    [string]$SummaryPath = "outputs\batch_training_summary.csv"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if (-not (Test-Path $Manifest -PathType Leaf)) {
    throw "Training manifest not found: $Manifest"
}

$Rows = @(Import-Csv $Manifest)
if ($Rows.Count -eq 0) {
    throw "Training manifest is empty: $Manifest"
}

$EnabledRows = @($Rows | Where-Object {
    $_.enabled -match '^(?i:true|yes|1)$'
})
if ($EnabledRows.Count -eq 0) {
    throw "No enabled estates were found in $Manifest"
}

$Results = foreach ($Row in $EnabledRows) {
    $Estate = $Row.estate.Trim()
    $CropSource = $Row.crop_source.Trim()
    $WeatherFile = $Row.weather_file.Trim()
    $Started = Get-Date
    $Status = "PASS"
    $Message = "Training completed"

    try {
        if ([string]::IsNullOrWhiteSpace($Estate)) {
            throw "Estate name is blank"
        }
        if ([string]::IsNullOrWhiteSpace($CropSource)) {
            throw "Crop source is blank"
        }
        $TrainingParameters = @{
            Estate = $Estate
            CropZip = $CropSource
        }
        if (-not [string]::IsNullOrWhiteSpace($WeatherFile)) {
            $TrainingParameters["WeatherFile"] = $WeatherFile
        }
        & "$ProjectRoot\train_estate.ps1" @TrainingParameters
    }
    catch {
        $Status = "FAIL"
        $Message = $_.Exception.Message
    }

    [PSCustomObject]@{
        estate = $Estate
        status = $Status
        started_at = $Started.ToString("s")
        duration_minutes = [math]::Round(((Get-Date) - $Started).TotalMinutes, 2)
        crop_source = $CropSource
        weather_file = $WeatherFile
        message = $Message
    }
}

$SummaryDirectory = Split-Path -Parent $SummaryPath
if ($SummaryDirectory) {
    New-Item -ItemType Directory -Force -Path $SummaryDirectory | Out-Null
}
$Results | Export-Csv -Path $SummaryPath -NoTypeInformation -Encoding UTF8
$Results | Format-Table estate, status, duration_minutes, message -AutoSize

$Failed = @($Results | Where-Object { $_.status -eq "FAIL" }).Count
if ($Failed -gt 0) {
    throw "$Failed estate training run(s) failed. See $SummaryPath."
}

Write-Host "Batch training completed. Summary: $SummaryPath" -ForegroundColor Green
