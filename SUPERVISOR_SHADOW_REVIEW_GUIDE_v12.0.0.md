# TTE Supervisor Shadow Review v12.0.0

This package creates review files from the passed v11.0.2 routing repair.

## Initial stage

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_SUPERVISOR_SHADOW_REVIEW_v12.0.0.ps1
.\OPEN_SUPERVISOR_SHADOW_REVIEW_v12.0.0.ps1
```

Complete:

```text
supervisor_case_review.csv
estate_daily_context.csv
employee_daily_status_verification.csv
shadow_review_signoff.csv
```

Then run:

```powershell
.\VALIDATE_SUPERVISOR_SHADOW_REVIEW_v12.0.0.ps1
.\CHECK_SUPERVISOR_SHADOW_REVIEW_v12.0.0.ps1
```

## Mandatory controls

```text
396 review cases completed
33 estate context rows completed
At least one verified employee shadow sample per estate
Attendance, leave, fitness and movement restrictions verified
Supervisor and cross-functional signoff completed
All live_assignment_authorized fields remain NO
```

A passing validation means the shadow-review documentation is complete.
It does not authorize live assignment, employee notification or payroll use.
