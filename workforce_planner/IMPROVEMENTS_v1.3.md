# Improvements in v1.3 — Robust Dynamic RL

## Environment

- Replaced the one-pass disruption model with morning, midday and afternoon stages.
- Added progressive reserve release, late absence and late demand revisions.
- Added easy, medium, full, extreme and mixed disruption domains.
- Added uncertainty-adjusted productivity and pending-workforce state features.
- Removed future comparator metrics from the observation.
- Corrected cross-division budgeting to count unique new transfers.
- Added repeat-move controls and field-floor coverage rewards.
- Added empty-stage handling and deterministic reset checks.

## Training

- Three-way chronological train/validation/test split.
- Multi-seed candidate tournament.
- Validation checkpoint selection without touching the final test set.
- Extreme stress evaluation.
- Bootstrap confidence interval for the mean gain.
- Robust score including coverage, field-floor gain, win rate and greedy comparison.
- Stronger approval gates and automatic candidate rejection.

## Deployment safety

- Dynamic models are fingerprinted against the workforce profile, CatBoost model, crop forecast, environment source and training source.
- The application refuses a stale or code-incompatible model.
- Simulation approval and operational shadow approval are reported separately.
- The perfect-information greedy comparator is explicitly labelled as a reference, not a certified mathematical upper bound.

## Remaining work

- Run the GPU tournament.
- Collect actual midday and afternoon plan-versus-result data.
- Calibrate disruption distributions using observed absence, transfer, weather and field-output errors.
- Complete shadow-mode approval before any automated operational recommendation.
