# TTE Crop Repair v2.1.4

This patch resumes the interrupted v2.1.3 repair.

## What changed

- Reuses Alton's completed four-row output instead of retraining it.
- Keeps the rule that weeks with fewer than three crop days are excluded.
- Trains Bambarakelly under a clearly labelled short-history provisional gate:
  - minimum 26 chronological training weeks
  - minimum 8 chronological validation weeks
- Attempts all direct repairs before reporting any remaining failures.
- Saves the 33-estate summary after every estate so the job can resume safely.
- Starts workforce-productivity training only after the summary reaches 33/33 PASS.

## Run

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\REPAIR_8_ESTATES_AND_START_WORKFORCE_v2.1.4.ps1 `
    -CropRoot "C:\Users\user\Desktop\HG 2" `
    -TriWeather "C:\Users\user\Desktop\w_data\weather_output\TRI-Thalawakele.xlsx" `
    -PedroWeather "C:\Users\user\Desktop\w_data\weather_output\Pedro_Estate_Nuwaraeliya.xlsx" `
    -SkipWorkforceSetup
```

## Check

```powershell
.\CHECK_REPAIR_AND_WORKFORCE_STATUS_v2.1.4.ps1
```

All repaired missing-PROMPT and short-history forecasts remain provisional. They are suitable for continuing model development, not automatic live decisions.
