from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path
from typing import Any


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def append_csv_files(
    sources: list[Path],
    destination: Path,
) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    fieldnames: list[str] | None = None

    with destination.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as output_handle:
        writer: csv.DictWriter | None = None

        for source in sources:
            if not source.exists():
                continue

            with source.open(
                newline="",
                encoding="utf-8-sig",
            ) as input_handle:
                reader = csv.DictReader(input_handle)

                if reader.fieldnames is None:
                    continue

                if fieldnames is None:
                    fieldnames = list(reader.fieldnames)
                    writer = csv.DictWriter(
                        output_handle,
                        fieldnames=fieldnames,
                        extrasaction="ignore",
                    )
                    writer.writeheader()

                if writer is None:
                    continue

                for row in reader:
                    writer.writerow(row)
                    row_count += 1

    return row_count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--forecast-start", required=True)
    parser.add_argument("--forecast-end", required=True)
    parser.add_argument("--expected-chunks", type=int, required=True)
    args = parser.parse_args()

    output_root = Path(args.output_root).resolve()
    chunks_root = output_root / "Chunks"

    summaries: list[dict[str, Any]] = []

    for summary_path in sorted(
        chunks_root.glob("Chunk_*/run_summary.json")
    ):
        summary = json.loads(
            summary_path.read_text(encoding="utf-8")
        )
        chunk_folder = summary_path.parent
        summaries.append({
            "chunk": chunk_folder.name,
            "forecast_start": clean(
                summary.get("forecast_start")
            ),
            "forecast_end": clean(
                summary.get("forecast_end")
            ),
            "forecast_days": int(
                summary.get("forecast_days", 0)
            ),
            "estates": int(summary.get("estates", 0)),
            "field_demand_rows": int(
                summary.get("field_demand_rows", 0)
            ),
            "named_employee_allocation_rows": int(
                summary.get(
                    "named_employee_allocation_rows",
                    0,
                )
            ),
            "expected_required": int(
                summary.get(
                    "expected_total_required_positions",
                    0,
                )
            ),
            "expected_assigned": int(
                summary.get(
                    "expected_total_assigned_positions",
                    0,
                )
            ),
            "expected_unfilled": int(
                summary.get(
                    "expected_total_unfilled_positions",
                    0,
                )
            ),
            "conservative_required": int(
                summary.get(
                    "conservative_total_required_positions",
                    0,
                )
            ),
            "conservative_assigned": int(
                summary.get(
                    "conservative_total_assigned_positions",
                    0,
                )
            ),
            "conservative_unfilled": int(
                summary.get(
                    "conservative_total_unfilled_positions",
                    0,
                )
            ),
            "status": clean(summary.get("status")),
            "folder": str(chunk_folder),
        })

    chunk_status_path = (
        output_root / "TTE_3_Year_Chunk_Status.csv"
    )
    status_fields = [
        "chunk",
        "forecast_start",
        "forecast_end",
        "forecast_days",
        "estates",
        "field_demand_rows",
        "named_employee_allocation_rows",
        "expected_required",
        "expected_assigned",
        "expected_unfilled",
        "conservative_required",
        "conservative_assigned",
        "conservative_unfilled",
        "status",
        "folder",
    ]

    with chunk_status_path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=status_fields,
        )
        writer.writeheader()
        writer.writerows(summaries)

    estate_sources = [
        Path(row["folder"])
        / "TTE_Daily_Estate_Allocation_Summary.csv"
        for row in summaries
    ]
    field_sources = [
        Path(row["folder"])
        / "TTE_Daily_Field_Allocation_Summary.csv"
        for row in summaries
    ]

    estate_rows = append_csv_files(
        estate_sources,
        output_root
        / "TTE_3_Year_Daily_Estate_Allocation_Summary.csv",
    )
    field_rows = append_csv_files(
        field_sources,
        output_root
        / "TTE_3_Year_Daily_Field_Allocation_Summary.csv",
    )

    completed_chunks = len(summaries)
    total_days = sum(row["forecast_days"] for row in summaries)
    total_named_rows = sum(
        row["named_employee_allocation_rows"]
        for row in summaries
    )

    totals = {
        "status": (
            "PASS_COMPLETE_3_YEAR_CHUNKED_FORECAST_AND_ALLOCATION"
            if completed_chunks == args.expected_chunks
            else "PARTIAL_RUN_RESUME_REQUIRED"
        ),
        "forecast_start": args.forecast_start,
        "forecast_end": args.forecast_end,
        "expected_chunks": args.expected_chunks,
        "completed_chunks": completed_chunks,
        "forecast_days_completed": total_days,
        "daily_estate_summary_rows": estate_rows,
        "daily_field_summary_rows": field_rows,
        "named_employee_allocation_rows": total_named_rows,
        "expected_required_positions": sum(
            row["expected_required"] for row in summaries
        ),
        "expected_assigned_positions": sum(
            row["expected_assigned"] for row in summaries
        ),
        "expected_unfilled_positions": sum(
            row["expected_unfilled"] for row in summaries
        ),
        "conservative_required_positions": sum(
            row["conservative_required"]
            for row in summaries
        ),
        "conservative_assigned_positions": sum(
            row["conservative_assigned"]
            for row in summaries
        ),
        "conservative_unfilled_positions": sum(
            row["conservative_unfilled"]
            for row in summaries
        ),
        "employee_home_code_verified": False,
        "attendance_verified": False,
        "operational_use_allowed": False,
        "live_assignment_authorized": False,
    }

    (
        output_root / "run_summary.json"
    ).write_text(
        json.dumps(totals, indent=2),
        encoding="utf-8",
    )

    table_rows = []
    for row in summaries:
        relative = (
            "Chunks/"
            + row["chunk"]
            + "/START_HERE.html"
        )
        table_rows.append(
            "<tr>"
            f"<td>{html.escape(row['chunk'])}</td>"
            f"<td>{html.escape(row['forecast_start'])}</td>"
            f"<td>{html.escape(row['forecast_end'])}</td>"
            f"<td>{row['forecast_days']:,}</td>"
            f"<td>{row['named_employee_allocation_rows']:,}</td>"
            f"<td>{row['expected_unfilled']:,}</td>"
            f"<td>{row['conservative_unfilled']:,}</td>"
            f"<td><a href='{html.escape(relative)}'>"
            "Open chunk</a></td>"
            "</tr>"
        )

    dashboard = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>TTE 3-Year Forecast and Employee Allocation</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 28px; color: #222; }}
h1, h2 {{ color: #1b5e20; }}
.cards {{ display: grid;
grid-template-columns: repeat(4, minmax(170px, 1fr));
gap: 12px; margin: 18px 0; }}
.card {{ background: #f3f8f3;
border: 1px solid #c8e6c9;
border-radius: 8px; padding: 16px; }}
.card strong {{ display: block;
font-size: 24px; color: #1b5e20; }}
.notice {{ background: #fff8e1;
border-left: 6px solid #f9a825;
padding: 14px; margin: 18px 0; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ border: 1px solid #ddd;
padding: 8px; text-align: left; }}
th {{ background: #2e7d32; color: white; }}
tr:nth-child(even) {{ background: #f7f7f7; }}
a {{ color: #1565c0; }}
</style>
</head>
<body>
<h1>TTE 3-Year Daily Forecast and Employee Allocation</h1>
<p><strong>Period:</strong>
{html.escape(args.forecast_start)} to
{html.escape(args.forecast_end)}</p>

<div class="cards">
<div class="card"><strong>{completed_chunks}</strong>
Completed chunks</div>
<div class="card"><strong>{total_days:,}</strong>
Forecast days</div>
<div class="card"><strong>{total_named_rows:,}</strong>
Named allocation rows</div>
<div class="card"><strong>{html.escape(totals['status'])}</strong>
Run status</div>
</div>

<div class="notice">
The original forecasting program accepts a maximum of 90 days per run.
The three-year period is therefore processed as consecutive chunks.
Together, the completed chunks form one continuous forecast and
employee-allocation result.
</div>

<h2>Combined Results</h2>
<p><a href="TTE_3_Year_Daily_Estate_Allocation_Summary.csv">
Combined daily estate allocation summary</a></p>
<p><a href="TTE_3_Year_Daily_Field_Allocation_Summary.csv">
Combined daily field allocation summary</a></p>
<p><a href="TTE_3_Year_Chunk_Status.csv">
Chunk status</a></p>
<p><a href="run_summary.json">Overall run summary</a></p>

<h2>Chunk Results</h2>
<table>
<thead>
<tr>
<th>Chunk</th><th>Start</th><th>End</th><th>Days</th>
<th>Named rows</th><th>EXPECTED unfilled</th>
<th>CONSERVATIVE unfilled</th><th>Open</th>
</tr>
</thead>
<tbody>
{''.join(table_rows)}
</tbody>
</table>
</body>
</html>
"""

    (
        output_root / "START_HERE.html"
    ).write_text(
        dashboard,
        encoding="utf-8",
    )

    print("")
    print("MASTER INDEX UPDATED")
    print(json.dumps(totals, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
