# TTE Employee Home-Code Review Source Repair v13.0.7.1

This repair fixes the source-selection error in v13.0.7.

The old launcher followed `source_allocation_path` from the v13.0.6
summary. That path could point to the older allocation preview with
these columns:

```text
division
inferred_home_division
```

v13.0.7.1 instead selects the actual v13.0.6 review file containing:

```text
allocation_division_context
employee_home_division_code
```

## Run

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_EMPLOYEE_HOME_CODE_REVIEW_v13.0.7.1.ps1
.\CHECK_EMPLOYEE_HOME_CODE_REVIEW_v13.0.7.1.ps1
.\OPEN_EMPLOYEE_HOME_CODE_REVIEW_v13.0.7.1.ps1
```

Expected source file:

```text
v13_0_6\rare_cross_division_exception_runs\<latest run>\
review_input\employee_capacity_and_cross_division_exception_review.csv
```

This stage remains supervisor review only.
