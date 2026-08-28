# TTE Code-Only Division Normalization v13.0.4

This stage does not require an official long division name.

It uses:

```text
official assigned division code
versus
employee home division code
```

The allocation's existing division text is retained only as context so
that fields with the same field code can be distinguished.

## Create the code-only evidence pack

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_CODE_ONLY_DIVISION_NORMALIZATION_v13.0.4.ps1
.\CHECK_CODE_ONLY_DIVISION_NORMALIZATION_v13.0.4.ps1
.\OPEN_CODE_ONLY_DIVISION_EVIDENCE_v13.0.4.ps1
```

## Complete this file

```text
review_input\official_field_division_code_input.csv
```

For every row, enter:

```text
official_assigned_division_code
source_document_name
source_document_date
source_sheet_or_page
source_row_or_cell_reference
source_document_owner
verified_by
verified_at
evidence_status = VERIFIED
```

Keep:

```text
employee_home_code_verified = NO
operational_use_allowed = NO
live_assignment_authorized = NO
```

A long division name is not required in the official source document.

`allocation_division_context` is not official evidence. It is retained
only to distinguish allocation field records.

## Validate after entering official field codes

```powershell
.\VALIDATE_CODE_ONLY_DIVISION_NORMALIZATION_v13.0.4.ps1
.\CHECK_CODE_ONLY_DIVISION_NORMALIZATION_v13.0.4.ps1
```

Required next gate:

```text
READY_FOR_EMPLOYEE_HOME_CODE_SUPERVISOR_REVIEW
```

This gate means the official field codes are complete. It does not mean
employee home codes, attendance, leave, fitness or movement permission
have been verified.

## Open comparison outputs

```powershell
.\OPEN_CODE_ONLY_NORMALIZED_ALLOCATIONS_v13.0.4.ps1
```

Outputs:

```text
expected_primary_code_only_division_comparison.csv
conservative_backup_code_only_division_comparison.csv
all_code_only_division_comparisons.csv
```

No employee notification or live allocation is authorized.
