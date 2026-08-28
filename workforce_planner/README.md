# TTE Employee Planner — Conservative High-Confidence Hybrid RL v1.5.0

This release redesigns intraday reinforcement learning after the v1.3 full-allocation policy was correctly rejected. The new system does **not** allow RL to reorganise the whole workforce.

## Planning hierarchy

1. A refreshed estate crop forecast estimates expected crop demand.
2. CatBoost estimates employee-field productivity and uncertainty.
3. CP-SAT creates the morning allocation when OR-Tools is available.
4. Budgeted dynamic greedy creates the main midday and afternoon reallocation plan.
5. Selective MaskablePPO reviews only uncertain proposed moves.
6. Hard movement limits and a conservative safety check automatically fall back to budgeted dynamic greedy when necessary.

## Why v1.5 is safer

The rejected v1.3 policy moved too many employees and produced lower untouched-test coverage than the comparison methods. v1.5 changes the role of RL:

- RL has only two choices: **accept the greedy proposal** or **veto it and keep the current field**.
- High-confidence decisions are completed automatically by dynamic greedy.
- RL is consulted only for uncertain, reserve or cross-division decisions.
- Maximum total reassignments: the lower of **15 workers or 15% of workers considered**.
- Maximum reassignments in one round: **10 workers**.
- One voluntary movement per employee remains enforced.
- Invalid, inactive, over-capacity and prohibited cross-division actions remain masked.
- A global conservative comparison falls back to the budgeted greedy plan when the raw RL plan is forecast-inferior.
- Comparator outcomes and future simulated output are not placed in the policy observation.

## Build-time architecture benchmark

`models/selective_hybrid_safety_benchmark.json` is a smoke benchmark, not a trained-policy result.

Across 80 full-disruption accept-all episodes, budgeted dynamic greedy averaged:

- 58.427% simulated crop coverage.
- 0.798 percentage-point gain over no replanning.
- 13.575 reassignments versus 20.525 for unrestricted dynamic greedy.
- Only 0.098 percentage points below unrestricted dynamic greedy.
- Zero hard-rule violations.

This confirms that the movement budget preserves most of the greedy benefit before RL training. A newly trained v1.5 model must still pass untouched testing.

## First-time installation

Double-click:

```text
RUN_FIRST_TIME.bat
```

For later use:

```text
START_PLANNER.bat
```

Open:

```text
http://127.0.0.1:8090
```

## Train the v1.5 selective hybrid model

Run PowerShell in the project folder:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup_gpu_windows.ps1
```

Then double-click:

```text
TRAIN_HYBRID_RL_GPU.bat
```

Default training tournament:

```text
Easy       100,000 steps
Medium     150,000 steps
Full       250,000 steps
Mixed      200,000 steps
Total      700,000 steps per candidate
3 candidates = 2,100,000 total steps
```

Approved output:

```text
models\selective_hybrid_maskable_ppo.zip
models\selective_hybrid_training_metrics.json
```

Rejected output:

```text
models\selective_hybrid_training_rejected.json
```

A rejected candidate is not installed.

## Re-evaluate an approved model

Double-click:

```text
EVALUATE_HYBRID_RL.bat
```

The model must pass all untouched-test and extreme-stress gates again.

## Approval requirements

The v1.5 candidate is installed only when all gates pass, including:

- Zero hard-rule violations.
- Positive mean gain versus no replanning.
- No mean loss versus budgeted dynamic greedy.
- At least 80% non-inferiority rate versus budgeted dynamic greedy.
- Bounded downside and bootstrap non-inferiority.
- No more than 15% mean reassignment rate and no more than 15 mean moves.
- Within 0.50 percentage points of unrestricted dynamic greedy.
- Measurable extra value through either coverage improvement or fewer movements.
- Non-negative extreme-stress gain versus no replanning.
- Untouched chronological test evaluation.

Passing means **simulation-approved only**. Live estate use still requires shadow-mode evidence and supervisor approval.

## Optional architecture check

Before training, run:

```text
BENCHMARK_HYBRID_SAFETY.bat
```

It produces:

```text
models\selective_hybrid_safety_benchmark.json
```

## Crop forecast warning

The bundled Clarendon demonstration forecast covers 15 June–12 July 2026 and is stale for current planning. Import a refreshed crop-forecast workbook using:

```text
IMPORT_CROP_FORECAST.bat
```

## Honest status

- CatBoost productivity model: packaged and active.
- CP-SAT morning planner: active when OR-Tools is installed.
- Budgeted dynamic-greedy safety architecture: implemented and smoke-tested.
- Selective hybrid RL training/evaluation pipeline: implemented.
- Approved v1.5 RL model: **not packaged**; GPU training is required.
- Operational shadow approval: **not completed**.
- Actual attendance and intraday weighment data remain necessary for production use.


## v1.5 confidence rule
Budgeted dynamic greedy is the default. RL can veto a proposed movement only when its masked action probability exceeds the validation-calibrated threshold. Otherwise the greedy move is retained.
