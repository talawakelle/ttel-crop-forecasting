@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0train_selective_hybrid_rl_gpu_windows.ps1"
if errorlevel 1 (
  echo.
  echo v1.5 conservative hybrid training completed, but the candidate failed one or more safety gates.
  echo Read models\selective_hybrid_training_rejected.json for the exact reason.
  echo The best rejected candidate is preserved as models\selective_hybrid_rejected_candidate.zip.
  pause
  exit /b 1
)
echo.
echo Approved v1.5 high-confidence hybrid RL model created.
echo The model still requires operational shadow-mode evidence before live use.
pause
