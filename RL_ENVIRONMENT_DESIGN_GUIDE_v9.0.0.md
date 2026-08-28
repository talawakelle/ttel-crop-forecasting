# TTE Safe RL Environment Design v9.0.0

This package creates and smoke-tests the reinforcement-learning environment. It does not train an RL model.

## Structure

- 66 base episodes: 33 estates × EXPECTED and CONSERVATIVE scenarios
- CP-SAT development allocation is the starting baseline
- Greedy remains the comparison benchmark
- Six states per episode: baseline plus five deterministic crop/productivity shock simulations

## Actions and safety

An action moves one assigned employee to another field in the same estate. The safety shield requires a valid employee-field edge, prevents duplicate or cross-estate assignment, blocks materially harmful moves, and always permits `NO_OP`.

## Run

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_RL_ENVIRONMENT_DESIGN_v9.0.0.ps1
.\CHECK_RL_ENVIRONMENT_DESIGN_v9.0.0.ps1
```

Required results:

```text
Status: PASS_RL_ENVIRONMENT_DESIGN
Episodes: 66
Baseline field rows: 894
Duplicate assignment failures: 0
Smoke-test failures: 0
Safety-gate failures: 0
Environment ready for training code: True
RL started: False
```
