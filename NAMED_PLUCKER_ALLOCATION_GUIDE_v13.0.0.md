# TTE Simulation Named Plucker Allocation v13.0.0

This package exports named employee-field assignments from the latest
passed CP-SAT development run.

The user requested all supervisor decisions to be accepted. Therefore,
the output uses:

```text
supervisor_simulation_decision = ACCEPT
supervisor_acceptance_basis = USER_REQUESTED_SIMULATION_ACCEPT_ALL
actual_supervisor_verified = NO
```

This is a simulation marker, not a real supervisor approval.

Run:

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_NAMED_PLUCKER_ALLOCATION_v13.0.0.ps1
.\CHECK_NAMED_PLUCKER_ALLOCATION_v13.0.0.ps1
.\OPEN_NAMED_PLUCKER_ALLOCATION_v13.0.0.ps1
```

Main output:

```text
allocation\named_plucker_allocation_simulation.csv
```

Controls that remain fixed:

```text
actual_supervisor_verified = NO
attendance_verified = NO
approved_leave_verified = NO
fitness_verified = NO
movement_restrictions_verified = NO
operational_use_allowed = NO
live_assignment_authorized = NO
```

Do not send this output to employees or use it for live field deployment.
