# TTE Development Allocation Consolidation v13.0.8

This stage continues the project without claiming that unfinished
employee home-code reviews are complete.

It creates full allocation CSVs, scenario summaries, estate/scenario
files, exception files, and structural/safety gates.

## Run

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_DEVELOPMENT_ALLOCATION_v13.0.8.ps1
.\CHECK_DEVELOPMENT_ALLOCATION_v13.0.8.ps1
.\OPEN_DEVELOPMENT_ALLOCATION_v13.0.8.ps1
```

Expected gate:

```text
READY_FOR_MANAGEMENT_SIMULATION_REVIEW_WITH_OPEN_HOME_CODE_EXCEPTIONS
```

Open exceptions remain visible:

- 95 assigned-field rows without an official development reference code.
- 1,508 assignment rows linked to ambiguous employee home codes.
- 945 affected employees.
- Zero current cross-division exception rows.

All attendance, leave, fitness, operational-use and live-assignment
flags remain NO.
