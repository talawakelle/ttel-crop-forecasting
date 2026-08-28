# TTE Final Method-Gated Planning v5.0.3

## Final rule

All 33 estates continue through planning.

For Bambarakelly, Tillicoultry and EildonHall:

1. backtest the pooled hierarchical technical variants using the same number of
   observed test days recorded for the original candidate;
2. compare the best pooled WAPE with the original estate method WAPE;
3. select the lower-WAPE method independently for each estate.

All other estates continue with the existing gate-based planning methods.

## Expected selection from the comparison already observed

- Bambarakelly: keep `RECENT_SAME_WEEKDAY_MEDIAN`
- EildonHall: use `POOLED_TREND_DAMPED_HYBRID`
- Tillicoultry: use `POOLED_WITH_OWN_WEEKDAY_SHRINKAGE`

The script recalculates and confirms these choices rather than hard-coding them.

## Run

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_FINAL_METHOD_GATE_PLANNING_v5.0.3.ps1
```

## Check

```powershell
.\CHECK_FINAL_METHOD_GATE_PLANNING_v5.0.3.ps1
```

## Main outputs

- `quality\final_three_estate_method_gate.csv`
- `quality\pooled_hierarchical_backtest.csv`
- `quality\method_and_gate_register.csv`
- `planning\estate_required_plucker_assignments.csv`
- `planning\division_crop_and_plucker_demand.csv`
- `planning\field_required_plucker_assignments.csv`

No matching donor estates are used.
