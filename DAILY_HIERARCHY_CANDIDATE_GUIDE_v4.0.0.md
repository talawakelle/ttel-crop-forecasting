# TTE Daily Estate–Division–Field Hierarchy Candidate v4.0.0

## Purpose

This is the next stage after:

- 33/33 crop candidate gate
- 33/33 productivity processing
- corrected data audit v3.0.1
- verified legacy workbook filename mismatches

The package creates:

1. Historical daily field totals
2. Historical daily division totals
3. Historical daily estate totals
4. Chronological backtests of four estate-daily candidate methods
5. A selected estate-daily method for each estate
6. A 28-day development forecast by default
7. Reconciled division and field forecast baselines
8. A hierarchy reconciliation audit

## Important interpretation

The estate daily candidate is selected by the lowest WAPE on a chronological
observed-plucking-day holdout. WAPE is an error measure, not an accuracy percentage.

The division and field outputs are smoothed historical-share baselines. They are
not yet independent field-level machine-learning models.

Missing source dates are not automatically treated as zero crop.

## Safety

- No crop model is replaced.
- No productivity model is replaced.
- No manager portal is changed.
- No employee is allocated.
- CP-SAT is not started.
- RL is not started.
- Source freshness and operating-calendar approval are required before operational use.

## Install

Extract the package into:

`C:\TTE_Integrated_Platform`

## Start

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_DAILY_HIERARCHY_CANDIDATE_v4.0.0.ps1 `
    -CropRoot "C:\Users\user\Desktop\HG 2" `
    -ForecastDays 28
```

Optional fixed start date:

```powershell
.\START_DAILY_HIERARCHY_CANDIDATE_v4.0.0.ps1 `
    -CropRoot "C:\Users\user\Desktop\HG 2" `
    -ForecastDays 28 `
    -ForecastStart "2026-07-24"
```

## Check

```powershell
.\CHECK_DAILY_HIERARCHY_CANDIDATE_v4.0.0.ps1
```

## Main outputs

`workforce_planner\v4\daily_hierarchy_runs\daily_hierarchy_candidate_YYYYMMDD_HHMMSS`

- `historical\field_daily.csv.gz`
- `historical\division_daily.csv.gz`
- `historical\estate_daily.csv.gz`
- `backtest\estate_candidate_metrics.csv`
- `backtest\estate_selected_models.csv`
- `forecast\estate_daily_forecast.csv`
- `forecast\division_daily_forecast.csv`
- `forecast\field_daily_forecast.csv`
- `profiles\estate_hierarchy_profile.csv`
- `profiles\identity_gate_resolution.csv`
- `hierarchy_reconciliation_audit.csv`
- `run_summary.json`
