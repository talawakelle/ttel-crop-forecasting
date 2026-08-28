# TTE Pooled Hierarchical Technical-Method Planning v5.0.2

## Correct interpretation

The project continues planning for all 33 estates.

- Bambarakelly: pooled hierarchical seasonal-transfer method
- Tillicoultry: pooled hierarchical seasonal-transfer method
- EildonHall: pooled hierarchical seasonal-transfer method
- Other 30 estates: continue the existing gate-based planning methods

This version does not select matching donor estates.

## Technical method for the three estates

The method learns a pooled seasonal pattern from the combined history of the
other estates, then transfers that pattern to each target estate using its own:

- recent crop level
- weekday pattern
- recent trend
- available history

Three pooled variants are backtested separately for each target estate:

1. pooled month-weekday level
2. pooled pattern with own-weekday shrinkage
3. pooled trend-damped hybrid

The lowest-WAPE technical variant is selected for each of the three estates.

## Run

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_POOLED_HIERARCHICAL_PLANNING_v5.0.2.ps1
```

## Check

```powershell
.\CHECK_POOLED_HIERARCHICAL_PLANNING_v5.0.2.ps1
```

## Outputs

- `quality\pooled_hierarchical_backtest.csv`
- `quality\method_and_gate_register.csv`
- `planning\estate_required_plucker_assignments.csv`
- `planning\division_crop_and_plucker_demand.csv`
- `planning\field_required_plucker_assignments.csv`

## Safety

The project continues for all estates, but results remain development/scenario
planning because the source data is stale. No portal, named employee allocation,
CP-SAT or RL process is started.
