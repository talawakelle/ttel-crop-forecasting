# Improvements in v1.4 — Selective Hybrid RL

## Problem corrected

The v1.3 full dynamic RL candidate followed the hard rules but was rejected because it reduced total coverage, lost to dynamic greedy and moved too many employees. Training the same design for more steps was therefore not appropriate.

## New architecture

- CP-SAT remains the morning optimizer.
- Budgeted dynamic greedy is the main intraday planner.
- RL receives only uncertain proposed moves.
- RL chooses between accepting the proposal and keeping the current assignment.
- High-margin decisions are automatically handled by greedy.
- Movement is capped at 15% of considered workers, no more than 15 total and no more than 10 in one replanning round.
- A conservative whole-plan comparison can replace the raw RL plan with budgeted greedy before deployment.

## Reward correction

The new reward prioritises:

1. Coverage relative to budgeted dynamic greedy.
2. Coverage relative to no replanning.
3. Remaining close to unrestricted dynamic greedy.
4. Fewer unnecessary movements.
5. Weak-field coverage only after total coverage is protected.

## Training correction

- Smaller binary action space.
- Three-seed tournament.
- Easy, medium, full and mixed curriculum.
- Chronological train, validation and untouched test splits.
- Separate extreme-disruption test.
- Coverage, non-inferiority, downside, movement and safety gates.
- Exact source-code, data, forecast and model fingerprints.

## Script correction

PowerShell training wrappers now propagate Python failures correctly. A rejected candidate can no longer be followed by a false “approved model created” message.
