param(
    [string]$ProjectRoot = "C:\TTE_Integrated_Platform\ttel_crop_forecasting",
    [string]$CropRoot = "C:\Users\user\Desktop\HG 2",
    [string]$ForecastStart = "2026-07-27",
    [int]$Years = 3,
    [int]$ChunkDays = 90,
    [switch]$CreateZip
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "TTE 3-YEAR DAILY FORECAST AND EMPLOYEE ALLOCATION v3" -ForegroundColor Cyan
Write-Host "The 3-year period will be processed in consecutive 90-day chunks."
Write-Host "Completed chunks are skipped when the script is run again."
Write-Host ""

if (-not (Test-Path $ProjectRoot)) {
    throw "Project folder not found: $ProjectRoot"
}

if (-not (Test-Path $CropRoot)) {
    throw "Crop data folder not found: $CropRoot"
}

if ($ChunkDays -lt 7 -or $ChunkDays -gt 90) {
    throw "ChunkDays must be between 7 and 90."
}

$dailyLauncher = Join-Path `
    $ProjectRoot `
    "START_DAILY_HIERARCHY_CANDIDATE_v4.0.0.ps1"

$planningLauncher = Join-Path `
    $ProjectRoot `
    "START_FINAL_METHOD_GATE_PLANNING_v5.0.3.ps1"

$allocationBuilder = Join-Path `
    $ProjectRoot `
    "BUILD_TTE_3_YEAR_EMPLOYEE_ALLOCATIONS_v3.py"

$masterBuilder = Join-Path `
    $ProjectRoot `
    "BUILD_TTE_3_YEAR_MASTER_INDEX_v3.py"

foreach ($requiredFile in @(
    $dailyLauncher,
    $planningLauncher,
    $allocationBuilder,
    $masterBuilder
)) {
    if (-not (Test-Path $requiredFile)) {
        throw "Required file not found: $requiredFile"
    }
}

$startDate = [datetime]::ParseExact(
    $ForecastStart,
    "yyyy-MM-dd",
    [System.Globalization.CultureInfo]::InvariantCulture
)

$endExclusive = $startDate.AddYears($Years)
$endInclusive = $endExclusive.AddDays(-1)
$totalDays = [int]($endExclusive - $startDate).TotalDays
$expectedChunks = [int][math]::Ceiling(
    $totalDays / [double]$ChunkDays
)

$desktop = [Environment]::GetFolderPath("Desktop")
$outputRoot = Join-Path `
    $desktop `
    ("TTE_3_Year_Daily_Forecast_Employee_Allocation_{0}_to_{1}" -f `
        $startDate.ToString("yyyyMMdd"),
        $endInclusive.ToString("yyyyMMdd"))

$chunksRoot = Join-Path $outputRoot "Chunks"
New-Item -ItemType Directory -Force -Path $chunksRoot | Out-Null

$v13Root = Join-Path `
    $ProjectRoot `
    "workforce_planner\v13_0_8\development_allocation_consolidation_runs"

$v13Pointer = Join-Path `
    $v13Root `
    "LATEST_DEVELOPMENT_ALLOCATION_V1308_RUN.txt"

if (-not (Test-Path $v13Pointer)) {
    throw "Latest v13.0.8 employee-allocation pointer was not found."
}

$v13Run = (Get-Content $v13Pointer -Raw).Trim()
$employeeTemplate = Join-Path `
    $v13Run `
    "allocation\all_development_allocation.csv"

if (-not (Test-Path $employeeTemplate)) {
    throw "Employee allocation template was not found: $employeeTemplate"
}

Write-Host ("Forecast start: {0}" -f $startDate.ToString("yyyy-MM-dd"))
Write-Host ("Forecast end:   {0}" -f $endInclusive.ToString("yyyy-MM-dd"))
Write-Host ("Total days:     {0}" -f $totalDays)
Write-Host ("Chunks:         {0}" -f $expectedChunks)
Write-Host ("Chunk size:     up to {0} days" -f $ChunkDays)
Write-Host ""
Write-Host "Keep PowerShell open. You can rerun this script to resume." -ForegroundColor Yellow

Set-Location $ProjectRoot

$remainingDays = $totalDays
$currentStart = $startDate
$chunkNumber = 1

while ($remainingDays -gt 0) {
    $daysThisChunk = [math]::Min($ChunkDays, $remainingDays)
    $currentEnd = $currentStart.AddDays($daysThisChunk - 1)

    $chunkName = (
        "Chunk_{0:D2}_{1}_to_{2}" -f `
            $chunkNumber,
            $currentStart.ToString("yyyyMMdd"),
            $currentEnd.ToString("yyyyMMdd")
    )

    $chunkOutput = Join-Path $chunksRoot $chunkName
    $chunkSummary = Join-Path $chunkOutput "run_summary.json"

    Write-Host ""
    Write-Host ("============================================================")
    Write-Host (
        "CHUNK {0} OF {1}: {2} TO {3} ({4} DAYS)" -f `
            $chunkNumber,
            $expectedChunks,
            $currentStart.ToString("yyyy-MM-dd"),
            $currentEnd.ToString("yyyy-MM-dd"),
            $daysThisChunk
    ) -ForegroundColor Cyan
    Write-Host ("============================================================")

    $skipChunk = $false

    if (Test-Path $chunkSummary) {
        try {
            $existing = Get-Content $chunkSummary -Raw | ConvertFrom-Json

            if (
                $existing.status -eq `
                    "PASS_3_YEAR_DAILY_FORECAST_AND_EMPLOYEE_ALLOCATION_OUTPUTS" -and
                $existing.forecast_start -eq `
                    $currentStart.ToString("yyyy-MM-dd") -and
                $existing.forecast_end -eq `
                    $currentEnd.ToString("yyyy-MM-dd")
            ) {
                $skipChunk = $true
            }
        }
        catch {
            $skipChunk = $false
        }
    }

    if ($skipChunk) {
        Write-Host "Chunk already completed. Skipping." -ForegroundColor Green
    }
    else {
        if (Test-Path $chunkOutput) {
            Remove-Item $chunkOutput -Recurse -Force
        }
        New-Item -ItemType Directory -Force -Path $chunkOutput | Out-Null

        & $dailyLauncher `
            -CropRoot $CropRoot `
            -ForecastDays $daysThisChunk `
            -ForecastStart $currentStart.ToString("yyyy-MM-dd")

        if ($LASTEXITCODE -ne 0) {
            throw "Daily forecast failed for $chunkName."
        }

        $v4Pointer = Join-Path `
            $ProjectRoot `
            "workforce_planner\v4\daily_hierarchy_runs\LATEST_DAILY_HIERARCHY_RUN.txt"

        if (-not (Test-Path $v4Pointer)) {
            throw "Daily forecast pointer was not created."
        }

        $v4Run = (Get-Content $v4Pointer -Raw).Trim()

        & $planningLauncher

        if ($LASTEXITCODE -ne 0) {
            throw "Field-demand planning failed for $chunkName."
        }

        $v5Root = Join-Path `
            $ProjectRoot `
            "workforce_planner\v5\final_method_gate_runs_v503"

        $fieldDemandFile = Get-ChildItem `
            -Path $v5Root `
            -Recurse `
            -File `
            -Filter "field_required_plucker_assignments.csv" `
            -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1

        if ($null -eq $fieldDemandFile) {
            throw "No field-demand output was found for $chunkName."
        }

        $v5Run = $fieldDemandFile.Directory.Parent.FullName

        & py -3.12 $allocationBuilder `
            --v4-run $v4Run `
            --v5-run $v5Run `
            --field-demand $fieldDemandFile.FullName `
            --employee-template $employeeTemplate `
            --output-folder $chunkOutput `
            --forecast-start $currentStart.ToString("yyyy-MM-dd") `
            --forecast-days $daysThisChunk `
            --expected-estates 33

        if ($LASTEXITCODE -ne 0) {
            throw "Employee allocation failed for $chunkName."
        }

        Write-Host "Chunk completed." -ForegroundColor Green
    }

    & py -3.12 $masterBuilder `
        --output-root $outputRoot `
        --forecast-start $startDate.ToString("yyyy-MM-dd") `
        --forecast-end $endInclusive.ToString("yyyy-MM-dd") `
        --expected-chunks $expectedChunks

    if ($LASTEXITCODE -ne 0) {
        throw "Master index update failed."
    }

    $remainingDays -= $daysThisChunk
    $currentStart = $currentEnd.AddDays(1)
    $chunkNumber += 1
}

if ($CreateZip) {
    $zipPath = "$outputRoot.zip"

    if (Test-Path $zipPath) {
        Remove-Item $zipPath -Force
    }

    Write-Host ""
    Write-Host "Compressing the large output folder..." -ForegroundColor Yellow

    Compress-Archive `
        -Path (Join-Path $outputRoot "*") `
        -DestinationPath $zipPath `
        -Force

    Write-Host ("ZIP created: {0}" -f $zipPath) -ForegroundColor Green
}

Write-Host ""
Write-Host "FULL 3-YEAR RUN COMPLETED" -ForegroundColor Green
Write-Host ("Output folder: {0}" -f $outputRoot)
Write-Host "Open START_HERE.html."

Invoke-Item (Join-Path $outputRoot "START_HERE.html")
