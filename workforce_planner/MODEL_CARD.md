# Model Card — TTE Employee Planner v1.5

## Crop-demand input

- Source: Clarendon four-week plantation crop-forecast pilot.
- Output: estate-level weekly net green-leaf kilograms with lower, central and upper ranges.
- Field demand: weekly estate demand is distributed using the selected historical field/day template; it is not a true field-level crop forecast.
- Bundled period: 15 June–12 July 2026; refresh required for current planning.

## Employee-productivity model

- Algorithm: CatBoost regression.
- Output: expected employee-field kilograms and a conservative uncertainty-adjusted estimate.
- Test MAE: 4.3266 kg.
- Historical baseline MAE: 4.6160 kg.
- Improvement: 6.27%.
- Intended use: planning support, not payroll, discipline or employee appraisal.

## Morning allocation

- Primary method: OR-Tools CP-SAT.
- Fallback: forecast-aware greedy.
- Static RL remains research-only unless separately approved.

## Selective hybrid intraday model

- Primary intraday planner: budgeted dynamic greedy.
- RL algorithm: MaskablePPO with a binary action space.
- RL actions: accept the proposed greedy move or veto it and keep the current field.
- Decision timing: midday and afternoon only.
- Movement limits: maximum 15% of workers, 15 total and 10 per round.
- Safety: action masking, one-move rule, cross-division limits and conservative global fallback.
- Included trained model: none.
- Required evidence: untouched simulation approval followed by actual shadow-mode validation.

## Known limitations

- Historical rows can include partial-day employee-field output when one employee worked in several fields.
- Attendance is simulated unless actual attendance is supplied.
- Crop demand remains estate-week level and is allocated to fields through historical templates.
- Simulated counterfactual performance does not prove real operational improvement.
- Confidence estimates are decision-support indicators, not guaranteed prediction intervals.

## Prohibited uses

- Automatic payroll or disciplinary decisions.
- Unsupervised live employee movement.
- Treating the stale crop forecast as current.
- Treating simulation approval as production approval.


## v1.5 decision rule
The default is budgeted dynamic greedy. RL is permitted to veto only when the calibrated veto probability threshold is met; low-confidence vetoes are automatically converted to greedy acceptance.
