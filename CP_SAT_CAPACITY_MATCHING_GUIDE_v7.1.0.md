# TTE CP-SAT Capacity Matching Repair v7.1.0

The earlier v7.0.0 run passed structural solver checks, but its employee
capacity coverage was poor.

Two corrections are included:

1. Field identity is `estate + division + field`.
2. Forecasted plucker demand is a soft reference, not a hard field maximum.

The optimizer now considers every unique employee identity for every active
field in the same estate. Exact-field and home-division experience receive
preference, while cross-division choices receive a penalty.

Every employee master record remains in the audit roster. Duplicate copies of
the same employee ID are not treated as separate workers because that could
double-assign one identity.

## Run

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\PREFLIGHT_CP_SAT_CAPACITY_MATCHING_v7.1.0.ps1
.\START_CP_SAT_CAPACITY_MATCHING_v7.1.0.ps1
.\CHECK_CP_SAT_CAPACITY_MATCHING_v7.1.0.ps1
```

Expected structural values:

```text
active_field_rows: 447
expected_field_result_rows: 894
actual_field_result_rows: 894
field_identity_failures: 0
solver_failures: 0
duplicate_employee_assignment_failures: 0
field_reconciliation_failures: 0
```

A structural PASS is not the same as an operational approval. Review the
scenario coverage percentages and field exceptions before building the greedy
baseline or RL environment.
