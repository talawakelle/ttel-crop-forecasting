@echo off
title TTE Forecasting + Protected Hybrid RL Continuous Project
cd /d C:\TTE_Integrated_Platform\ttel_crop_forecasting
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\RUN_TTE_FORECASTING_RL_CONTINUOUS_v16.0.0.ps1"
echo.
echo The session has ended. Review the message above.
pause
