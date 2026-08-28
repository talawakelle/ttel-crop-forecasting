# TTE CP-SAT vs Greedy Comparison v8.0.0

This stage creates the deterministic greedy baseline required before the RL
environment is designed.

## Clarendon-style comparison

The comparison uses an 80% CP-SAT noninferiority gate across:

```text
33 estates × 2 scenarios = 66 estate-scenarios
```

CP-SAT is noninferior when its uncovered crop is no more than 0.5 kg above
the greedy result for that estate and scenario.

## Run

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_CP_SAT_VS_GREEDY_v8.0.0.ps1
.\CHECK_CP_SAT_VS_GREEDY_v8.0.0.ps1
```

Required structural checks:

```text
Comparison rows actual: 66
Greedy field rows actual: 894
Greedy field identity failures: 0
Greedy duplicate employee failures: 0
```

Possible gate result:

```text
READY_FOR_RL_ENVIRONMENT_DESIGN
```

This permits the next development stage only. It does not start, approve or
deploy RL.
