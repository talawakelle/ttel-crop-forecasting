# TTE Balanced Baseline Review v8.0.1

The v8.0.0 comparison used a fixed 0.5 kg noninferiority tolerance. That is
too sensitive for estate-scenario crop totals measured in thousands of
kilograms.

v8.0.1 keeps the old result visible but adds a material safety gate.

## Material tolerance

```text
max(2 kg, 0.05% of estate-scenario crop)
```

CP-SAT must also meet all of these:

```text
No uncovered fields
No duplicate employee assignments
Estate-scenario shortfall rate no more than 0.10%
At least 80% material noninferiority
```

## Run

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_BALANCED_BASELINE_REVIEW_v8.0.1.ps1
.\CHECK_BALANCED_BASELINE_REVIEW_v8.0.1.ps1
```

Possible result:

```text
READY_FOR_RL_ENVIRONMENT_DESIGN
```

This permits environment design only. It does not start or approve RL.
