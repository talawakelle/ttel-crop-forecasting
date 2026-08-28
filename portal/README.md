# TTE Integrated Crop, GAP and Workforce Planning Portal

Dependency-free Node.js manager portal for the combined 33-estate crop and conservative workforce-planning checkpoint.

## Access model

- 33 passwordless manager accounts: one active secure access link per estate.
- 1 portfolio administrator account.
- Managers are restricted server-side to their assigned estate; changing a URL or form value cannot grant another estate.
- No username or password entry is required. Access-link tokens are stored only as SHA-256 hashes and can be rotated.
- Sessions expire after eight hours and use HttpOnly, SameSite=Strict cookies.
- State-changing forms use CSRF tokens and access-link sessions are validated on every request.

## Forecast graph

Every estate graph has three series:

1. Actual crop — privacy-safe estate/day totals imported from PROMPT.
2. Current-practice forecast — validated four-week forecast followed by a five-year planning projection.
3. Best-practice forecast — activates only after sufficient field master and practice diary data exists.

The graph supports Daily, Weekly, Monthly and Yearly aggregation and ranges from one week to five years. Years 4–5 are explicitly strategic scenarios. Daily values after the validated four-week horizon are allocations from weekly/seasonal planning projections, not exact weather forecasts.

## Workforce planning page

Every estate account also has a server-restricted workforce page. It shows the historical employee/division/field coverage, workforce data-readiness status, crop-demand freshness gate, approved safety limits and the inputs still required for a daily plan. It does not expose employee identifiers, create automatic moves or enable RL.

Clarendon remains the preserved planner pilot. Every other estate must select and validate its own productivity model before shadow mode; short-history estates remain provisional.

## Start in VS Code / PowerShell

From the project root:

```powershell
.\start_portal.ps1
```

Then open `http://127.0.0.1:8080`.

To expose the portal on an internal network, deploy it behind the organisation's HTTPS reverse proxy and set:

```powershell
$env:PORTAL_HOST = "0.0.0.0"
$env:COOKIE_SECURE = "true"
npm --prefix .\portal start
```

Do not expose the development server directly to the public internet.

The issued links currently use `http://127.0.0.1:8080`. Before an internal-network rollout, set the final HTTPS address and intentionally rotate the links once:

```powershell
$env:PORTAL_BASE_URL = "https://crop-forecast.your-company.example"
cd portal
npm run setup -- --rotate-links
```

Distribute the resulting CSV privately. The previous links are invalid after rotation.

## Refresh automated actuals

The supplied PROMPT automation creates one XLSX workbook per estate. Import only privacy-safe daily totals:

```powershell
.\sync_prompt_actuals.ps1 -SourcePath "C:\Data\prompt_automation\output"
```

The portal notices changes to `outputs\prompt_daily_actuals.csv` without a restart. Employee names, IDs and images are not copied into the portal.

## Rotate access links

Initial setup runs automatically when the database does not exist. To intentionally replace every passwordless access link:

```powershell
cd portal
npm run setup -- --rotate-links
```

This invalidates existing links and writes a new private access-link file. Use only with formal authorization. Never include that file in the main project ZIP or forward one estate's link to another estate.
