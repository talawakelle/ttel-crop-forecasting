from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def parse_date(value: Any) -> date:
    text = clean(value)
    if not text:
        raise ValueError("blank date")
    return datetime.fromisoformat(text.replace("Z", "+00:00")).date()


def as_float(value: Any) -> float | None:
    text = clean(value)
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def find_latest(run_folder: Path, name: str) -> Path | None:
    matches = list(run_folder.rglob(name))
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def choose_column(headers: list[str], exact: list[str], contains: list[str]) -> str | None:
    lower_map = {h.lower(): h for h in headers}
    for candidate in exact:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]
    for header in headers:
        lowered = header.lower()
        if all(token in lowered for token in contains):
            return header
    return None


def safe_name(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    return text.strip("_") or "estate"


def planning_year(d: date, start: date) -> int:
    first_end = start.replace(year=start.year + 1)
    second_end = start.replace(year=start.year + 2)
    if d < first_end:
        return 1
    if d < second_end:
        return 2
    return 3


def fmt_num(value: float | None, decimals: int = 0) -> str:
    if value is None:
        return ""
    return f"{value:,.{decimals}f}"


def make_svg(month_rows: list[dict[str, Any]]) -> str:
    values = [float(row["forecast_kg"]) for row in month_rows]
    if not values:
        return ""

    width = 1000
    height = 280
    left = 70
    right = 20
    top = 20
    bottom = 55
    plot_w = width - left - right
    plot_h = height - top - bottom
    max_v = max(values) or 1.0

    points = []
    for i, value in enumerate(values):
        x = left + (plot_w * i / max(1, len(values) - 1))
        y = top + plot_h - (value / max_v) * plot_h
        points.append(f"{x:.1f},{y:.1f}")

    labels = []
    step = max(1, len(month_rows) // 12)
    for i in range(0, len(month_rows), step):
        x = left + (plot_w * i / max(1, len(values) - 1))
        label = html.escape(month_rows[i]["month"])
        labels.append(
            f'<text x="{x:.1f}" y="{height-18}" text-anchor="middle" '
            f'font-size="10" fill="#555">{label}</text>'
        )

    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Monthly company crop projection chart">'
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>'
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_h}" '
        f'stroke="#999"/>'
        f'<line x1="{left}" y1="{top+plot_h}" x2="{width-right}" '
        f'y2="{top+plot_h}" stroke="#999"/>'
        f'<polyline points="{" ".join(points)}" fill="none" '
        f'stroke="#2e7d32" stroke-width="3"/>'
        f'<text x="10" y="{top+12}" font-size="11" fill="#555">'
        f'{html.escape(fmt_num(max_v, 0))} kg</text>'
        f'{"".join(labels)}</svg>'
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-folder", required=True)
    parser.add_argument("--output-folder", required=True)
    parser.add_argument("--forecast-start", required=True)
    parser.add_argument("--forecast-days", type=int, required=True)
    parser.add_argument("--expected-estates", type=int, default=33)
    args = parser.parse_args()

    run_folder = Path(args.run_folder).resolve()
    output_folder = Path(args.output_folder).resolve()
    output_folder.mkdir(parents=True, exist_ok=True)

    source = find_latest(run_folder, "estate_daily_forecast.csv")
    if source is None:
        raise SystemExit(
            "No estate_daily_forecast.csv was found in the latest run folder."
        )

    source_rows = read_csv(source)
    if not source_rows:
        raise SystemExit("estate_daily_forecast.csv is empty.")

    headers = list(source_rows[0].keys())

    estate_col = choose_column(
        headers,
        ["estate", "estate_name", "estate_id"],
        ["estate"],
    )
    date_col = choose_column(
        headers,
        ["forecast_date", "date", "forecast_day", "day"],
        ["forecast", "date"],
    )
    forecast_col = choose_column(
        headers,
        [
            "forecast_kg",
            "expected_crop_kg",
            "forecast_crop_kg",
            "predicted_kg",
            "estate_forecast_kg",
            "point_forecast_kg",
            "crop_forecast_kg",
        ],
        ["forecast", "kg"],
    )
    lower_col = choose_column(
        headers,
        ["lower_80_kg", "lower_kg", "lower_forecast_kg"],
        ["lower", "kg"],
    )
    upper_col = choose_column(
        headers,
        ["upper_80_kg", "upper_kg", "upper_forecast_kg"],
        ["upper", "kg"],
    )
    method_col = choose_column(
        headers,
        ["selected_method", "forecast_method", "method"],
        ["method"],
    )
    gate_col = choose_column(
        headers,
        ["development_gate", "forecast_gate", "gate"],
        ["gate"],
    )

    if not estate_col or not date_col or not forecast_col:
        raise SystemExit(
            "Could not identify required columns.\n"
            f"Headers found: {headers}\n"
            f"estate={estate_col}, date={date_col}, forecast={forecast_col}"
        )

    start = datetime.strptime(args.forecast_start, "%Y-%m-%d").date()

    normalized: list[dict[str, Any]] = []
    for row in source_rows:
        try:
            d = parse_date(row.get(date_col))
        except ValueError:
            continue

        forecast = as_float(row.get(forecast_col))
        if forecast is None:
            continue

        lower = as_float(row.get(lower_col)) if lower_col else None
        upper = as_float(row.get(upper_col)) if upper_col else None

        normalized.append({
            "date": d.isoformat(),
            "estate": clean(row.get(estate_col)),
            "forecast_kg": round(forecast, 4),
            "lower_80_kg": "" if lower is None else round(lower, 4),
            "upper_80_kg": "" if upper is None else round(upper, 4),
            "selected_method": clean(row.get(method_col)) if method_col else "",
            "development_gate": clean(row.get(gate_col)) if gate_col else "",
            "planning_year": planning_year(d, start),
            "calendar_year": d.year,
            "month": d.strftime("%Y-%m"),
            "day_name": d.strftime("%A"),
            "operating_calendar_verified": "NO",
            "projection_status": "LONG_RANGE_PLANNING_PROJECTION_ONLY",
        })

    if not normalized:
        raise SystemExit("No valid forecast rows were produced.")

    normalized.sort(key=lambda r: (r["date"], r["estate"].lower()))

    estates = sorted({r["estate"] for r in normalized}, key=str.lower)
    dates = sorted({r["date"] for r in normalized})
    expected_rows = args.expected_estates * args.forecast_days
    row_count_pass = len(normalized) == expected_rows
    estate_count_pass = len(estates) == args.expected_estates
    date_count_pass = len(dates) == args.forecast_days

    fields = list(normalized[0].keys())
    write_csv(
        output_folder / "TTE_All_Estates_3_Year_Daily_Forecast.csv",
        normalized,
        fields,
    )

    estate_folder = output_folder / "Estate_Daily_Files"
    estate_folder.mkdir(parents=True, exist_ok=True)

    by_estate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in normalized:
        by_estate[row["estate"]].append(row)

    for estate, rows in by_estate.items():
        write_csv(
            estate_folder / f"{safe_name(estate)}_3_Year_Daily_Forecast.csv",
            rows,
            fields,
        )

    monthly_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    annual_groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    company_month_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in normalized:
        monthly_groups[(row["estate"], row["month"])].append(row)
        annual_groups[(row["estate"], int(row["planning_year"]))].append(row)
        company_month_groups[row["month"]].append(row)

    monthly_rows: list[dict[str, Any]] = []
    for (estate, month), rows in sorted(monthly_groups.items()):
        monthly_rows.append({
            "estate": estate,
            "month": month,
            "days": len(rows),
            "forecast_kg": round(sum(float(r["forecast_kg"]) for r in rows), 2),
            "lower_80_kg": round(
                sum(float(r["lower_80_kg"]) for r in rows if r["lower_80_kg"] != ""),
                2,
            ),
            "upper_80_kg": round(
                sum(float(r["upper_80_kg"]) for r in rows if r["upper_80_kg"] != ""),
                2,
            ),
            "projection_status": "LONG_RANGE_PLANNING_PROJECTION_ONLY",
        })

    write_csv(
        output_folder / "TTE_Estate_Monthly_3_Year_Summary.csv",
        monthly_rows,
        list(monthly_rows[0].keys()),
    )

    annual_rows: list[dict[str, Any]] = []
    for (estate, year_no), rows in sorted(annual_groups.items()):
        total = sum(float(r["forecast_kg"]) for r in rows)
        annual_rows.append({
            "estate": estate,
            "planning_year": year_no,
            "period_start": min(r["date"] for r in rows),
            "period_end": max(r["date"] for r in rows),
            "days": len(rows),
            "forecast_kg": round(total, 2),
            "average_daily_kg": round(total / len(rows), 2),
            "projection_status": "LONG_RANGE_PLANNING_PROJECTION_ONLY",
        })

    write_csv(
        output_folder / "TTE_Estate_Annual_3_Year_Summary.csv",
        annual_rows,
        list(annual_rows[0].keys()),
    )

    company_month_rows = []
    for month, rows in sorted(company_month_groups.items()):
        company_month_rows.append({
            "month": month,
            "forecast_kg": round(sum(float(r["forecast_kg"]) for r in rows), 2),
            "estate_rows": len(rows),
        })

    write_csv(
        output_folder / "TTE_Company_Monthly_3_Year_Summary.csv",
        company_month_rows,
        list(company_month_rows[0].keys()),
    )

    backtest_file = find_latest(run_folder, "estate_selected_models.csv")
    backtest_lookup: dict[str, dict[str, str]] = {}
    if backtest_file:
        for row in read_csv(backtest_file):
            key = clean(row.get("estate")).lower()
            if key:
                backtest_lookup[key] = row

    estate_summary_rows = []
    for estate in estates:
        rows = by_estate[estate]
        bt = backtest_lookup.get(estate.lower(), {})
        total = sum(float(r["forecast_kg"]) for r in rows)
        estate_summary_rows.append({
            "estate": estate,
            "forecast_start": min(r["date"] for r in rows),
            "forecast_end": max(r["date"] for r in rows),
            "daily_rows": len(rows),
            "three_year_forecast_kg": round(total, 2),
            "average_daily_kg": round(total / len(rows), 2),
            "selected_method": clean(
                bt.get("selected_method") or rows[0].get("selected_method")
            ),
            "backtest_mae_kg": clean(bt.get("selected_mae_kg")),
            "backtest_wape_pct": clean(bt.get("selected_wape_pct")),
            "operating_calendar_verified": "NO",
            "projection_status": "LONG_RANGE_PLANNING_PROJECTION_ONLY",
        })

    write_csv(
        output_folder / "TTE_Estate_3_Year_Executive_Summary.csv",
        estate_summary_rows,
        list(estate_summary_rows[0].keys()),
    )

    checks = [
        {
            "check": "ESTATE_COUNT",
            "value": len(estates),
            "required": args.expected_estates,
            "status": "PASS" if estate_count_pass else "FAIL",
        },
        {
            "check": "DISTINCT_FORECAST_DATES",
            "value": len(dates),
            "required": args.forecast_days,
            "status": "PASS" if date_count_pass else "FAIL",
        },
        {
            "check": "ESTATE_DAILY_ROWS",
            "value": len(normalized),
            "required": expected_rows,
            "status": "PASS" if row_count_pass else "FAIL",
        },
        {
            "check": "OPERATING_CALENDAR_VERIFIED",
            "value": "NO",
            "required": "YES_FOR_LIVE_USE",
            "status": "OPEN_REVIEW",
        },
        {
            "check": "LIVE_OPERATIONAL_USE",
            "value": "NO",
            "required": "NO",
            "status": "PASS",
        },
    ]
    write_csv(
        output_folder / "TTE_3_Year_Forecast_Quality_Gate.csv",
        checks,
        ["check", "value", "required", "status"],
    )

    summary = {
        "status": (
            "PASS_3_YEAR_DAILY_PLANNING_PROJECTION_OUTPUTS"
            if row_count_pass and estate_count_pass and date_count_pass
            else "CHECK_3_YEAR_DAILY_OUTPUT_COMPLETENESS"
        ),
        "source_run_folder": str(run_folder),
        "source_estate_daily_forecast": str(source),
        "forecast_start": min(dates) if dates else "",
        "forecast_end": max(dates) if dates else "",
        "forecast_days": len(dates),
        "estates": len(estates),
        "estate_daily_rows": len(normalized),
        "expected_estate_daily_rows": expected_rows,
        "projection_type": "LONG_RANGE_PLANNING_PROJECTION_ONLY",
        "operating_calendar_verified": False,
        "live_operational_use_allowed": False,
        "important_limitations": [
            "This is a three-year long-range planning projection, not a precise operational forecast for each day.",
            "Forecast uncertainty increases materially with horizon.",
            "Missing historical dates are not automatically treated as zero crop.",
            "An approved operating calendar is required before daily operational use.",
            "Weather, pruning, fertilizer, manager decisions, extreme events and labour changes beyond the source data are not known for the full three-year horizon.",
            "Use short-horizon refreshed forecasts for weekly and daily workforce decisions.",
        ],
    }
    (output_folder / "run_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    estate_table = []
    for row in estate_summary_rows:
        file_name = (
            f"Estate_Daily_Files/{safe_name(row['estate'])}"
            "_3_Year_Daily_Forecast.csv"
        )
        estate_table.append(
            "<tr>"
            f"<td>{html.escape(row['estate'])}</td>"
            f"<td>{html.escape(row['forecast_start'])}</td>"
            f"<td>{html.escape(row['forecast_end'])}</td>"
            f"<td>{int(row['daily_rows']):,}</td>"
            f"<td>{fmt_num(float(row['three_year_forecast_kg']), 0)}</td>"
            f"<td>{fmt_num(float(row['average_daily_kg']), 0)}</td>"
            f"<td>{html.escape(row['backtest_wape_pct'])}</td>"
            f"<td><a href='{html.escape(file_name)}'>Open daily CSV</a></td>"
            "</tr>"
        )

    chart = make_svg(company_month_rows)

    dashboard = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>TTE 3-Year Daily Crop Projection</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 28px; color: #222; }}
h1, h2 {{ color: #1b5e20; }}
.cards {{ display: grid; grid-template-columns: repeat(4, minmax(160px,1fr));
          gap: 12px; margin: 18px 0; }}
.card {{ background: #f3f8f3; border: 1px solid #c8e6c9;
         border-radius: 8px; padding: 16px; }}
.card strong {{ display: block; font-size: 24px; color: #1b5e20; }}
.notice {{ background: #fff8e1; border-left: 6px solid #f9a825;
           padding: 14px; margin: 18px 0; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #2e7d32; color: white; position: sticky; top: 0; }}
tr:nth-child(even) {{ background: #f7f7f7; }}
a {{ color: #1565c0; }}
</style>
</head>
<body>
<h1>TTE 3-Year Daily Crop Planning Projection</h1>
<p><strong>Period:</strong> {html.escape(summary['forecast_start'])}
to {html.escape(summary['forecast_end'])}</p>

<div class="cards">
  <div class="card"><strong>{summary['estates']}</strong>Estates</div>
  <div class="card"><strong>{summary['forecast_days']:,}</strong>Daily dates</div>
  <div class="card"><strong>{summary['estate_daily_rows']:,}</strong>Estate-day rows</div>
  <div class="card"><strong>NO</strong>Live operational use</div>
</div>

<div class="notice">
<strong>Important:</strong> This is a long-range planning projection.
It is not the same as the existing four-week operational forecast.
Use refreshed short-horizon forecasts for real weekly and daily decisions.
An approved operating calendar has not been applied.
</div>

<h2>Company Monthly Projection</h2>
{chart}

<h2>Estate Summary</h2>
<table>
<thead>
<tr>
<th>Estate</th><th>Start</th><th>End</th><th>Daily rows</th>
<th>3-year forecast kg</th><th>Average daily kg</th>
<th>Backtest WAPE %</th><th>Daily file</th>
</tr>
</thead>
<tbody>
{''.join(estate_table)}
</tbody>
</table>

<h2>Main Files</h2>
<p><a href="TTE_All_Estates_3_Year_Daily_Forecast.csv">
All estates — day-by-day forecast CSV</a></p>
<p><a href="TTE_Estate_Monthly_3_Year_Summary.csv">
Estate monthly summary</a></p>
<p><a href="TTE_Estate_Annual_3_Year_Summary.csv">
Estate annual summary</a></p>
<p><a href="TTE_Estate_3_Year_Executive_Summary.csv">
Executive estate summary</a></p>
<p><a href="TTE_3_Year_Forecast_Quality_Gate.csv">
Quality gate</a></p>
</body>
</html>
'''

    (output_folder / "START_HERE_3_YEAR_FORECAST.html").write_text(
        dashboard, encoding="utf-8"
    )

    print("")
    print("3-YEAR DAILY FORECAST REPORT FINISHED")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
