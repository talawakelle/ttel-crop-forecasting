TTE FORECASTING + PROTECTED HYBRID RL CONTINUOUS PROJECT v16.0.0
=================================================================

DEFAULT PROJECT PERIOD
Start: 2026-07-27
End:   2031-07-26
Total: 1,826 dates

The master launcher divides the period into resumable blocks of up to 90 days.
It creates 20 blocks of 90 days and one final block of 26 days.

INCLUDED WORKFLOW
Forecasting:                    YES
Estate/division/field reconciliation: YES
Plucker-demand calculation:     YES
CP-SAT morning allocation:      YES
Named employee allocation:      YES
Protected hybrid RL inference:  YES
CUDA required:                  YES
Safety shield:                  YES
Greedy fallback:                YES
Monthly Excel workbooks:        YES
Live operational authorization: NO

IMPORTANT INTERPRETATION
This package performs protected hybrid RL inference using the existing trained
model. It does not retrain the RL model.

All future named employee allocations are current-roster shadow simulations.
Attendance, approved leave, fitness, movement restrictions, home-code
verification, operational use and live authorization remain NO.

REQUIRED EXISTING PROJECT FILES
- START_DAILY_HIERARCHY_CANDIDATE_v4.0.0.ps1
- START_FINAL_METHOD_GATE_PLANNING_v5.0.3.ps1
- Existing forecasting source archives under C:\Users\user\Desktop\HG 2
- Existing current employee roster and allocation source files

PYTHON REQUIREMENTS
Python 3.12 with:
- PyTorch and CUDA
- OR-Tools
- openpyxl

MAIN LAUNCHER
RUN_TTE_FORECASTING_RL_CONTINUOUS_v16.0.0.ps1

The launcher is resumable:
- passing dates are skipped;
- passing blocks are skipped;
- an incomplete date or block is rebuilt when the same command is rerun.

DEFAULT RESULT FOLDER
C:\Users\user\Desktop\TTE_Forecasting_RL_Continuous_20260727_20310726

RESULTS
- START_HERE.html
- run_summary.json
- master\TTE_Forecasting_Protected_Hybrid_RL_Continuous_Summary.xlsx
- master\master_block_index.csv
- master\monthly_workbook_index.csv
- blocks\block_...\excel\monthly Excel workbooks
- blocks\block_...\combined_csv\combined block CSV files
- blocks\block_...\days\daily protected RL outputs

OVERNIGHT USE
Keep the computer connected to power and prevent Windows from sleeping.
The entire five-year simulation is not guaranteed to finish in one night.
You can stop it and rerun the same command; completed passing work is skipped.

OPTIONAL SESSION LIMIT
To process only two new blocks in one session:
.\RUN_TTE_FORECASTING_RL_CONTINUOUS_v16.0.0.ps1 -MaxBlocksThisRun 2

To continue through all remaining blocks:
.\RUN_TTE_FORECASTING_RL_CONTINUOUS_v16.0.0.ps1

CHECK PROGRESS
.\CHECK_TTE_FORECASTING_RL_CONTINUOUS_v16.0.0.ps1

CHECK AND OPEN RESULTS
.\CHECK_TTE_FORECASTING_RL_CONTINUOUS_v16.0.0.ps1 -OpenResults
