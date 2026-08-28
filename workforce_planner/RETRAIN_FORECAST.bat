@echo off
cd /d "%~dp0"
echo Retraining changes the forecast fingerprint and disables any old RL model until RL is retrained.
powershell -NoProfile -ExecutionPolicy Bypass -File ".\train_productivity_auto_windows.ps1" -Iterations 3000 -Depth 8
pause
