# TTE Employee Home-Division Code Supervisor Review v13.0.7

This stage verifies employee home-division codes.

## Start

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_EMPLOYEE_HOME_CODE_REVIEW_v13.0.7.ps1
.\CHECK_EMPLOYEE_HOME_CODE_REVIEW_v13.0.7.ps1
.\OPEN_EMPLOYEE_HOME_CODE_REVIEW_v13.0.7.ps1
```

## Review files

```text
home_code_context_supervisor_review.csv
employee_home_code_exception_review.csv
```

The context file contains 107 observed historical code contexts.

Single-candidate rows are suggestions only. An authorized reviewer must
check an approved employee master, division register or equivalent
source before confirming.

Ambiguous and unresolved contexts require employee-level review.

Do not use today's assigned division as proof of home division.

TLD remains unresolved until approved records identify each employee's
actual home division.

Keep all attendance, leave, fitness, movement restriction,
operational-use and live-assignment fields as NO.

## Validate

```powershell
.\VALIDATE_EMPLOYEE_HOME_CODE_REVIEW_v13.0.7.ps1
.\CHECK_EMPLOYEE_HOME_CODE_REVIEW_v13.0.7.ps1
```

This stage remains supervisor review only.
