@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0train_dynamic_rl_gpu_windows.ps1"
if errorlevel 1 (
  echo.
  echo RL training finished, but the candidate failed one or more untouched-test safety gates.
  echo Read models\dynamic_training_rejected.json for the exact reason.
  pause
  exit /b 1
)
echo.
echo Approved event-driven dynamic RL model created.
pause
