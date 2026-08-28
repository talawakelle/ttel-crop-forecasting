@echo off
cd /d "%~dp0"
echo This requires an NVIDIA GPU and can take several hours.
powershell -NoProfile -ExecutionPolicy Bypass -File ".\setup_gpu_windows.ps1"
if errorlevel 1 pause & exit /b 1
powershell -NoProfile -ExecutionPolicy Bypass -File ".\train_strong_gpu_windows.ps1" -TimestepsPerSeed 400000
pause
