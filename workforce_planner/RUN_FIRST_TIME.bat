@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File ".\setup_windows.ps1"
if errorlevel 1 pause & exit /b 1
powershell -NoProfile -ExecutionPolicy Bypass -File ".\start_windows.ps1"
pause
