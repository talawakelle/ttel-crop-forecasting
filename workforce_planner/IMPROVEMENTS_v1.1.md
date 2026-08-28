# Improvements in v1.1

## Forecasting

- Packaged a verified CatBoost model rather than silently relying on historical medians.
- Preserved chronological train/validation/test separation.
- Improved untouched test MAE from 4.6160 kg to 4.3266 kg.
- Added per-assignment forecast confidence and uncertainty.
- Added a 120-day maximum forecast horizon to stop uncontrolled extrapolation.
- Preserved historical-median fallback when the model, fingerprint or horizon is invalid.

## Reinforcement learning

- Bumped RL model schema from 2 to 3; older policies cannot be loaded accidentally.
- Wired the approved CatBoost model into RL training, evaluation and inference.
- Added forecast confidence, fill state and shortage risk to the RL observation.
- Added scarcity-aware marginal coverage reward.
- Penalised oversupply, avoidable idling and opportunity regret.
- Broadened scenario randomisation for attendance, demand and division rules.
- Added paired win-rate, median, p10 and worst-case comparisons against the baseline.
- Added a strict activation gate and automatic rejection report.
- Bound the RL model to the exact CatBoost model hash.

## Optimizer and baseline

- Strengthened the greedy benchmark with forecast confidence and field demand pressure.
- Added forecast confidence as a CP-SAT secondary preference when coverage is equal.
- Kept the hybrid selector: a weaker RL plan is never forced into use.
