@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0benchmark_selective_hybrid_windows.ps1"
if errorlevel 1 (
  echo.
  echo Hybrid safety benchmark failed.
  pause
  exit /b 1
)
echo.
echo Hybrid safety benchmark completed.
echo Read models\selective_hybrid_safety_benchmark.json
pause
