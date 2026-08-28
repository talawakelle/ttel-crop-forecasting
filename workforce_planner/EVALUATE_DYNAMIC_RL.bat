@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0evaluate_dynamic_rl_windows.ps1"
pause
