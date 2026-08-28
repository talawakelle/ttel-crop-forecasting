# TTE Division Identity Normalization v13.0.2

This stage repairs the division comparison used in the v13.0.1 named
plucker allocation.

The source allocation stores:

```text
division                 = full assigned division name
inferred_home_division   = short home-division code
```

These values must be normalized before cross-division movement is
interpreted.

## Run the review-pack creator

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_DIVISION_IDENTITY_NORMALIZATION_v13.0.2.ps1
.\CHECK_DIVISION_IDENTITY_NORMALIZATION_v13.0.2.ps1
.\OPEN_DIVISION_MAPPING_REVIEW_v13.0.2.ps1
```

## Complete the mapping file

Open:

```text
review_input\division_identity_mapping_review.csv
```

For every row:

1. Check `suggested_division_name`.
2. Enter the correct full name in `confirmed_division_name`.
3. Set `manager_confirmed` to `YES`.
4. Enter `reviewer_name`.
5. Enter `reviewed_at`.
6. Keep `live_assignment_authorized` as `NO`.

Suggestions are not approvals and must not be auto-confirmed.

## Validate after review

```powershell
.\VALIDATE_DIVISION_IDENTITY_NORMALIZATION_v13.0.2.ps1
.\CHECK_DIVISION_IDENTITY_NORMALIZATION_v13.0.2.ps1
```

Required gate:

```text
READY_FOR_SUPERVISOR_EXPECTED_ALLOCATION_REVIEW
```

Then open:

```powershell
.\OPEN_NORMALIZED_PLUCKER_ALLOCATIONS_v13.0.2.ps1
```

Outputs:

```text
expected_primary_named_plucker_allocation.csv
conservative_backup_named_plucker_allocation.csv
all_normalized_named_plucker_allocations.csv
```

This stage remains review-only. It does not verify current attendance,
leave, fitness, movement permission or live employee availability.
