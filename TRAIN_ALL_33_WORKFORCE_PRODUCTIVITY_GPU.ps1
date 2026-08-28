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
$WorkforceRoot = Join-Path $ProjectRoot "workforce_planner"
Set-Location $ProjectRoot

$LatestCropRun = Get-ChildItem (Join-Path $ProjectRoot "outputs") -Directory `
    -Filter "gpu_candidates_*" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($LatestCropRun -and -not (Test-Path (Join-Path $LatestCropRun.FullName "gpu_batch_summary.csv"))) {
    if (-not $WaitForCrop) {
        throw "The all-estate crop GPU run is still active or incomplete: $($LatestCropRun.FullName). Let it finish or use -WaitForCrop."
    }
    Write-Host "Waiting for the all-estate crop GPU batch to finish: $($LatestCropRun.FullName)" -ForegroundColor Yellow
    while (-not (Test-Path (Join-Path $LatestCropRun.FullName "gpu_batch_summary.csv"))) {
        Start-Sleep -Seconds 30
    }
}
if ($LatestCropRun) {
    $CropSummary = @(Import-Csv (Join-Path $LatestCropRun.FullName "gpu_batch_summary.csv"))
    $CropFailures = @($CropSummary | Where-Object status -ne "PASS")
    if ($CropSummary.Count -ne 33 -or $CropFailures.Count) {
        throw "The crop GPU batch did not finish with 33 PASS results. Workforce training will not start."
    }
    Write-Host "Crop GPU gate passed: 33 / 33 estates." -ForegroundColor Green
}

foreach ($Path in @($CropRoot, $TriWeather, $PedroWeather)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Required input not found: $Path" }
}

if (-not $SkipSetup) {
    & "$WorkforceRoot\setup_gpu_windows.ps1"
}
$Python = Join-Path $WorkforceRoot "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Workforce GPU environment was not found." }

& $Python -c "from catboost.utils import get_gpu_device_count; n=get_gpu_device_count(); print(f'CatBoost CUDA devices: {n}'); assert n > 0"
if ($LASTEXITCODE -ne 0) { throw "CatBoost cannot access the NVIDIA GPU." }

$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$RunRoot = Join-Path $WorkforceRoot "v2\model_candidates\productivity_gpu_$Stamp"
$Manifest = Join-Path $RunRoot "estate_sources.csv"
$Log = Join-Path $RunRoot "all_estate_productivity_gpu.log"
New-Item -ItemType Directory -Path $RunRoot -Force | Out-Null

& $Python "$ProjectRoot\discover_estate_archives.py" --crop-root (Resolve-Path $CropRoot).Path --output $Manifest
if ($LASTEXITCODE -ne 0) { throw "All 33 valid estate ZIP archives are required." }
$Sources = @(Import-Csv $Manifest)

$WeatherRoot = Join-Path $RunRoot "weather"
New-Item -ItemType Directory -Path $WeatherRoot -Force | Out-Null
$TriDaily = Join-Path $WeatherRoot "tri_weather_daily.csv.gz"
$TriMetadata = Join-Path $WeatherRoot "tri_weather_metadata.json"
$PedroDaily = Join-Path $WeatherRoot "pedro_weather_daily.csv.gz"
$PedroMetadata = Join-Path $WeatherRoot "pedro_weather_metadata.json"
$NoDataset = Join-Path $RunRoot "weather_only_no_productivity_dataset.csv.gz"

& $Python "$WorkforceRoot\scripts\prepare_weather_data.py" $TriWeather `
    --daily $TriDaily --metadata $TriMetadata --productivity-dataset $NoDataset `
    --station "TRI-TW" --station-label "TRI Thalawakelle"
if ($LASTEXITCODE -ne 0) { throw "TRI workforce-weather preparation failed." }
& $Python "$WorkforceRoot\scripts\prepare_weather_data.py" $PedroWeather `
    --daily $PedroDaily --metadata $PedroMetadata --productivity-dataset $NoDataset `
    --station "PEDRO" --station-label "Pedro Nuwara Eliya"
if ($LASTEXITCODE -ne 0) { throw "Pedro workforce-weather preparation failed." }

$Results = [System.Collections.Generic.List[object]]::new()
Start-Transcript -Path $Log
if (-not ("TteWorkforceExecutionState" -as [type])) {
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class TteWorkforceExecutionState {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint esFlags);
}
"@
}
$ES_CONTINUOUS = [Convert]::ToUInt32("80000000", 16)
$ES_KEEP_AWAKE = [Convert]::ToUInt32("80000041", 16)
[TteWorkforceExecutionState]::SetThreadExecutionState($ES_KEEP_AWAKE) | Out-Null
try {
    foreach ($Row in $Sources) {
        $Estate = $Row.estate
        $Started = Get-Date
        $Split = $null
        $EstateRoot = Join-Path $RunRoot $Estate
        $DataRoot = Join-Path $EstateRoot "data"
        $ModelRoot = Join-Path $EstateRoot "models"
        New-Item -ItemType Directory -Path $DataRoot,$ModelRoot -Force | Out-Null
        $Profile = Join-Path $DataRoot "workforce_profile.json"
        $Dataset = Join-Path $DataRoot "productivity_training.csv.gz"
        $State = Join-Path $DataRoot "productivity_state.json.gz"
        $DatasetMetadata = Join-Path $DataRoot "productivity_dataset_metadata.json"
        $SplitPath = Join-Path $DataRoot "temporal_split.json"
        $BaseModel = Join-Path $ModelRoot "productivity_catboost.cbm"
        $WeatherModel = Join-Path $ModelRoot "productivity_weather_catboost.cbm"
        $Metrics = Join-Path $ModelRoot "productivity_metrics.json"
        $Rejected = Join-Path $ModelRoot "productivity_rejected_metrics.json"
        $UsePedro = $Estate -in @("Pedro", "NuwaraEliya")
        $WeatherDaily = if ($UsePedro) { $PedroDaily } else { $TriDaily }
        $WeatherMetadata = if ($UsePedro) { $PedroMetadata } else { $TriMetadata }

        Write-Host "Estate productivity GPU candidate: $Estate" -ForegroundColor Green
        try {
            & $Python "$WorkforceRoot\scripts\prepare_data.py" $Row.crop_source $Profile
            if ($LASTEXITCODE -ne 0) { throw "Profile preparation failed" }
            & $Python "$WorkforceRoot\v2\scripts\choose_productivity_split.py" --profile $Profile --output $SplitPath
            if ($LASTEXITCODE -ne 0) { throw "Temporal split selection failed" }
            $Split = Get-Content $SplitPath -Raw | ConvertFrom-Json
            & $Python "$WorkforceRoot\scripts\prepare_forecast_data.py" $Row.crop_source `
                --dataset $Dataset --state $State --metadata $DatasetMetadata `
                --train-end $Split.train_end --validation-end $Split.validation_end `
                --weather-daily $WeatherDaily --weather-metadata $WeatherMetadata
            if ($LASTEXITCODE -ne 0) { throw "Productivity feature preparation failed" }
            & $Python "$WorkforceRoot\scripts\train_productivity_gpu.py" `
                --dataset $Dataset --dataset-metadata $DatasetMetadata --state $State `
                --weather-daily $WeatherDaily --weather-metadata $WeatherMetadata --profile $Profile `
                --base-model $BaseModel --weather-model $WeatherModel --metrics $Metrics `
                --rejected-metrics $Rejected --iterations $Iterations --task-type gpu `
                --devices 0 --gpu-ram-part 0.85
            if ($LASTEXITCODE -ne 0) { throw "GPU productivity training failed" }
            if (Test-Path $Metrics) {
                $Report = Get-Content $Metrics -Raw | ConvertFrom-Json
                $Status = "APPROVED_CANDIDATE"
                $Message = "Untouched temporal test gate passed; shadow mode still required"
                $Improvement = $Report.test_metrics.mae_improvement_pct
            }
            elseif (Test-Path $Rejected) {
                $Report = Get-Content $Rejected -Raw | ConvertFrom-Json
                $Status = "REJECTED"
                $Message = "Did not beat the historical baseline safety gate"
                $Improvement = $Report.base_test_metrics.mae_improvement_pct
            }
            else {
                throw "No approved or rejected metrics file was produced"
            }
        }
        catch {
            $Status = "FAILED"
            $Message = $_.Exception.Message
            $Improvement = $null
        }
        $Results.Add([PSCustomObject]@{
            estate = $Estate
            status = $Status
            history_class = if ($Split) { $Split.history_class } else { "unknown" }
            test_mae_improvement_pct = $Improvement
            duration_minutes = [math]::Round(((Get-Date) - $Started).TotalMinutes, 2)
            output = $EstateRoot
            message = $Message
        })
    }
}
finally {
    $Results | Sort-Object estate | Export-Csv (Join-Path $RunRoot "productivity_gpu_batch_summary.csv") -NoTypeInformation -Encoding UTF8
    [TteWorkforceExecutionState]::SetThreadExecutionState($ES_CONTINUOUS) | Out-Null
    Stop-Transcript
}

& $Python "$WorkforceRoot\v2\scripts\build_productivity_summary.py" --run-root $RunRoot
$Results | Sort-Object estate | Format-Table estate,status,history_class,test_mae_improvement_pct,duration_minutes -AutoSize
Write-Host "All-estate productivity candidate folder: $RunRoot" -ForegroundColor Cyan
Write-Host "These models are isolated candidates. No manager portal or live allocator was changed." -ForegroundColor Yellow
Write-Host "Estate-specific attendance, skills, restrictions, daily field demand and shadow-mode approval are required before live use." -ForegroundColor Yellow
