# GPU Crop Forecasting — All 33 Estates

This upgrade is for the **crop forecasting models**, not the workforce RL model.

For every estate and each 1–4 week horizon, the pipeline trains and compares:

- Weather + crop GPU CatBoost;
- Crop-only GPU CatBoost;
- CPU gradient boosting and random forest controls;
- same week last year;
- recent four-week mean.

The selected result is the method with the lowest chronological validation WAPE. GPU is used as a candidate for every estate/horizon, but it is not selected merely because it used the GPU.

The TRI and Pedro weather workbooks are converted once into reusable daily caches at the beginning of the run. This avoids reopening the large sensor workbooks for every estate.

Completed PROMPT estate/day actuals are added through yesterday. The current day is excluded to prevent partial-day crop from entering training. Employee identifiers are not used by this crop model.

The runner freezes one `prompt_daily_actuals_snapshot.csv` at startup. If the
scheduled 7:00 AM sync occurs before training ends, it cannot change the data
cutoff for later estates in the same batch.

Eildon Hall and Tillicoultry retain the pooled short-history guardrail and train pooled GPU candidates using same-plantation/same-weather-station donors. The run never labels an estate or manager as best practice.

## Required local inputs

1. One valid output ZIP for each of the 33 estates in one folder tree.
2. TRI-Thalawakele base and update weather workbooks.
3. Pedro/Nuwara Eliya weather workbook.
4. Refreshed `outputs\prompt_daily_actuals.csv`.
5. NVIDIA GPU visible to `nvidia-smi` and Python 3.12.

## Easiest Windows start

Run `START_ALL_33_GPU_OVERNIGHT.ps1` from the project folder. It opens Windows
selection dialogs for the crop ZIP folder and the two weather-station inputs,
then temporarily prevents sleep while the job runs. It restores normal sleep
behaviour when the job finishes or fails.

Use `CHECK_ALL_33_GPU_RESULTS.ps1` in the morning. A successful actual-data sync
or workforce/RL GPU run is separate and does not count as all-estate crop GPU
training.

## Safety

Training writes only to `outputs\gpu_candidates_<timestamp>`. It does not replace live portal forecasts. Inspect `gpu_batch_summary.csv`, `portfolio_summary.csv`, all model metrics and the morning result table before promotion.

The Actual line does not require GPU training. The Best-Practice line remains unavailable until real field master, fertilizer, foliar, sundry-work and practice-outcome evidence passes its own validation.
