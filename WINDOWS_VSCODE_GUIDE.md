# Running the Forecasting Project in VS Code and PowerShell

## Recommended setup

Use **VS Code** to manage the project and its **integrated PowerShell terminal** to execute commands. VS Code and PowerShell are complementary; they are not alternatives.

## 1. Open the project

1. Extract `TTE_Integrated_Crop_and_Workforce_Planning_Platform.zip`.
2. Open VS Code.
3. Select **File → Open Folder**.
4. Open the extracted `ttel_crop_forecasting` folder.
5. Open **Terminal → New Terminal** and confirm the terminal profile is PowerShell.

## 2. Set up Python

Run:

```powershell
.\setup_windows.ps1
```

If Windows blocks the script, allow scripts only for the current terminal session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\setup_windows.ps1
```

Do not use a system-wide execution-policy change for this project.

## 3. Place the data

```text
data\incoming\crop\          One ZIP per estate
data\incoming\weather\       Weather workbooks
data\incoming\practice\      Diaries, fertilizer and foliar records
data\incoming\sundry_work\   Employee counts, man-days and completed work
data\incoming\field_master\  Field extent, elevation, tea type and pruning
data\incoming\financials\    Monthly estate financial data
```

Keep the original files unchanged. The estate name and period should be clear in every filename.

## 4. Run the first crop/weather pilot

First verify that every ZIP is complete:

```powershell
.\validate_crop_archives.ps1
```

Do not train any archive marked `FAIL`. Recreate it from the original annual workbooks and validate it again.

Example only—replace all paths and the estate name with the actual uploaded files:

```powershell
.\train_estate.ps1 `
  -Estate "Estate A" `
  -CropZip "data\incoming\crop\Estate_A_2021_2026.zip" `
  -WeatherFile "data\incoming\weather\Weather_Station_01.xlsx"
```

The script creates a separate output folder for the estate.

If the representative weather station is not confirmed, omit `-WeatherFile`. The script will train a crop-only provisional model rather than guessing a weather mapping:

```powershell
.\train_estate.ps1 `
  -Estate "Estate A" `
  -CropZip "data\incoming\crop\Estate_A_2021_2026.zip"
```

## 5. Run several estates

Complete `config\estate_training_manifest.csv` with the estate name and crop source. Leave `weather_file` blank for a crop-only provisional run; populate it only when the representative station has been confirmed. Set `enabled` to `TRUE` only after the source has been checked. Then run:

```powershell
.\train_all_estates.ps1
```

Each estate receives a separate output folder. The batch summary is written to `outputs\batch_training_summary.csv`.

After training, build the consolidated portfolio view:

```powershell
.\.venv\Scripts\python.exe build_portfolio_summary.py
```

Open `outputs\portfolio_dashboard.html` in a browser. A forecast marked `OUTDATED—REFRESH DATA` is a valid historical model output whose target period has already ended; upload the latest crop data and rerun before operational use.

## 6. Validate GAP practice data

For the standardized workbook:

```powershell
.\validate_gap_data.ps1 `
  -InputPath ".\Plantation_GAP_Forecasting_Data_Template.xlsx"
```

A blocking validation error means training must stop until the source is corrected. Do not bypass missing field codes, invalid dates or unmatched estates.

## 7. Start the integrated 33-estate manager portal

The portal uses a separate passwordless access link for each estate manager. Keep the supplied access-link CSV outside the main project folder and send each manager only their own row.

```powershell
.\START_TTE_INTEGRATED_PLATFORM.ps1
```

Open the manager's secure link, not the plain `http://127.0.0.1:8080` address. Managers are restricted to their assigned estate on the server. The portfolio administrator link opens all 33 estates.

The graph provides Actual, Current-Practice Forecast and Best-Practice Forecast series with Daily, Weekly, Monthly and Yearly views and a maximum five-year range. Current-practice values are available; best practice remains visibly unavailable until the field master and practice diary contain enough validated evidence.

Refresh actual crop from the PROMPT output folder:

```powershell
.\sync_prompt_actuals.ps1 -SourcePath "C:\Data\prompt_automation\output"
```

The importer keeps only estate/date crop totals. It does not copy employee names, employee numbers or images into the portal.

Open **Workforce Planning** inside the same manager account to see the assigned estate's employee/division/field coverage, model-readiness gates and crop-demand freshness. The page does not generate automatic employee moves. See `INTEGRATED_PROJECT_GUIDE.md` for the conservative workforce lifecycle and the exact July 22 refresh command.

## GPU policy

GPU usage is a model-selection decision, not a quality setting. Start with auditable tree-based and statistical baselines. Add GPU models only after the dataset is large enough and they improve chronological and leave-one-estate-out validation. The selected production model is the most accurate and stable model, not the model that consumes the most hardware.
