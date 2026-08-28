# TTE Matching-Method Existing-Data Planning v5.0.1

## Corrected method rule

The following three estates use the matched-estate analog method:

- Bambarakelly
- Tillicoultry
- EildonHall

All other estates retain the v5 gate-based planning methods.

## How matching works

Each target is matched to three donor estates selected from the stronger
development candidates. Matching uses:

- recent daily crop scale
- crop variability
- recent trend
- weekday production pattern
- monthly production pattern
- division count
- field count

Each donor forecast is scaled to the target estate's recent crop level. The
three donor estimates are combined with the target estate's own recent-history
estimate.

The output includes:

`quality\matched_estate_register.csv`

This records every donor estate, matching distance and scale ratio.

## Run

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_MATCHING_METHOD_PLANNING_OUTPUTS_v5.0.1.ps1
```

## Check

```powershell
.\CHECK_MATCHING_METHOD_PLANNING_OUTPUTS_v5.0.1.ps1
```

## Safety

The available stale data is used as requested, but outputs remain labelled
development/scenario planning. No portal, named employee allocation, CP-SAT or
RL process is started.
