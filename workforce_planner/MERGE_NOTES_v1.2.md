# Forecast Merge Notes

## Source selected

The relevant external forecast is the Clarendon four-week plantation crop pilot. The monthly tea-production portfolio model and the six-estate assignment workbook are not direct field-allocation inputs.

## Granularity contract

| Component | Output granularity | Role |
|---|---|---|
| Plantation crop forecast | Estate × week | Total crop-demand envelope |
| CatBoost productivity | Employee × field × planning date | Expected worker contribution |
| Field schedule template | Field × day | Which fields are active and their proportions |
| CP-SAT | Employee × field × morning plan | Static constrained allocation |
| Dynamic RL | Employee × field × intraday event | Reallocation after disruption |

## Why the forecast is not fed directly to RL actions

A weekly total cannot identify a field assignment. The adapter first converts the weekly forecast to a daily total and then applies a declared field schedule. This prevents the system from inventing field-level precision that the crop model did not produce.

## Mismatch requiring future correction

The crop pilot reports 30 fields while the current workforce profile contains 36 field identifiers. This release uses the workforce profile as the operational field master and the selected template day as the active-field schedule. The crop model should eventually be retrained with the same canonical field master.
