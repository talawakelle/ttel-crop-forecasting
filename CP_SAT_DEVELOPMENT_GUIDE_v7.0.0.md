# TTE CP-SAT Development Allocation v7.0.0

This stage performs estate-wise employee-to-field matching for the first
planning date.

## Allocation logic

The optimizer considers all candidate employees across the whole estate.

It prioritizes:

1. minimum crop left uncovered
2. minimum excess employee capacity
3. fewer employees when two solutions cover the same crop
4. exact-field history
5. same-division history
6. lower use of cross-division fallback

Each employee can be assigned to at most one field in each scenario.

Example:

- Field 3A crop: 80 kg
- Rani: 40 kg
- Kamala: 40 kg
- Vimala: 80 kg
- Sunil: 100 kg

The global optimizer can choose Vimala, or Rani plus Kamala, while preserving
Sunil for a field closer to 100 kg.

## Scenarios

- EXPECTED: central crop and expected plucker limit
- CONSERVATIVE: upper crop and recommended plucker limit

## Run

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\PREFLIGHT_CP_SAT_DEVELOPMENT_v7.0.0.ps1
.\START_CP_SAT_DEVELOPMENT_v7.0.0.ps1
.\CHECK_CP_SAT_DEVELOPMENT_v7.0.0.ps1
```

The start script installs OR-Tools through pip when it is missing.

## Safety boundary

This uses the all-employee provisional scenario. It is not a live roster.
Availability, leave, medical fitness and restrictions remain unverified.
RL training is not started.
