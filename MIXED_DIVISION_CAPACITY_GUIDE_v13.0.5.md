# TTE Mixed-Division Capacity-Safe Allocation v13.0.5

This version allows an employee to work in more than one field or
division on the same date.

The capacity rule is:

```text
sum of employee_field_allocated_capacity_kg
must be less than or equal to employee_daily_capacity_kg
```

It no longer treats every repeated employee ID as a duplicate failure.

An exact duplicate of the same employee, division and field remains a
data failure.

## Start

```powershell
Set-Location "C:\TTE_Integrated_Platform\ttel_crop_forecasting"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\START_MIXED_DIVISION_CAPACITY_v13.0.5.ps1
.\CHECK_MIXED_DIVISION_CAPACITY_v13.0.5.ps1
.\OPEN_MIXED_DIVISION_CAPACITY_REVIEW_v13.0.5.ps1
```

## Main review file

```text
review_input\employee_field_capacity_allocation_review.csv
```

For a single-row employee, the capacity is prefilled.

For an employee with several rows, enter the capacity allocated to each
field. The total must not exceed the employee's daily capacity.

For a mixed-division employee, an authorized supervisor must complete:

```text
supervisor_mixed_division_confirmed = YES
supervisor_name
reviewed_at
```

Do not confirm a movement that did not actually occur or was not
authorized.

Keep:

```text
employee_home_code_verified = NO
attendance_verified = NO
approved_leave_verified = NO
fitness_verified = NO
movement_restrictions_verified = NO
operational_use_allowed = NO
live_assignment_authorized = NO
```

TLD and other unclear home codes remain unverified.

## Validate

```powershell
.\VALIDATE_MIXED_DIVISION_CAPACITY_v13.0.5.ps1
.\CHECK_MIXED_DIVISION_CAPACITY_v13.0.5.ps1
```

The target gate is:

```text
READY_FOR_EMPLOYEE_HOME_CODE_SUPERVISOR_REVIEW
```

This gate confirms capacity arithmetic only. It does not verify current
employee status or authorize live assignments.

## Open successful outputs

```powershell
.\OPEN_MIXED_DIVISION_CAPACITY_OUTPUTS_v13.0.5.ps1
```
