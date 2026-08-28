# Improvements in v1.2

- Merged the Clarendon four-week estate crop forecast through an explicit granularity adapter.
- Added lower, central and upper forecast-demand modes.
- Added stale-forecast rejection instead of silent use of expired values.
- Added a refresh importer for the external forecast workbook.
- Added demand-source and forecast-risk controls to the web interface and API.
- Separated morning static planning from intraday dynamic RL.
- Added disruption-calibrated reallocation environment.
- Added reserve employee handling, absence shocks and productivity shocks.
- Added chronological holdout and curriculum training.
- Added no-replan and dynamic-greedy paired benchmarks.
- Added strict dynamic-policy rejection gates.
