# TTE Next Stage — Data Identity and Readiness Audit v3.0.0

## Purpose

This is the first stage after the 33-estate workforce-productivity candidates.

It performs a read-only audit of all estate ZIP archives and prepares the trusted
data foundation required before daily estate/division/field forecasting.

## It checks

- Archive estate name versus internal workbook estate name
- Required date, employee, division, field and net-weight columns
- Historical date range and data freshness
- Valid plucking rows
- Missing required values
- Non-positive weights
- Duplicate weighing IDs
- Employee, division and field counts
- Estate readiness score

## Outputs

The latest timestamped folder is created under:

`workforce_planner\v3\data_audit_runs\estate_audit_YYYYMMDD_HHMMSS`

Files:

- `audit_summary.json`
- `estate_data_audit.csv`
- `estate_file_identity_audit.csv`
- `estate_alias_mapping.csv`
- `estate_readiness.json`
- `rejected_rows_sample.csv`
- `data_quality_report.md`

## Safety

- No live model is changed.
- No manager portal is changed.
- No employee is allocated.
- Raw employee identifiers are not written to the rejected-row sample.
- This stage must be reviewed before daily field-demand modelling.

## Start

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_DATA_IDENTITY_READINESS_AUDIT_v3.0.0.ps1 `
    -CropRoot "C:\Users\user\Desktop\HG 2"
```

## Check results

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
.\CHECK_DATA_IDENTITY_READINESS_AUDIT_v3.0.0.ps1
```
