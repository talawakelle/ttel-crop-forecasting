# TTE Safe Development RL Training v10.0.0

The v9 RL environment passed all design and smoke-test gates.

## Training and evaluation split

```text
Training: SHOCK_01 to SHOCK_04
Validation: SHOCK_05
No-shock safety test: SHOCK_00_BASELINE
```

The model is an action-conditioned safe Q-network.

The protected hybrid policy uses an RL move only when its immediate safe
reward is at least 95% of the safe greedy move. Otherwise it falls back to
greedy.

## Gates

```text
No training safety violations
No validation safety violations
No duplicate employee assignments
No degradation on no-shock baseline episodes
At least 80% noninferiority to greedy on unseen SHOCK_05
```

## Run

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_SAFE_RL_TRAINING_v10.0.0.ps1
.\CHECK_SAFE_RL_TRAINING_v10.0.0.ps1
```

A successful development result is:

```text
Policy gate: CANDIDATE_FOR_SHADOW_BACKTEST
RL training completed: True
Live deployment started: False
```

All 23,043 employees were considered during the CP-SAT capacity stage. The
RL stage learns safe reallocation from the selected CP-SAT baseline. It does
not require every employee to be assigned.

Named employee recommendations remain development-only until attendance,
leave, fitness and movement restrictions are confirmed.
