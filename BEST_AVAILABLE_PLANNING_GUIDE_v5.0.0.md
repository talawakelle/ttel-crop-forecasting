# TTE Best-Available Existing-Data Planning Outputs v5.0.0

This stage accepts the user's instruction to use the currently available data only.

## Method

The package does not simply use one weak daily baseline for every estate.

It applies:

- WAPE-gated ensemble selection for accepted estates
- Broader robust ensembles for review/provisional estates
- Recent-history fallback for short-history and rejected daily baselines
- Larger uncertainty ranges for weaker gates and stale source data
- Historical active-field counts, weekday frequency and plucking-due score
- Field productivity with shrinkage to division/estate history
- Conservative crop and productivity values for recommended plucker assignments
- Exact estate-to-field reconciliation

## Outputs

- `planning\estate_crop_planning.csv`
- `planning\estate_required_plucker_assignments.csv`
- `planning\division_crop_and_plucker_demand.csv`
- `planning\field_crop_planning.csv`
- `planning\field_required_plucker_assignments.csv`
- `quality\method_and_gate_register.csv`
- `quality\field_schedule_diagnostics.csv`
- `quality\hierarchy_reconciliation.csv`
- `run_summary.json`

## Interpretation

`recommended_plucker_assignments` means headcount-equivalent field assignments.
It is not yet a list of named employees.

A unique employee roster still requires attendance, leave, skills, medical
restrictions, home division, allowed movements and CP-SAT.

## Install and run

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_BEST_AVAILABLE_PLANNING_OUTPUTS_v5.0.0.ps1
```

## Check

```powershell
.\CHECK_BEST_AVAILABLE_PLANNING_OUTPUTS_v5.0.0.ps1
```

## Safety

- Existing crop models remain unchanged.
- Existing productivity models remain unchanged.
- The manager portal remains unchanged.
- CP-SAT is not started.
- RL is not started.
- Outputs remain explicitly labelled as development/scenario planning because
  the available source data is stale.
