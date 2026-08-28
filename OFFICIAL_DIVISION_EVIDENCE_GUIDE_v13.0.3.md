# TTE Official Division Evidence Intake v13.0.3

This stage replaces system-generated division guesses with official
source-document evidence.

It supports both:

```text
one code -> one valid division
one code -> several valid divisions in an approved division group
```

## Create the evidence intake pack

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_OFFICIAL_DIVISION_EVIDENCE_v13.0.3.ps1
.\CHECK_OFFICIAL_DIVISION_EVIDENCE_v13.0.3.ps1
.\OPEN_OFFICIAL_DIVISION_EVIDENCE_v13.0.3.ps1
```

## Main evidence input

```text
review_input\official_division_code_evidence_input.csv
```

For every candidate division row:

```text
include_as_valid_mapping = YES or NO
```

For every YES row, complete:

```text
mapping_scope = SINGLE_DIVISION or DIVISION_GROUP
source_document_name
source_document_date
source_sheet_or_page
source_row_or_cell_reference
source_document_owner
approved_by
approved_at
evidence_status = VERIFIED
```

Keep:

```text
operational_use_allowed = NO
live_assignment_authorized = NO
```

Acceptable evidence includes an approved division master, approved
cost-centre master, employee home-division register, HR master, or an
estate-manager-approved division register.

Generated suggestions and allocation history are not official evidence.

## Priority evidence file

```text
review_input\priority_unresolved_division_evidence.csv
```

This is a working view of the four current unresolved keys. Enter final
decisions only in `official_division_code_evidence_input.csv`.

## Validate after official evidence is entered

```powershell
.\VALIDATE_OFFICIAL_DIVISION_EVIDENCE_v13.0.3.ps1
.\CHECK_OFFICIAL_DIVISION_EVIDENCE_v13.0.3.ps1
```

Required gate:

```text
READY_FOR_SUPERVISOR_EXPECTED_ALLOCATION_REVIEW
```

Then open:

```powershell
.\OPEN_OFFICIALLY_NORMALIZED_ALLOCATIONS_v13.0.3.ps1
```

Outputs:

```text
expected_primary_officially_normalized_allocation.csv
conservative_backup_officially_normalized_allocation.csv
all_officially_normalized_allocations.csv
```

This stage does not verify attendance, leave, fitness, movement
permission, current availability or live assignment authorization.
