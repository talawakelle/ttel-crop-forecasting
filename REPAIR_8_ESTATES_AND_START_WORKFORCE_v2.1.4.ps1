[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$CropRoot,

    [Parameter(Mandatory = $true)]
    [string]$TriWeather,

    [Parameter(Mandatory = $true)]
    [string]$PedroWeather,

    [ValidateRange(200, 20000)]
    [int]$WorkforceIterations = 3000,

    [switch]$SkipWorkforceSetup
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

function Test-CompleteForecastOutput {
    param([Parameter(Mandatory = $true)][string]$Path)
    foreach ($Name in @("forecast.csv", "weekly_history.csv", "model_metrics.csv", "data_quality.json")) {
        if (-not (Test-Path (Join-Path $Path $Name) -PathType Leaf)) { return $false }
    }
    try {
        $ForecastRows = @(Import-Csv (Join-Path $Path "forecast.csv"))
        return ($ForecastRows.Count -eq 4 -and @($ForecastRows | Where-Object { -not $_.forecast_kg }).Count -eq 0)
    }
    catch { return $false }
}

function Save-Summary {
    param([Parameter(Mandatory = $true)]$Rows, [Parameter(Mandatory = $true)][string]$Path)
    $Rows | Sort-Object estate | Export-Csv $Path -NoTypeInformation -Encoding UTF8
}

if (-not (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue)) {
    throw "NVIDIA driver/GPU was not found."
}

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python -PathType Leaf)) {
    throw "Crop Python environment was not found: $Python"
}

foreach ($Path in @($CropRoot, $TriWeather, $PedroWeather)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Required input was not found: $Path" }
}

$Run = Get-ChildItem (Join-Path $ProjectRoot "outputs") -Directory `
    -Filter "gpu_candidates_*" -ErrorAction SilentlyContinue |
    Where-Object { Test-Path (Join-Path $_.FullName "gpu_batch_summary.csv") } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $Run) { throw "No completed all-estate GPU crop candidate run was found." }

$RunRoot = $Run.FullName
$SummaryPath = Join-Path $RunRoot "gpu_batch_summary.csv"
$ManifestPath = Join-Path $RunRoot "gpu_estate_sources.csv"
$ActualsSnapshot = Join-Path $RunRoot "prompt_daily_actuals_snapshot.csv"
$TriCache = Join-Path $RunRoot "tri_weather_daily_cache.csv"
$PedroCache = Join-Path $RunRoot "pedro_weather_daily_cache.csv"
$RepairLog = Join-Path $RunRoot "repair_8_estates_v2.1.4.log"

foreach ($Required in @($SummaryPath, $ManifestPath, $ActualsSnapshot, $TriCache, $PedroCache)) {
    if (-not (Test-Path $Required -PathType Leaf)) { throw "Required run file was not found: $Required" }
}

$Summary = @(Import-Csv $SummaryPath)
if ($Summary.Count -ne 33) { throw "The crop summary must contain 33 estates; found $($Summary.Count)." }
$Sources = @(Import-Csv $ManifestPath)

$DirectRepair = @("Alton", "Bambarakelly", "Fairlawn", "Gouravilla", "Mahanilu", "Stockholm")
$ShortDirect = @("Bambarakelly")
$PooledRepair = @("EildonHall", "Tillicoultry")
$ExpectedRepair = @($DirectRepair + $PooledRepair)
$UnexpectedFailures = @(
    $Summary | Where-Object status -ne "PASS" | Select-Object -ExpandProperty estate |
    Where-Object { $_ -notin $ExpectedRepair }
)
if ($UnexpectedFailures.Count) {
    throw "Unexpected failed estates were found: $($UnexpectedFailures -join ', ')."
}

if (-not ("TteRepairExecutionState214" -as [type])) {
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class TteRepairExecutionState214 {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint esFlags);
}
"@
}
$ES_CONTINUOUS = [Convert]::ToUInt32("80000000", 16)
$ES_KEEP_AWAKE = [Convert]::ToUInt32("80000041", 16)
[TteRepairExecutionState214]::SetThreadExecutionState($ES_KEEP_AWAKE) | Out-Null

Write-Host "Resuming repair in: $RunRoot" -ForegroundColor Cyan
Write-Host "Alton will be reused because its completed repair output already exists." -ForegroundColor Green
Write-Host "Bambarakelly will use the guarded short-history provisional gate." -ForegroundColor Yellow
Write-Host "All incomplete crop weeks remain excluded from training." -ForegroundColor Yellow

$RepairFailures = [System.Collections.Generic.List[string]]::new()
Start-Transcript -Path $RepairLog -Append
try {
    foreach ($Estate in $DirectRepair) {
        $Row = $Sources | Where-Object estate -eq $Estate | Select-Object -First 1
        $Target = $Summary | Where-Object estate -eq $Estate | Select-Object -First 1
        if (-not $Row -or -not $Target) {
            $RepairFailures.Add("${Estate}: source or summary row missing")
            continue
        }

        $Output = Join-Path $RunRoot "${Estate}_provisional"
        if (Test-CompleteForecastOutput $Output) {
            Write-Host "Resume check PASS: $Estate already has a complete four-row forecast." -ForegroundColor DarkGreen
            $Target.status = "PASS"
            $Target.mode = if ($Estate -in $ShortDirect) { "short_history_historical_only_gpu_candidate" } else { "historical_only_gpu_candidate" }
            $Target.output = $Output
            $Target.message = if ($Estate -in $ShortDirect) {
                "PASS PROVISIONAL - short history; historical archive used; incomplete weeks excluded"
            } else {
                "PASS PROVISIONAL - no matching completed PROMPT actual rows; historical archive used"
            }
            Save-Summary $Summary $SummaryPath
            continue
        }

        if (Test-Path $Output) { Remove-Item $Output -Recurse -Force }
        $Started = Get-Date
        $Arguments = @(
            "$ProjectRoot\train.py",
            "--estate", $Estate,
            "--crop", $Row.crop_source,
            "--actuals", $ActualsSnapshot,
            "--allow-missing-actuals",
            "--accelerator", "gpu",
            "--output-dir", $Output,
            "--weather", $TriCache
        )
        if ($Estate -in $ShortDirect) { $Arguments += "--short-history-provisional" }

        Write-Host "Repair GPU crop training: $Estate" -ForegroundColor Green
        try {
            & $Python @Arguments
            if ($LASTEXITCODE -ne 0) { throw "training returned exit code $LASTEXITCODE" }
            if (-not (Test-CompleteForecastOutput $Output)) { throw "required output files or four forecast rows were not produced" }

            $Target.status = "PASS"
            $Target.mode = if ($Estate -in $ShortDirect) { "short_history_historical_only_gpu_candidate" } else { "historical_only_gpu_candidate" }
            $Target.duration_minutes = [math]::Round(((Get-Date) - $Started).TotalMinutes, 2)
            $Target.output = $Output
            $Target.message = if ($Estate -in $ShortDirect) {
                "PASS PROVISIONAL - short history; historical archive used; incomplete weeks excluded"
            } else {
                "PASS PROVISIONAL - no matching completed PROMPT actual rows; historical archive used"
            }
        }
        catch {
            $Target.status = "FAIL"
            $Target.message = $_.Exception.Message
            $RepairFailures.Add("${Estate}: $($_.Exception.Message)")
            Write-Host "Repair failed for $Estate but the script will check the remaining direct estates." -ForegroundColor Red
        }
        Save-Summary $Summary $SummaryPath
    }

    $MissingDonors = @($DirectRepair | Where-Object {
        -not (Test-CompleteForecastOutput (Join-Path $RunRoot "${_}_provisional"))
    })
    if ($MissingDonors.Count) {
        foreach ($Estate in $PooledRepair) {
            $Target = $Summary | Where-Object estate -eq $Estate | Select-Object -First 1
            $Target.status = "FAIL"
            $Target.message = "Pooled repair not run because donor outputs are missing: $($MissingDonors -join ', ')"
        }
        Save-Summary $Summary $SummaryPath
    }
    else {
        foreach ($Estate in $PooledRepair) {
            $Row = $Sources | Where-Object estate -eq $Estate | Select-Object -First 1
            $Target = $Summary | Where-Object estate -eq $Estate | Select-Object -First 1
            if (-not $Row -or -not $Target) {
                $RepairFailures.Add("${Estate}: source or summary row missing")
                continue
            }

            $Output = Join-Path $RunRoot "${Estate}_provisional"
            if (Test-CompleteForecastOutput $Output) {
                Write-Host "Resume check PASS: $Estate already has a complete pooled forecast." -ForegroundColor DarkGreen
                $Target.status = "PASS"
                $Target.mode = "short_history_pooled_gpu_candidate"
                $Target.output = $Output
                $Target.message = "PASS PROVISIONAL - pooled short-history model"
                Save-Summary $Summary $SummaryPath
                continue
            }

            if (Test-Path $Output) { Remove-Item $Output -Recurse -Force }
            $Started = Get-Date
            $Arguments = @(
                "$ProjectRoot\train_pooled_short_history.py",
                "--estate", $Estate,
                "--crop", $Row.crop_source,
                "--actuals", $ActualsSnapshot,
                "--allow-missing-actuals",
                "--accelerator", "gpu",
                "--output-dir", $Output,
                "--weather", $TriCache
            )
            foreach ($Donor in $DirectRepair) {
                $Arguments += @("--donor-output", (Join-Path $RunRoot "${Donor}_provisional"))
            }

            Write-Host "Repair pooled GPU crop training: $Estate" -ForegroundColor Yellow
            try {
                & $Python @Arguments
                if ($LASTEXITCODE -ne 0) { throw "training returned exit code $LASTEXITCODE" }
                if (-not (Test-CompleteForecastOutput $Output)) { throw "required pooled output files or four forecast rows were not produced" }

                $Target.status = "PASS"
                $Target.mode = "short_history_pooled_gpu_candidate"
                $Target.duration_minutes = [math]::Round(((Get-Date) - $Started).TotalMinutes, 2)
                $Target.output = $Output
                $Target.message = "PASS PROVISIONAL - pooled short-history model"
            }
            catch {
                $Target.status = "FAIL"
                $Target.message = $_.Exception.Message
                $RepairFailures.Add("${Estate}: $($_.Exception.Message)")
            }
            Save-Summary $Summary $SummaryPath
        }
    }

    $Final = @(Import-Csv $SummaryPath)
    $Failures = @($Final | Where-Object status -ne "PASS")
    if ($Final.Count -ne 33 -or $Failures.Count) {
        $Names = ($Failures | Select-Object -ExpandProperty estate) -join ", "
        throw "Repair is not yet 33/33. Remaining failed estates: $Names. Workforce training was not started."
    }

    & $Python "$ProjectRoot\build_portfolio_summary.py" --outputs-dir $RunRoot
    if ($LASTEXITCODE -ne 0) { throw "Portfolio summary rebuild failed." }
    Write-Host "Crop gate passed after repair: 33 / 33 estates." -ForegroundColor Green
}
finally {
    Stop-Transcript
    [TteRepairExecutionState214]::SetThreadExecutionState($ES_CONTINUOUS) | Out-Null
}

$WorkforceScript = Join-Path $ProjectRoot "START_ALL_33_WORKFORCE_PRODUCTIVITY_GPU.ps1"
if (-not (Test-Path $WorkforceScript -PathType Leaf)) {
    throw "Workforce GPU launcher was not found: $WorkforceScript"
}

$WorkforceArguments = @{
    CropRoot = $CropRoot
    TriWeather = $TriWeather
    PedroWeather = $PedroWeather
    Iterations = $WorkforceIterations
}
if ($SkipWorkforceSetup) { $WorkforceArguments.SkipSetup = $true }

Write-Host "Starting all-33-estate workforce-productivity GPU training now..." -ForegroundColor Cyan
& $WorkforceScript @WorkforceArguments
if ($LASTEXITCODE -ne 0) { throw "Workforce-productivity launcher returned exit code $LASTEXITCODE" }

Write-Host "Crop repair and workforce-productivity training finished." -ForegroundColor Green
Write-Host "Field-level demand and multi-estate RL remain separate later stages." -ForegroundColor Yellow
