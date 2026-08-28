# TTE Rare Cross-Division Exception Review v13.0.6

This version does not describe the allocation model as mixed division.

Normal model:

```text
same-division allocation
```

Small exceptional activity:

```text
cross-division exception
```

The system reports the actual exception percentage. It does not invent
a percentage limit.

## Start

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_RARE_CROSS_DIVISION_EXCEPTION_v13.0.6.ps1
.\CHECK_RARE_CROSS_DIVISION_EXCEPTION_v13.0.6.ps1
.\OPEN_RARE_CROSS_DIVISION_EXCEPTION_REVIEW_v13.0.6.ps1
```

## Review file

```text
employee_capacity_and_cross_division_exception_review.csv
```

Standard same-division rows require no exception approval.

Only genuine cross-division exception rows require:

```text
exception_reason
supervisor_exception_confirmed = YES
supervisor_name
reviewed_at
```

The total allocation across all rows for an employee must not exceed
the employee's daily capacity.

Keep all verification, operational-use and live-assignment fields as NO.

## Validate

```powershell
.\VALIDATE_RARE_CROSS_DIVISION_EXCEPTION_v13.0.6.ps1
.\CHECK_RARE_CROSS_DIVISION_EXCEPTION_v13.0.6.ps1
```

This stage remains review-only.
