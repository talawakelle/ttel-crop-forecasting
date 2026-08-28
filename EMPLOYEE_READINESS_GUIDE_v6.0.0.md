# TTE Employee Readiness Layer v6.0.0

This is the next stage after the final v5.0.3 crop and plucker-demand plan.

## What it builds

- employee master from all 33 compressed productivity training files
- employee-field experience register
- first-date employee availability template
- employee constraint template
- first-date field/employee historical candidate matrix
- field candidate coverage report
- CP-SAT input readiness gate

## Method

- reads `productivity_training.csv.gz` for all 33 estates
- estimates estate-specific 1st and 99th percentile clipping limits
- builds historical employee, employee-division and employee-field statistics
- infers home division from modal observed field division when source is `UNK`
- gives priority to field experience, then division experience, then estate history
- applies recency, experience and activity weighting
- creates a candidate matrix only; it does not allocate named employees

## Run

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_EMPLOYEE_READINESS_v6.0.0.ps1
```

## Check

```powershell
.\CHECK_EMPLOYEE_READINESS_v6.0.0.ps1
```

## Required management input

Open and complete:

- `templates\employee_availability_template.csv`
- `templates\employee_constraints_template.csv`

Use:

- available_status: `AVAILABLE` or `UNAVAILABLE`
- leave_status: `NONE` or `ON_LEAVE`
- medically_fit_for_plucking: `YES` or `NO`
- supervisor_confirmed: `YES`
- cross_division_allowed: `YES` or `NO`
- restriction_status: `NONE` or `RESTRICTED`

Then run:

```powershell
.\RECHECK_EMPLOYEE_INPUT_READINESS_v6.0.0.ps1
```

CP-SAT remains blocked until the recheck passes.
