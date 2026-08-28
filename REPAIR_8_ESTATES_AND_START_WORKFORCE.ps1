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

if (-not (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue)) {
    throw "NVIDIA driver/GPU was not found."
}

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python -PathType Leaf)) {
    throw "Crop Python environment was not found: $Python"
}

foreach ($Path in @($CropRoot, $TriWeather, $PedroWeather)) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Required input was not found: $Path"
    }
}

$Run = Get-ChildItem (Join-Path $ProjectRoot "outputs") -Directory `
    -Filter "gpu_candidates_*" -ErrorAction SilentlyContinue |
    Where-Object { Test-Path (Join-Path $_.FullName "gpu_batch_summary.csv") } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $Run) {
    throw "No completed all-estate GPU crop candidate run was found."
}

$RunRoot = $Run.FullName
$SummaryPath = Join-Path $RunRoot "gpu_batch_summary.csv"
$ManifestPath = Join-Path $RunRoot "gpu_estate_sources.csv"
$ActualsSnapshot = Join-Path $RunRoot "prompt_daily_actuals_snapshot.csv"
$TriCache = Join-Path $RunRoot "tri_weather_daily_cache.csv"
$PedroCache = Join-Path $RunRoot "pedro_weather_daily_cache.csv"
$RepairLog = Join-Path $RunRoot "repair_8_estates.log"

foreach ($Required in @($SummaryPath, $ManifestPath, $ActualsSnapshot, $TriCache, $PedroCache)) {
    if (-not (Test-Path $Required -PathType Leaf)) {
        throw "Required run file was not found: $Required"
    }
}

$Summary = @(Import-Csv $SummaryPath)
if ($Summary.Count -ne 33) {
    throw "The crop summary must contain 33 estates; found $($Summary.Count)."
}
$Sources = @(Import-Csv $ManifestPath)

$DirectRepair = @("Alton", "Bambarakelly", "Fairlawn", "Gouravilla", "Mahanilu", "Stockholm")
$ShortHistory = @("EildonHall", "Tillicoultry")
$ExpectedRepair = @($DirectRepair + $ShortHistory)
$CurrentFailures = @($Summary | Where-Object status -ne "PASS" | Select-Object -ExpandProperty estate)
$UnexpectedFailures = @($CurrentFailures | Where-Object { $_ -notin $ExpectedRepair })
if ($UnexpectedFailures.Count) {
    throw "Unexpected failed estates were found: $($UnexpectedFailures -join ', '). Review them before using this repair."
}

if (-not ("TteRepairExecutionState" -as [type])) {
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class TteRepairExecutionState {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint esFlags);
}
"@
}
$ES_CONTINUOUS = [Convert]::ToUInt32("80000000", 16)
$ES_KEEP_AWAKE = [Convert]::ToUInt32("80000041", 16)
[TteRepairExecutionState]::SetThreadExecutionState($ES_KEEP_AWAKE) | Out-Null

Write-Host "Repair run folder: $RunRoot" -ForegroundColor Cyan
Write-Host "The six donor estates will use historical archive data when PROMPT actual rows are absent." -ForegroundColor Yellow
Write-Host "EildonHall and Tillicoultry will then use the pooled provisional model." -ForegroundColor Yellow

Start-Transcript -Path $RepairLog -Append
try {
    foreach ($Estate in $DirectRepair) {
        $Row = $Sources | Where-Object estate -eq $Estate | Select-Object -First 1
        if (-not $Row) { throw "Crop source mapping was not found for $Estate" }

        $Output = Join-Path $RunRoot "${Estate}_provisional"
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

        Write-Host "Repair GPU crop training: $Estate" -ForegroundColor Green
        & $Python @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Repair training failed for $Estate with exit code $LASTEXITCODE"
        }

        $Target = $Summary | Where-Object estate -eq $Estate | Select-Object -First 1
        $Target.status = "PASS"
        $Target.mode = "historical_only_gpu_candidate"
        $Target.duration_minutes = [math]::Round(((Get-Date) - $Started).TotalMinutes, 2)
        $Target.output = $Output
        $Target.message = "PASS PROVISIONAL - no matching completed PROMPT actual rows; historical archive used"
    }

    foreach ($Estate in $ShortHistory) {
        $Row = $Sources | Where-Object estate -eq $Estate | Select-Object -First 1
        if (-not $Row) { throw "Crop source mapping was not found for $Estate" }

        $Output = Join-Path $RunRoot "${Estate}_provisional"
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
        & $Python @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Pooled repair training failed for $Estate with exit code $LASTEXITCODE"
        }

        $Target = $Summary | Where-Object estate -eq $Estate | Select-Object -First 1
        $Target.status = "PASS"
        $Target.mode = "short_history_pooled_gpu_candidate"
        $Target.duration_minutes = [math]::Round(((Get-Date) - $Started).TotalMinutes, 2)
        $Target.output = $Output
        $Target.message = "PASS PROVISIONAL - pooled short-history model"
    }

    $Summary | Sort-Object estate | Export-Csv $SummaryPath -NoTypeInformation -Encoding UTF8
    $Final = @(Import-Csv $SummaryPath)
    $Failures = @($Final | Where-Object status -ne "PASS")
    if ($Final.Count -ne 33 -or $Failures.Count) {
        throw "Repair did not produce 33 PASS results."
    }

    & $Python "$ProjectRoot\build_portfolio_summary.py" --outputs-dir $RunRoot
    if ($LASTEXITCODE -ne 0) { throw "Portfolio summary rebuild failed." }

    Write-Host "Crop gate passed after repair: 33 / 33 estates." -ForegroundColor Green
}
finally {
    Stop-Transcript
    [TteRepairExecutionState]::SetThreadExecutionState($ES_CONTINUOUS) | Out-Null
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
if ($LASTEXITCODE -ne 0) {
    throw "Workforce-productivity launcher returned exit code $LASTEXITCODE"
}

Write-Host "Crop repair and workforce-productivity training finished." -ForegroundColor Green
Write-Host "Field-level demand and multi-estate RL remain separate later stages." -ForegroundColor Yellow
