# Clarendon workforce coverage improvement diagnostic

## Executive answer

The 67.75% optimizer result cannot be improved by more RL or GPU training under
the same attendance, field capacity, crop targets, and division rules. It is
already the proven mathematical maximum in all 40 reference scenarios.

The strongest measured operational path is to improve attendance first and use
supervisor-approved cross-division deployment when needed. Together these
raised mean modeled coverage to 81.37%, a gain of 13.62 percentage points, with
zero hard-rule violations. This still does not guarantee an 85% average because
some high-demand days exceed the production available from the known workforce.

Version 1.0 operationalizes that finding: the supervisor enters the additional
workers and transfers genuinely available for the morning, and CP-SAT optimizes
inside those exact caps. The frontier remains diagnostic; only the separately
confirmed practical roster is intended for export.

## Evidence

| Decision option | Mean coverage | Gain vs strict | Days ≥85% | Interpretation |
| --- | ---: | ---: | ---: | --- |
| Current strict maximum | 67.75% | — | 4 / 40 | Baseline is already optimized |
| Allow division transfers | 71.50% | +3.75 | 6 / 40 | Useful secondary lever |
| Full known attendance | 77.56% | +9.81 | 13 / 40 | Largest single lever |
| Full attendance + transfers | 81.37% | +13.62 | 15 / 40 | Strongest practical tested option |
| Plus capacity and half-day splitting | 81.39% | +13.64 | 16 / 40 | Only +0.02 beyond combined; not worth complexity |

## Recommended operating sequence

1. Keep the strict CP-SAT plan as the safe default.
2. Confirm actual morning attendance before allocation.
3. If coverage remains low, calculate transfer candidates across divisions.
4. Require supervisor approval for each transfer and re-solve.
5. If the combined frontier remains below 85%, treat the gap as a real
   workforce/productivity shortage. Do not lower crop demand or inflate
   productivity to make the number look better.
6. Collect absence reasons, worker restrictions, skill eligibility, transport,
   and field-level crop estimates. These are the next data inputs most likely to
   improve decisions, rather than longer RL training.

## Metric definition

Coverage is:

`sum(min(predicted field kg, field target kg)) / sum(field target kg) × 100`

The diagnostic uses 40 fixed counterfactual scenarios sampled evenly across
complete Clarendon workdays from 2021-04-01 through 2026-06-15. Attendance
varies from 72% to 100%, demand from 85% to 115%, and seed 1042 fixes sampling.
Historical-median productivity reproduces the user's 67.75% benchmark. The
dashboard recalculates the frontier using the active approved forecast.

## Caveats

- These are modeled counterfactuals, not observed outcomes from a randomized
  deployment trial.
- A single TRI Thalawakelle station did not add verified forecast accuracy and
  remains disabled; the approved base CatBoost model is used.
- Some flexible searches reached the three-second limit before proving global
  optimality. Their plans were still feasible and had zero violations.
- Full attendance means the complete worker pool recorded for the selected
  template day, not all 650 historical employee profiles.
- Live leave, medical restrictions, skills, transport, and legal working-time
  rules must be added before production deployment.
