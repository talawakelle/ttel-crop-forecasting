# TTE Supervisor Shadow Review Identity Repair v12.0.1

This version repairs employee identity by using:

```text
employee_key = estate + "|" + employee_id
```

It must preserve:

```text
23,043 estate-employee records
0 duplicate composite identities
33 estates
396 simulated review cases
```

Run:

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_SUPERVISOR_SHADOW_REVIEW_v12.0.1.ps1
.\CHECK_SUPERVISOR_SHADOW_REVIEW_v12.0.1.ps1
.\OPEN_SUPERVISOR_SHADOW_REVIEW_v12.0.1.ps1
```

Do not use the earlier 2,444-row v12.0.0 employee template.

After actual supervisor input:

```powershell
.\VALIDATE_SUPERVISOR_SHADOW_REVIEW_v12.0.1.ps1
.\CHECK_SUPERVISOR_SHADOW_REVIEW_v12.0.1.ps1
```

Historical activity is not proof of current attendance, leave, fitness or availability.
All live_assignment_authorized values must remain NO.
