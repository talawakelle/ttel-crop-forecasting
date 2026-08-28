# TTE Integrated Crop, GAP and Workforce Planning Platform

This project combines the 33-estate crop forecasting system with the conservative Clarendon workforce-planner pilot in one estate-restricted manager portal. It forecasts weekly green-leaf crop, imports privacy-safe PROMPT actuals, collects GAP evidence, and exposes workforce readiness without authorizing automatic employee moves.

Start the complete Windows portal with:

```powershell
.\START_TTE_INTEGRATED_PLATFORM.ps1
```

Read `INTEGRATED_PROJECT_GUIDE.md` first. It contains the exact July 22 PROMPT refresh command, the three-line graph definition, workforce safety controls and current blockers.

## What the pilot proves

- All supplied estate crop records can be reconciled exactly to the annual workbook summaries.
- The mapped TRI-TW and PEDRO-NE station histories can be tested independently for every relevant estate.
- Direct models can forecast weeks 1–4 without using future actual crop or future observed weather.
- Each forecast horizon is accepted only if it beats the alternative methods during the final 26-week time-based validation period.

## Current checkpoint (2026-07-22)

- 33 supplied estate datasets are registered; 31 have standard estate-specific models and 2 have clearly labelled short-history pooled provisional models (132 forecast rows).
- 15,905,370 raw crop rows reconcile to the supplied annual summaries with a maximum absolute difference of 0 kg.
- EildonHall and Tillicoultry use pooled provisional forecasts because their usable non-zero histories are shorter than the standard-model guardrail.
- 31 mapped estates are physically nearest to TRI-TW; Pedro and NuwaraEliya are nearest to PEDRO-NE.
- Weather was tested and selected for 45 of 132 forecast horizons across 20 estates. It was rejected wherever crop-only, peer-seasonal or recent-trend methods validated better.
- Forecast origins range from 2025-12-28 to 2026-06-14, so every current output is marked `OUTDATED—REFRESH DATA` for operational use as of the checkpoint date.
- The manager portal contains 33 passwordless, estate-restricted accounts plus one portfolio administrator account.
- PROMPT automation supplied privacy-safe daily actual totals for all 33 estates from 1–12 July 2026; all workbook daily totals reconcile exactly.
- A five-year current-practice planning layer contains 60,258 estate-day rows. Years 4–5 are strategic scenarios, and the best-practice series remains inactive until the GAP input data is sufficient.
- All 33 workforce sources are audited with plantation + estate identity controls. The authenticated portal shows estate-specific readiness, crop-demand freshness and the conservative planner gates.
- The Clarendon v1.5 optimizer is preserved as the pilot reference. RL, GPU training, live reassignment and cross-estate model copying remain disabled until each estate passes its own validation and shadow approval.

## Important limits

- Nearest-station distance is a first-pass mapping. Weather is accepted for a forecast horizon only when it improves chronological validation.
- The original Pedro workbook is incomplete/corrupt. `Pedro_Estate_Nuwaraeliya(2).xlsx` is the valid replacement used for Pedro-station tests.
- The group rollout requires a confirmed estate master covering TTEL, KVPL, and HPL.
- The current checkpoint contains all 33 supplied estate datasets. EildonHall and Tillicoultry still need more non-zero history before their pooled provisional forecasts can be replaced by standard estate-specific models.
- Forecast intervals describe historical model error; they are not guarantees.

## Input requirements

Weather workbook sheet `All Records`:

- Center
- Date Recorded
- Time Recorded
- Air Temp (C)
- Humidity (%)
- Rainfall (mm)
- Optional sensor fields such as soil moisture, soil temperature, sunshine, light, wind, and UV

Crop workbook sheet `All Records`:

- date
- weighing_id
- original_weight
- net_weight
- w_status
- Optional division and field identifiers

The input may be a single crop workbook, a folder of workbooks, or a ZIP archive.

## Run

```bash
python train.py \
  --weather /path/to/TRI-Thalawakele.xlsx \
  --weather /path/to/TRI-Thalawakele_2026_06.xlsx \
  --crop /path/to/estate_crop_history.zip \
  --estate Clarendon \
  --output-dir outputs
```

Outputs include:

- `forecast.csv`
- `model_metrics.csv`
- `feature_importance.csv` when the selected model exposes feature importance
- `backtest_predictions.csv`
- `weekly_history.csv`
- `data_quality.json`
- `forecast_dashboard.html`
- one fitted model per selected machine-learning horizon

For a multi-estate batch, generate the consolidated readiness dashboard after the estate runs finish:

```bash
python build_portfolio_summary.py --today 2026-07-22
```

This creates `outputs/portfolio_dashboard.html`, `outputs/portfolio_summary.csv`, and `outputs/portfolio_forecasts.csv`.

## Modelling controls

- Target: total weekly net green-leaf kilograms
- Horizons: 1, 2, 3, and 4 weeks
- Validation: last 26 weeks, held out chronologically
- Selection: lowest validation WAPE among crop-plus-weather gradient boosting/random forest, crop-only gradient boosting/random forest, same week last year, and the recent four-week mean
- Weather value test: weather is retained only when crop-plus-weather beats the crop-only model on unseen recent weeks
- Leakage control: only crop and weather data known by the forecast origin are used
- Rainfall handling: daily maximum, because the supplied sensor values behave as a cumulative counter; raw sub-daily rainfall values must not be summed
- Short-history guardrail: at least 52 training weeks and 13 chronological validation weeks; shorter valid runs are explicitly labelled provisional
- Atomic model saving: a fitted model is replaced only after the new artifact has been fully written

## Short-history pooled fallback

EildonHall and Tillicoultry use a separate interim pathway. Their comparable donors are Alton, Bambarakelly, Fairlawn, Gouravilla, Mahanilu and Stockholm because the supplied data identifies all eight estates with plantation ID 7 and maps them to TRI-TW. Donors were not selected because of high crop.

The pooled model normalizes each estate by its own trailing 13-week crop level, balances donor contributions and validates every horizon on the target estate's final 13 observations. It compares pooled weather-plus-crop, pooled crop-only, peer-seasonal and recent four-week alternatives. Outputs are marked `PROVISIONAL POOLED—SHORT ESTATE HISTORY` and include a donor audit file. They must be replaced with standard models after sufficient estate history is collected.

Reproduce one pooled run with:

```bash
python train_pooled_short_history.py \
  --estate EildonHall \
  --crop /path/to/EildonHall_output.zip \
  --weather /path/to/TRI-Thalawakele.xlsx \
  --weather /path/to/TRI-Thalawakele_2026_06.xlsx \
  --donor-output outputs/Alton_provisional \
  --donor-output outputs/Bambarakelly_provisional \
  --donor-output outputs/Fairlawn_provisional \
  --donor-output outputs/Gouravilla_provisional \
  --donor-output outputs/Mahanilu_provisional \
  --donor-output outputs/Stockholm_provisional \
  --output-dir outputs/EildonHall_provisional
```

## Group rollout

Complete `config/estate_master_template.csv` with every estate and its correct weather station. The provisional counts are 12 TTEL estates, 15 KVPL estates, and 8 HPL estates (35 total). Confirm these counts before production deployment.

The current physical nearest-station assignments are recorded in `config/weather_station_mapping.csv`; station coordinates and file readiness are in `config/weather_station_master.csv`. Distance matching is a first-pass control, not proof that a station is climatically representative. Each estate run still compares weather-plus-crop against crop-only and baseline methods on unseen recent weeks, and weather is retained only when it lowers validation error. Borderline assignments should be reviewed using elevation and estate microclimate after both weather workbooks are valid.

To apply one confirmed station efficiently after crop-only estate runs have created privacy-safe weekly checkpoints:

```bash
python retrain_with_mapped_weather.py \
  --weather /path/to/TRI-Thalawakele.xlsx \
  --weather /path/to/TRI-Thalawakele_2026_06.xlsx \
  --station-code TRI-TW
```

This does not re-read employee-level crop records. It joins weather to aggregated estate-week crop history and repeats chronological method selection.

## GAP best-practice expansion

The next model has two separate outputs:

1. **Current-practice growth forecast** — expected field and estate crop if the existing manager practices continue.
2. **Best-practice potential forecast** — a scenario estimate after replacing practice variables with those observed in comparable, adjusted high-performing fields.

All estates are needed for training. Supplying only the highest-crop estates would create selection bias. The comparison unit is a field-week and raw crop is normalized to kg/ha. Peer groups must be matched by elevation, tea type, bush age, pruning cycle, rainfall zone, soil and field condition before practices are compared.

No estate or manager is labelled best in advance. The pipeline first estimates expected performance from structural and weather conditions, then identifies practices associated with consistently positive adjusted performance within comparable peer groups. The best-practice output is a scenario estimate, not a manager ranking or a guaranteed causal uplift.

Use `Plantation_GAP_Forecasting_Data_Template.xlsx` for the standardized data contract. Existing estate files can also be supplied without manual re-entry; they will be mapped into the contract.

Validate a populated workbook before training:

```bash
python validate_inputs.py Plantation_GAP_Forecasting_Data_Template.xlsx
```

## Windows / VS Code

For the recommended Windows workflow, open the project in VS Code and run the PowerShell scripts from the integrated terminal:

```powershell
.\setup_windows.ps1
.\validate_gap_data.ps1 -InputPath ".\Plantation_GAP_Forecasting_Data_Template.xlsx"
```

See `WINDOWS_VSCODE_GUIDE.md` for the estate-training command and folder structure.

Start the estate-manager forecasting portal:

```powershell
.\start_portal.ps1
```

The portal graph shows Actual, Current-Practice Forecast and Best-Practice Forecast as three separate series, with Daily, Weekly, Monthly and Yearly views and ranges up to five years. The best-practice line is visibly marked as awaiting data until a validated all-estate GAP model exists. See `portal\README.md` for passwordless access-link distribution and PROMPT synchronization.

Before training the estate collection, validate every archive and use the manifest-controlled batch runner:

```powershell
.\validate_crop_archives.ps1
.\train_all_estates.ps1
```

The batch runner does not guess weather mappings. Complete `config\estate_training_manifest.csv` and enable an estate only after its crop source and representative weather file are confirmed.

If `weather_file` is blank, the project trains a crop-only provisional model. A weather workbook is used only when it is readable and the estate-to-station mapping has been confirmed. Use `Pedro_Estate_Nuwaraeliya(2).xlsx` for Pedro/Nuwara Eliya; retain the original truncated workbook only as a rejected-source audit record.
