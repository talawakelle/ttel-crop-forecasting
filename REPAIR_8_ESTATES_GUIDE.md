# TTE 8-Estate Crop Repair and Workforce Continuation v2.1.3

This repair is for the failed crop candidates:

- Alton
- Bambarakelly
- Fairlawn
- Gouravilla
- Mahanilu
- Stockholm
- EildonHall
- Tillicoultry

The first six are retrained from their historical crop archives when no completed PROMPT actual rows are available. Their outputs are clearly labelled **provisional historical-only**. EildonHall and Tillicoultry are then rebuilt as **pooled short-history provisional** models using the six donor outputs.

After the crop summary reaches 33/33 PASS, the script automatically starts all-estate workforce-productivity GPU training.

It does not start multi-estate RL. RL needs field-level demand, attendance, leave, skills, restrictions, and estate-level safety evaluation.

## Install

Extract the ZIP into:

`C:\TTE_Integrated_Platform`

Use overwrite/replace when Windows asks.

## Run

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\REPAIR_8_ESTATES_AND_START_WORKFORCE.ps1 `
    -CropRoot "C:\Users\user\Desktop\HG 2" `
    -TriWeather "C:\Users\user\Desktop\w_data\weather_output\TRI-Thalawakele.xlsx" `
    -PedroWeather "C:\Users\user\Desktop\w_data\weather_output\Pedro_Estate_Nuwaraeliya.xlsx" `
    -SkipWorkforceSetup
```

Keep the PowerShell window open and keep the computer connected to power.

## Check status in a second PowerShell window

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
.\CHECK_REPAIR_AND_WORKFORCE_STATUS.ps1
```

## Correct sequence

`Repair 8 crop models → 33/33 crop PASS → workforce-productivity training → check results → field-level demand → separate multi-estate RL later`
