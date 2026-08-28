# TTE Corrected Data Identity and Readiness Audit v3.0.1

This patch fixes the v3.0.0 `TypeError: unsupported operand type(s) for +: 'int' and 'str'`.

It uses the exact historical source structure already used by the successful
workforce-productivity pipeline:

- ZIP archives may contain workbooks in nested folders.
- Each workbook is audited through the `All Records` worksheet.
- Required columns are `date`, `employee_id`, `net_weight`, `field_code`,
  `division_name`, and `type`.
- Workbook names are checked against the archive estate name.
- The audit remains read-only.

## Install

Extract the ZIP to:

`C:\TTE_Integrated_Platform`

## Start

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_DATA_IDENTITY_READINESS_AUDIT_v3.0.1.ps1 `
    -CropRoot "C:\Users\user\Desktop\HG 2"
```

## Check

```powershell
.\CHECK_DATA_IDENTITY_READINESS_AUDIT_v3.0.1.ps1
```
