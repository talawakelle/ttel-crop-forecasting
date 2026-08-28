# TTE Movement Audit and Fallback Repair v11.0.1

This stage does not retrain the RL model.

It corrects the movement audit by counting accepted non-NO_OP
environment actions as the authoritative completed movement count.

The corrected objective is:

```text
1000 × undercoverage kg
+ 10 × overcapacity kg
+ accepted movement count
```

Routing rules:

```text
5 estate-scenario fallback rules from v10
13 exact scenario-estate-shock fallback rules from v11
All remaining cases use protected hybrid RL
```

Run:

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_MOVEMENT_AUDIT_REPAIR_v11.0.1.ps1
```

After completion:

```powershell
.\CHECK_MOVEMENT_AUDIT_REPAIR_v11.0.1.ps1
```

Required gate:

```text
All 396 routed cases noninferior to greedy: 100%
Unseen SHOCK_05 noninferiority: 100%
Safety violations: 0
Duplicate assignments: 0
No-shock baseline degradation: 0
Movement reconciliation failures: 0
Live deployment: False
```

Passing permits supervisor shadow review only.
