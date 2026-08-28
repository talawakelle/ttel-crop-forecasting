# Validation — v1.5.0

## Build checks completed

- Python compilation: passed for `backend` and `scripts`.
- JavaScript syntax: passed for `web/assets/app.js`.
- FastAPI import and `/api/model` status construction: passed.
- Historical profile: 650 employees, 36 fields, 3 divisions and 415,920 usable weighments.
- CatBoost forecast: ready; test MAE 4.3266 kg versus 4.6160 kg historical baseline.
- Crop forecast: loaded, but stale after 12 July 2026.
- Unit suite: 28 passed and 11 dependency-gated tests skipped in the build container.
- Selective architecture smoke benchmark: 240 episodes and zero hard-rule violations.

## Architecture benchmark interpretation

The benchmark uses fixed accept-all and veto-all behaviours. It tests the movement budget, masks, fallback and accounting. It is not evidence that a trained RL model is approved.

Accept-all reproduces budgeted dynamic greedy. In full-disruption smoke testing it retained almost all unrestricted-greedy coverage while reducing average movements from 20.525 to 13.575.

## Still required

- Train three v1.5 candidates on the NVIDIA GPU.
- Select the best candidate using chronological validation only.
- Pass the untouched test and extreme-stress gates.
- Conduct an actual estate shadow trial before operational approval.
