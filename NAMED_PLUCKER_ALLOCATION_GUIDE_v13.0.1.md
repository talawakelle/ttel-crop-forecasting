# TTE Named Plucker Allocation KG Repair v13.0.1

The uploaded v13.0.0 output had correct identities and assignments, but
all three kg columns were blank.

v13.0.1 maps the exact v7.1 CP-SAT columns:

```text
target_crop_kg                 -> field_crop_kg
expected_productivity_kg       -> plucker_capacity_kg
field_assigned_capacity_kg     -> field_assigned_capacity_kg
field_under_kg                 -> field_under_kg
field_over_kg                  -> field_over_kg
```

Run:

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_NAMED_PLUCKER_ALLOCATION_v13.0.1.ps1
.\CHECK_NAMED_PLUCKER_ALLOCATION_v13.0.1.ps1
.\OPEN_NAMED_PLUCKER_ALLOCATION_v13.0.1.ps1
```

Required kg gates:

```text
MISSING_FIELD_CROP_KG                 0
MISSING_PLUCKER_CAPACITY_KG           0
MISSING_FIELD_ASSIGNED_CAPACITY_KG    0
```

The allocation remains simulation-only:

```text
actual_supervisor_verified = NO
operational_use_allowed = NO
live_assignment_authorized = NO
```
