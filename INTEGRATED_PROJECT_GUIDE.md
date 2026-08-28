# TTE Integrated Crop, GAP and Workforce Planning Platform

## What this checkpoint does

One authenticated portal now combines:

- actual green-leaf crop imported from PROMPT at estate/day grain;
- current-practice crop forecasts and their 80% ranges;
- a deliberately empty best-practice line until enough real GAP evidence exists;
- five-year daily/weekly/monthly/yearly planning views;
- a practice diary and field master for future GAP modelling;
- workforce data/readiness for all 33 estates;
- the Clarendon v1.5 conservative planner preserved as the pilot reference;
- server-side one-estate isolation for each manager account.

The workforce page is decision support, not automatic employee control. It does not make live moves.

## Start on Windows

Open PowerShell in the extracted project folder and run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\START_TTE_INTEGRATED_PLATFORM.ps1
```

Open `http://127.0.0.1:8080` through the secure link issued for the estate. No password is required.

## Refresh the July 22 PROMPT actuals

The downloader output reported by the current Windows run is:

```text
C:\Users\user\Downloads\PROMPT_Latest\prompt_automation\output
```

Run:

```powershell
Set-Location "C:\TTE_Forecasting\ttel_crop_forecasting"
.\REFRESH_PROMPT_ACTUALS.ps1 -SourcePath "C:\Users\user\Downloads\PROMPT_Latest\prompt_automation\output"
```

This updates the black **Actual value** line. It does not silently change either forecast scenario. After new crop and weather inputs are complete, retrain and validate the crop models before treating workforce demand as current.

## The three crop graph lines

1. **Actual value** — imported PROMPT estate/day totals plus any manager fallback entry.
2. **Current-practice forecast** — the estate-specific forecast and its longer planning projection.
3. **Best-practice forecast** — pooled comparable-estate GAP potential, activated only after fields, practices, timing, costs and outcomes pass validation.

Blank best-practice values are intentional. The system does not invent an uplift.

## Workforce safety model

- Morning plan: CP-SAT is permitted only inside a validated estate pilot.
- Intraday default: budgeted dynamic greedy.
- Maximum movement: 15% and no more than 15 total moves.
- Maximum per round: 10 moves.
- Maximum voluntary movement per employee: one.
- RL role: high-confidence accept/veto gate only, always with deterministic fallback.
- Live automatic moves: disabled.
- Every estate must pass its own temporal model comparison, untouched test, shadow review and manager approval.

An employee identifier is always scoped to plantation + estate. The system never assumes that the same numeric employee ID represents the same person in two estates.

## Current production blockers

- The packaged crop forecasts end on 12 July 2026 and are stale on 22 July 2026.
- Attendance, leave, skills, legal restrictions and supervisor approvals are not present in the crop archives.
- Calsay and Udaradella used recovered workbook sources; valid replacement archives are required before production training.
- Eildon Hall, Tillicoultry and other short-history estates remain provisional where the audit says `CONDITIONAL_SHORT_HISTORY`.
- No approved RL policy is included; GPU/RL training remains unauthorized.

## Project folders

- `portal/` — authenticated integrated manager portal.
- `outputs/` — crop forecasts, actuals, projections and privacy-safe workforce audit.
- `workforce_planner/` — Clarendon pilot engine plus the multi-estate v2 registry, audit and crop adapter.
- `config/` — crop and weather mappings.
- `data/incoming/` — place new authorized source data here.

