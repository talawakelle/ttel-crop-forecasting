# TTE Protected Shadow Backtest v11.0.0

This stage uses the completed v10 development RL model.

## Routing

```text
5 reviewed estate-scenarios -> GREEDY_FALLBACK
61 validated estate-scenarios -> PROTECTED_HYBRID_RL
```

The five fallback episodes are read from:

```text
v10 run\evaluation\five_estate_scenario_review_cases.csv
```

## Replay coverage

```text
66 estate-scenario episodes
6 deterministic shock sets per episode
396 routed episode-shock cases
```

Policies compared:

```text
CP-SAT no replan
Greedy
RL only
Protected hybrid RL
Final routed shadow policy
```

## Required gates

```text
Unseen SHOCK_05 routed noninferiority = 100%
All-case routed noninferiority >= 95%
Safety violations = 0
Duplicate assignments = 0
No-shock baseline degradation = 0
```

## Run

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_PROTECTED_SHADOW_BACKTEST_v11.0.0.ps1
.\CHECK_PROTECTED_SHADOW_BACKTEST_v11.0.0.ps1
```

A passing gate allows supervisor shadow review only.

This is a replay of deterministic simulated shocks. It is not observed
historical performance and it does not approve live employee assignments.
