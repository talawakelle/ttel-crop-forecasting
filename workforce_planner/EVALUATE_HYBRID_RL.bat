@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0evaluate_selective_hybrid_rl_windows.ps1"
if errorlevel 1 (
  echo.
  echo Selective hybrid model failed re-evaluation.
  pause
  exit /b 1
)
echo.
echo Selective hybrid model passed re-evaluation.
pause
