[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$CropRoot,

    [Parameter(Mandatory = $true)]
    [string[]]$TriWeather,

    [Parameter(Mandatory = $true)]
    [string[]]$PedroWeather,

    [string]$ActualsPath = "outputs\prompt_daily_actuals.csv",
    [switch]$SkipSetup
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if (-not (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue)) {
    throw "NVIDIA driver/GPU was not found. Run nvidia-smi before starting."
}
& nvidia-smi.exe
if ($LASTEXITCODE -ne 0) { throw "nvidia-smi failed." }

if (-not $SkipSetup) {
    & "$ProjectRoot\setup_windows.ps1"
}
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Python environment is missing." }

foreach ($File in @($TriWeather) + @($PedroWeather)) {
    if (-not (Test-Path $File -PathType Leaf)) { throw "Weather workbook not found: $File" }
}
if (-not [System.IO.Path]::IsPathRooted($ActualsPath)) {
    $ActualsPath = Join-Path $ProjectRoot $ActualsPath
}
if (-not (Test-Path $ActualsPath -PathType Leaf)) {
    throw "PROMPT actuals were not found: $ActualsPath. Run the actual sync first."
}

Write-Host "Testing CatBoost on CUDA GPU 0..." -ForegroundColor Cyan
& $Python "$ProjectRoot\check_crop_gpu.py"
if ($LASTEXITCODE -ne 0) { throw "CatBoost GPU smoke test failed." }

$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$RunRoot = Join-Path $ProjectRoot "outputs\gpu_candidates_$Stamp"
$Manifest = Join-Path $RunRoot "gpu_estate_sources.csv"
$Log = Join-Path $RunRoot "overnight_gpu_training.log"
New-Item -ItemType Directory -Path $RunRoot -Force | Out-Null
$ActualsSnapshot = Join-Path $RunRoot "prompt_daily_actuals_snapshot.csv"
Copy-Item -LiteralPath $ActualsPath -Destination $ActualsSnapshot
$RunMetadata = [PSCustomObject]@{
    started_at = (Get-Date).ToString("o")
    crop_root = (Resolve-Path $CropRoot).Path
    actuals_source = (Resolve-Path $ActualsPath).Path
    actuals_snapshot = $ActualsSnapshot
    actuals_sha256 = (Get-FileHash -LiteralPath $ActualsSnapshot -Algorithm SHA256).Hash
    accelerator = "GPU"
    gpu_device = 0
    live_models_replaced = $false
}
$RunMetadata | ConvertTo-Json | Set-Content (Join-Path $RunRoot "gpu_run_metadata.json") -Encoding UTF8

& $Python "$ProjectRoot\discover_estate_archives.py" `
    --crop-root (Resolve-Path $CropRoot).Path `
    --output $Manifest
if ($LASTEXITCODE -ne 0) { throw "Estate source discovery failed. Review $Manifest" }

$Sources = @(Import-Csv $Manifest)
if ($Sources.Count -ne 33) { throw "Expected 33 estate sources; found $($Sources.Count)." }

$TriCache = Join-Path $RunRoot "tri_weather_daily_cache.csv"
$PedroCache = Join-Path $RunRoot "pedro_weather_daily_cache.csv"
$TriCacheArguments = @("$ProjectRoot\prepare_weather_cache.py", "--output", $TriCache)
foreach ($WeatherFile in $TriWeather) { $TriCacheArguments += @("--weather", $WeatherFile) }
$PedroCacheArguments = @("$ProjectRoot\prepare_weather_cache.py", "--output", $PedroCache)
foreach ($WeatherFile in $PedroWeather) { $PedroCacheArguments += @("--weather", $WeatherFile) }
Write-Host "Preparing TRI weather cache once for all mapped estates..." -ForegroundColor Cyan
& $Python @TriCacheArguments
if ($LASTEXITCODE -ne 0) { throw "TRI weather-cache preparation failed." }
Write-Host "Preparing Pedro/Nuwara Eliya weather cache once..." -ForegroundColor Cyan
& $Python @PedroCacheArguments
if ($LASTEXITCODE -ne 0) { throw "Pedro weather-cache preparation failed." }
$ShortHistory = @("EildonHall", "Tillicoultry")
$Results = [System.Collections.Generic.List[object]]::new()

Start-Transcript -Path $Log
try {
    foreach ($Row in @($Sources | Where-Object { $_.estate -notin $ShortHistory })) {
        $Started = Get-Date
        $Estate = $Row.estate
        $Output = Join-Path $RunRoot "${Estate}_provisional"
        $Weather = if ($Estate -in @("Pedro", "NuwaraEliya")) { @($PedroCache) } else { @($TriCache) }
        $Arguments = @(
            "$ProjectRoot\train.py", "--estate", $Estate,
            "--crop", $Row.crop_source,
            "--actuals", $ActualsSnapshot,
            "--accelerator", "gpu",
            "--output-dir", $Output
        )
        foreach ($WeatherFile in $Weather) { $Arguments += @("--weather", $WeatherFile) }
        Write-Host "GPU crop training: $Estate" -ForegroundColor Green
        try {
            & $Python @Arguments
            if ($LASTEXITCODE -ne 0) { throw "Training process returned $LASTEXITCODE" }
            $Status = "PASS"
            $Message = "GPU candidate comparison completed"
        }
        catch {
            $Status = "FAIL"
            $Message = $_.Exception.Message
        }
        $Results.Add([PSCustomObject]@{
            estate=$Estate; status=$Status; mode="estate_specific_gpu_candidate";
            duration_minutes=[math]::Round(((Get-Date)-$Started).TotalMinutes,2);
            output=$Output; message=$Message
        })
    }

    $Donors = @("Alton", "Bambarakelly", "Fairlawn", "Gouravilla", "Mahanilu", "Stockholm")
    foreach ($Estate in $ShortHistory) {
        $Started = Get-Date
        $Row = $Sources | Where-Object estate -eq $Estate
        $Output = Join-Path $RunRoot "${Estate}_provisional"
        $Arguments = @(
            "$ProjectRoot\train_pooled_short_history.py",
            "--estate", $Estate, "--crop", $Row.crop_source,
            "--actuals", $ActualsSnapshot, "--accelerator", "gpu",
            "--output-dir", $Output
        )
        $Arguments += @("--weather", $TriCache)
        foreach ($Donor in $Donors) {
            $DonorOutput = Join-Path $RunRoot "${Donor}_provisional"
            $Arguments += @("--donor-output", $DonorOutput)
        }
        Write-Host "GPU pooled provisional training: $Estate" -ForegroundColor Yellow
        try {
            $MissingDonors = @($Donors | Where-Object {
                -not (Test-Path (Join-Path $RunRoot "$($_)_provisional\forecast.csv"))
            })
            if ($MissingDonors.Count) {
                throw "One or more required donor runs failed"
            }
            & $Python @Arguments
            if ($LASTEXITCODE -ne 0) { throw "Training process returned $LASTEXITCODE" }
            $Status = "PASS"
            $Message = "GPU pooled candidate comparison completed"
        }
        catch {
            $Status = "FAIL"
            $Message = $_.Exception.Message
        }
        $Results.Add([PSCustomObject]@{
            estate=$Estate; status=$Status; mode="short_history_pooled_gpu_candidate";
            duration_minutes=[math]::Round(((Get-Date)-$Started).TotalMinutes,2);
            output=$Output; message=$Message
        })
    }
}
finally {
    $Results | Sort-Object estate | Export-Csv (Join-Path $RunRoot "gpu_batch_summary.csv") -NoTypeInformation -Encoding UTF8
    Stop-Transcript
}

$Failed = @($Results | Where-Object status -ne "PASS")
if ($Failed.Count -eq 0) {
    & $Python "$ProjectRoot\build_portfolio_summary.py" --outputs-dir $RunRoot
}

$Results | Sort-Object estate | Format-Table estate,status,mode,duration_minutes,message -AutoSize
Write-Host "Candidate run folder: $RunRoot" -ForegroundColor Cyan
Write-Host "Training log: $Log" -ForegroundColor Cyan
if ($Failed.Count) {
    throw "$($Failed.Count) estate run(s) failed. Existing portal models were not changed."
}
Write-Host "All 33 GPU candidate comparisons completed. Existing portal models were not replaced." -ForegroundColor Green
Write-Host "Review chronological WAPE and approve promotion separately." -ForegroundColor Yellow
