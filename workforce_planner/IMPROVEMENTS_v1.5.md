# Improvements in v1.5 — Conservative High-Confidence Hybrid RL

## Main change
Budgeted dynamic greedy is now the default decision for every uncertain move. The RL policy may override that decision only by issuing a veto with very high masked-policy confidence.

## Confidence calibration
Each trained candidate is tested on the held-out validation period at thresholds 0.80, 0.85, 0.90, 0.95 and 0.98. The safest value-adding threshold is frozen before the untouched test period is opened.

## Safety behavior
- Low-confidence RL veto -> automatically keep the greedy move.
- High-confidence RL veto -> apply only when the existing safety shield permits it.
- Hard movement budgets and conservative whole-plan fallback remain active.
- Untouched test approval still requires all safety gates.

## New diagnostics
Training metrics report the selected confidence threshold, raw RL vetoes, low-confidence vetoes overridden and high-confidence vetoes applied.

## Important
A trained v1.5 model is not included. GPU training and untouched-test approval are required. Actual deployment still requires estate shadow mode.
