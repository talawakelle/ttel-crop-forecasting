# TTE All-Employee Development Scenario v6.1.0

This package continues the workforce-planning sequence using every employee
record in the v6 employee master.

## Safety boundary

The package does not overwrite official availability or constraint templates.
It does not claim employees are currently available, medically fit, or
unrestricted. It creates a development-only scenario because the user
requested continued progress using every employee.

## Outputs

- `all_employee_development_scenario_roster.csv`
- `all_employee_active_field_candidate_matrix.csv`
- `all_employee_inclusion_gate.csv`
- `active_field_candidate_coverage.csv`
- `all_employee_cp_sat_scenario_readiness.csv`
- `scenario_assumption_register.csv`

## Run

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_ALL_EMPLOYEE_SCENARIO_v6.1.0.ps1
.\CHECK_ALL_EMPLOYEE_SCENARIO_v6.1.0.ps1
```

The required inclusion result is:

```text
employees_skipped = 0
all_employee_inclusion_status = PASS
```

CP-SAT and RL remain unstarted. The next stage is CP-SAT development
simulation using this candidate matrix.
