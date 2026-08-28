from __future__ import annotations

import argparse
import csv
import html
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator

VERSION = "16.0.0"
PASS_DAILY = "PASS_PROTECTED_HYBRID_RL_DAILY_SHADOW_ALLOCATION"
PASS_MULTI = "PASS_PROTECTED_HYBRID_RL_MULTI_DAY_SHADOW_ALLOCATION"


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def integer(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(clean(value).replace(",", ""))))
    except (TypeError, ValueError):
        return default


def number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(clean(value).replace(",", ""))
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def parse_date(text: str) -> date:
    return datetime.strptime(text, "%Y-%m-%d").date()


def dates_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv(path: Path) -> Iterator[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        yield from csv.DictReader(handle)


class CsvSink:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None
        self.writer: csv.DictWriter | None = None
        self.fields: list[str] = []
        self.rows = 0

    def write(self, row: dict[str, Any]) -> None:
        if self.writer is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.fields = list(row.keys())
            self.handle = self.path.open("w", newline="", encoding="utf-8-sig")
            self.writer = csv.DictWriter(self.handle, fieldnames=self.fields, extrasaction="ignore")
            self.writer.writeheader()
        self.writer.writerow(row)
        self.rows += 1

    def close(self) -> None:
        if self.handle is not None:
            self.handle.close()


def safe_sheet_title(text: str) -> str:
    bad = set('[]:*?/\\')
    return "".join("_" if ch in bad else ch for ch in text)[:31]


def excel_value(value: str, field: str) -> Any:
    text = clean(value)
    if field == "allocation_date" and text:
        try:
            return datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            return text
    numeric_fields = {
        "expected_productivity_kg", "greedy_final_objective", "hybrid_final_objective",
        "selected_final_objective", "selected_final_under_kg", "selected_final_over_kg",
        "accepted_move_count", "rl_actions_used", "hybrid_greedy_fallbacks",
        "safety_violations", "duplicate_assignments", "step_index",
        "selected_projected_reward", "greedy_projected_reward", "rl_projected_reward",
        "rl_q_value", "target_crop_kg", "assigned_capacity_kg", "under_kg", "over_kg",
        "assigned_employee_count", "value", "required",
    }
    if field in numeric_fields and text != "":
        try:
            value_float = float(text)
            return int(value_float) if value_float.is_integer() else value_float
        except ValueError:
            return text
    return text


def append_csv_to_sheet(ws: Any, path: Path, header_style: dict[str, Any]) -> int:
    from openpyxl.cell import WriteOnlyCell

    count = 0
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        header_cells = []
        for field in fields:
            cell = WriteOnlyCell(ws, value=field)
            cell.font = header_style["font"]
            cell.fill = header_style["fill"]
            cell.alignment = header_style["alignment"]
            header_cells.append(cell)
        ws.append(header_cells)
        for row in reader:
            ws.append([excel_value(row.get(field, ""), field) for field in fields])
            count += 1
    return count


def write_monthly_workbook(
    month_key: str,
    month_dates: list[date],
    day_folders: dict[date, Path],
    excel_root: Path,
) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    workbook = Workbook(write_only=True)
    header_style = {
        "font": Font(bold=True, color="FFFFFF"),
        "fill": PatternFill("solid", fgColor="1B5E20"),
        "alignment": Alignment(horizontal="center", vertical="center", wrap_text=True),
    }

    summary = workbook.create_sheet("Month Summary")
    summary.append(["TTE Forecasting + Protected Hybrid RL Monthly Shadow Allocation"])
    summary.append(["Month", month_key])
    summary.append(["Dates", f"{month_dates[0].isoformat()} to {month_dates[-1].isoformat()}"])
    summary.append(["Forecasting", "YES"])
    summary.append(["Plucker-demand calculation", "YES"])
    summary.append(["Named employee allocation", "YES"])
    summary.append(["Protected hybrid RL inference", "YES"])
    summary.append(["RL model retraining", "NO"])
    summary.append(["Protected hybrid RL system", "YES"])
    summary.append(["Safety shield", "YES"])
    summary.append(["Greedy fallback", "YES"])
    summary.append(["Operational use allowed", "NO"])
    summary.append(["Live assignment authorized", "NO"])
    summary.append(["Interpretation", "Current-roster future-date shadow simulation; attendance, leave, fitness, movement restrictions and home codes remain unverified."])

    sheets = {
        "EXPECTED": workbook.create_sheet("Expected Allocations"),
        "CONSERVATIVE": workbook.create_sheet("Conservative Allocations"),
        "POLICY": workbook.create_sheet("Policy Decisions"),
        "FIELD": workbook.create_sheet("Field Results"),
        "ACTION": workbook.create_sheet("RL Action Audit"),
        "GATE": workbook.create_sheet("Safety Gates"),
    }

    header_written: dict[str, bool] = {key: False for key in sheets}
    fields_by_key: dict[str, list[str]] = {}

    def append_rows(key: str, rows: Iterable[dict[str, str]]) -> None:
        from openpyxl.cell import WriteOnlyCell
        ws = sheets[key]
        for row in rows:
            if not header_written[key]:
                fields = list(row.keys())
                fields_by_key[key] = fields
                header_cells = []
                for field in fields:
                    cell = WriteOnlyCell(ws, value=field)
                    cell.font = header_style["font"]
                    cell.fill = header_style["fill"]
                    cell.alignment = header_style["alignment"]
                    header_cells.append(cell)
                ws.append(header_cells)
                header_written[key] = True
            fields = fields_by_key[key]
            ws.append([excel_value(row.get(field, ""), field) for field in fields])

    for day in month_dates:
        folder = day_folders[day]
        allocation_path = folder / "protected_hybrid_rl_employee_allocations.csv"
        append_rows("EXPECTED", (row for row in read_csv(allocation_path) if clean(row.get("scenario")).upper() == "EXPECTED"))
        append_rows("CONSERVATIVE", (row for row in read_csv(allocation_path) if clean(row.get("scenario")).upper() == "CONSERVATIVE"))
        append_rows("POLICY", read_csv(folder / "protected_hybrid_rl_policy_decisions.csv"))
        append_rows("FIELD", read_csv(folder / "protected_hybrid_rl_field_results.csv"))
        append_rows("ACTION", read_csv(folder / "protected_hybrid_rl_action_audit.csv"))
        for row in read_csv(folder / "protected_hybrid_rl_allocation_gate.csv"):
            enriched = {"allocation_date": day.isoformat(), **row}
            append_rows("GATE", [enriched])

    excel_root.mkdir(parents=True, exist_ok=True)
    output_path = excel_root / f"TTE_Protected_Hybrid_RL_{month_key}.xlsx"
    workbook.save(output_path)
    return output_path


def write_summary_workbook(
    output_path: Path,
    daily_rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    from openpyxl import Workbook
    from openpyxl.chart import LineChart, Reference
    from openpyxl.styles import Alignment, Font, PatternFill

    workbook = Workbook()
    overview = workbook.active
    overview.title = "Overview"

    overview["A1"] = "TTE Forecasting + Protected Hybrid RL Block Shadow Allocation"
    overview["A1"].font = Font(bold=True, size=16, color="1B5E20")
    overview.merge_cells("A1:D1")

    metrics = [
        ("Status", summary["status"]),
        ("Forecasting", "YES"),
        ("Plucker-demand calculation", "YES"),
        ("Named employee allocation", "YES"),
        ("Protected hybrid RL inference", "YES"),
        ("RL model retraining", "NO"),
        ("Safety shield", "YES"),
        ("Greedy fallback", "YES"),
        ("Period", f"{summary['start_date']} to {summary['end_date']}"),
        ("Completed days", summary["completed_days"]),
        ("Estates", 33),
        ("Scenarios per day", 2),
        ("Total episodes", summary["episodes"]),
        ("RL model-invoked episodes", summary["rl_model_invoked_episodes"]),
        ("Named employee rows", summary["employee_allocation_rows"]),
        ("RL actions used", summary["rl_actions_used"]),
        ("Accepted employee moves", summary["accepted_move_count"]),
        ("Safety violations", summary["safety_violations"]),
        ("Duplicate failures", summary["duplicate_assignment_failures"]),
        ("Operational use allowed", "NO"),
        ("Live assignment authorized", "NO"),
    ]

    overview.append([])
    overview.append(["Metric", "Value"])
    for cell in overview[3]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1B5E20")
    for metric, value in metrics:
        overview.append([metric, value])
    overview.column_dimensions["A"].width = 34
    overview.column_dimensions["B"].width = 44
    important_row = overview.max_row + 2
    overview.cell(important_row, 1, "Important")
    overview.cell(important_row, 1).font = Font(bold=True, color="9C6500")
    overview.cell(important_row, 2, "All named allocations are current-roster future-date shadow simulations. Attendance, approved leave, fitness, movement restrictions, home codes and live authorization remain unverified.")
    overview.cell(important_row, 2).alignment = Alignment(wrap_text=True, vertical="top")
    overview.row_dimensions[important_row].height = 54

    daily = workbook.create_sheet("Daily Summary")
    fields = list(daily_rows[0].keys()) if daily_rows else []
    daily.append(fields)
    for cell in daily[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1B5E20")
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
    for row in daily_rows:
        daily.append([row.get(field, "") for field in fields])
    daily.freeze_panes = "A2"
    daily.auto_filter.ref = daily.dimensions
    for col in range(1, len(fields) + 1):
        daily.column_dimensions[chr(64 + col) if col <= 26 else "A"].width = 18

    if daily_rows:
        date_col = fields.index("allocation_date") + 1
        employee_col = fields.index("employee_allocation_rows") + 1
        chart = LineChart()
        chart.title = "Named Employee Rows by Date"
        chart.y_axis.title = "Rows"
        chart.x_axis.title = "Date"
        data = Reference(daily, min_col=employee_col, min_row=1, max_row=daily.max_row)
        categories = Reference(daily, min_col=date_col, min_row=2, max_row=daily.max_row)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(categories)
        chart.height = 8
        chart.width = 16
        overview.add_chart(chart, "D3")

    workbook.save(output_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--expected-days", type=int, required=True)
    parser.add_argument("--skip-excel", action="store_true")
    args = parser.parse_args()

    days_root = Path(args.days_root).resolve()
    output_root = Path(args.output_root).resolve()
    start = parse_date(args.start_date)
    end = parse_date(args.end_date)
    expected_dates = dates_between(start, end)
    if len(expected_dates) != args.expected_days:
        raise SystemExit("Date range does not match expected-days.")

    day_folders: dict[date, Path] = {}
    daily_summaries: list[dict[str, Any]] = []
    missing: list[str] = []

    for day in expected_dates:
        folder = days_root / day.strftime("%Y%m%d")
        summary_path = folder / "run_summary.json"
        if not summary_path.exists():
            missing.append(day.isoformat())
            continue
        summary = read_json(summary_path)
        if summary.get("status") != PASS_DAILY:
            missing.append(day.isoformat())
            continue
        day_folders[day] = folder
        daily_summaries.append(summary)

    if missing:
        raise SystemExit(f"Missing or non-passing daily results: {', '.join(missing[:20])}")

    csv_root = output_root / "combined_csv"
    excel_root = output_root / "excel"
    sinks = {
        "EXPECTED": CsvSink(csv_root / "expected_employee_allocations.csv"),
        "CONSERVATIVE": CsvSink(csv_root / "conservative_employee_allocations.csv"),
        "POLICY": CsvSink(csv_root / "policy_decisions.csv"),
        "FIELD": CsvSink(csv_root / "field_results.csv"),
        "ACTION": CsvSink(csv_root / "rl_action_audit.csv"),
        "GATE": CsvSink(csv_root / "daily_safety_gates.csv"),
        "DAILY": CsvSink(csv_root / "daily_summary.csv"),
    }

    policy_counts: Counter[str] = Counter()
    total_employee_rows = 0
    total_field_rows = 0
    total_episodes = 0
    total_model_invoked = 0
    total_rl_actions = 0
    total_moves = 0
    total_safety = 0
    total_duplicates = 0
    total_live_yes = 0
    daily_rows: list[dict[str, Any]] = []

    try:
        for day in expected_dates:
            folder = day_folders[day]
            summary = read_json(folder / "run_summary.json")

            daily_row = {
                "allocation_date": day.isoformat(),
                "status": summary.get("status", ""),
                "episodes": integer(summary.get("episodes")),
                "employee_allocation_rows": integer(summary.get("employee_allocation_rows")),
                "field_rows": integer(summary.get("field_rows")),
                "rl_model_invoked_episodes": integer(summary.get("rl_model_invoked_episodes")),
                "rl_actions_used": integer(summary.get("rl_actions_used")),
                "accepted_move_count": 0,
                "safety_violations": integer(summary.get("safety_violations")),
                "duplicate_assignment_failures": integer(summary.get("duplicate_assignment_failures")),
                "device_used": clean(summary.get("device_used")),
                "operational_use_allowed": "NO",
                "live_assignment_authorized": "NO",
            }

            for row in read_csv(folder / "protected_hybrid_rl_employee_allocations.csv"):
                scenario = clean(row.get("scenario")).upper()
                if scenario not in ("EXPECTED", "CONSERVATIVE"):
                    raise SystemExit(f"Unexpected scenario {scenario} on {day.isoformat()}")
                sinks[scenario].write(row)
                total_employee_rows += 1
                if clean(row.get("live_assignment_authorized")).upper() != "NO":
                    total_live_yes += 1

            day_moves = 0
            for row in read_csv(folder / "protected_hybrid_rl_policy_decisions.csv"):
                sinks["POLICY"].write(row)
                policy_counts[clean(row.get("final_allocation_policy"))] += 1
                day_moves += integer(row.get("accepted_move_count"))
                total_episodes += 1
                total_model_invoked += 1 if clean(row.get("rl_model_invoked")).upper() == "YES" else 0
                total_rl_actions += integer(row.get("rl_actions_used"))
                total_safety += integer(row.get("safety_violations"))
                total_duplicates += integer(row.get("duplicate_assignments"))
                if clean(row.get("live_assignment_authorized")).upper() != "NO":
                    total_live_yes += 1
            daily_row["accepted_move_count"] = day_moves
            total_moves += day_moves

            for row in read_csv(folder / "protected_hybrid_rl_field_results.csv"):
                sinks["FIELD"].write(row)
                total_field_rows += 1

            for row in read_csv(folder / "protected_hybrid_rl_action_audit.csv"):
                sinks["ACTION"].write(row)

            for row in read_csv(folder / "protected_hybrid_rl_allocation_gate.csv"):
                sinks["GATE"].write({"allocation_date": day.isoformat(), **row})

            sinks["DAILY"].write(daily_row)
            daily_rows.append(daily_row)
    finally:
        for sink in sinks.values():
            sink.close()

    gate_checks = [
        {"check": "COMPLETED_DAYS", "value": len(day_folders), "required": args.expected_days,
         "status": "PASS" if len(day_folders) == args.expected_days else "FAIL"},
        {"check": "EPISODES", "value": total_episodes, "required": args.expected_days * 66,
         "status": "PASS" if total_episodes == args.expected_days * 66 else "FAIL"},
        {"check": "SAFETY_VIOLATIONS", "value": total_safety, "required": 0,
         "status": "PASS" if total_safety == 0 else "FAIL"},
        {"check": "DUPLICATE_ASSIGNMENTS", "value": total_duplicates, "required": 0,
         "status": "PASS" if total_duplicates == 0 else "FAIL"},
        {"check": "LIVE_ASSIGNMENT_AUTHORIZED", "value": total_live_yes, "required": 0,
         "status": "PASS" if total_live_yes == 0 else "FAIL"},
    ]
    gate_path = csv_root / "multi_day_allocation_gate.csv"
    with gate_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["check", "value", "required", "status"])
        writer.writeheader()
        writer.writerows(gate_checks)

    gate_failures = sum(row["status"] != "PASS" for row in gate_checks)
    monthly_files: list[str] = []
    summary_workbook = ""

    if not args.skip_excel:
        months: dict[str, list[date]] = defaultdict(list)
        for day in expected_dates:
            months[day.strftime("%Y-%m")].append(day)
        for month_key, month_dates in sorted(months.items()):
            path = write_monthly_workbook(month_key, month_dates, day_folders, excel_root)
            monthly_files.append(str(path.relative_to(output_root)))

    summary = {
        "status": PASS_MULTI if gate_failures == 0 else "PROTECTED_HYBRID_RL_MULTI_DAY_REVIEW_REQUIRED",
        "package_version": VERSION,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "expected_days": args.expected_days,
        "completed_days": len(day_folders),
        "estates_per_day": 33,
        "scenarios_per_day": 2,
        "episodes": total_episodes,
        "employee_allocation_rows": total_employee_rows,
        "expected_employee_rows": sinks["EXPECTED"].rows,
        "conservative_employee_rows": sinks["CONSERVATIVE"].rows,
        "field_rows": total_field_rows,
        "policy_decision_rows": sinks["POLICY"].rows,
        "action_audit_rows": sinks["ACTION"].rows,
        "rl_model_invoked_episodes": total_model_invoked,
        "final_policy_counts": dict(policy_counts),
        "rl_actions_used": total_rl_actions,
        "accepted_move_count": total_moves,
        "safety_violations": total_safety,
        "duplicate_assignment_failures": total_duplicates,
        "excel_created": not args.skip_excel,
        "monthly_excel_files": monthly_files,
        "forecasting": True,
        "plucker_demand_calculation": True,
        "named_employee_allocation": True,
        "protected_hybrid_rl_inference": True,
        "rl_model_retraining": False,
        "protected_hybrid_rl_allocation_used": True,
        "safety_shield_enabled": True,
        "greedy_fallback_enabled": True,
        "current_roster_future_date_simulation": True,
        "employee_home_code_verified": False,
        "attendance_verified": False,
        "approved_leave_verified": False,
        "fitness_verified": False,
        "movement_restrictions_verified": False,
        "operational_use_allowed": False,
        "live_assignment_authorized": False,
    }

    if not args.skip_excel:
        summary_path = excel_root / "TTE_Forecasting_Protected_Hybrid_RL_Block_Summary.xlsx"
        write_summary_workbook(summary_path, daily_rows, summary)
        summary_workbook = str(summary_path.relative_to(output_root))
        summary["summary_workbook"] = summary_workbook

    (output_root / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    month_links = "".join(
        f"<li><a href='{html.escape(path.replace(chr(92), '/'))}'>{html.escape(Path(path).name)}</a></li>"
        for path in monthly_files
    )
    summary_link = (
        f"<p><a href='{html.escape(summary_workbook.replace(chr(92), '/'))}'><strong>Open the block Excel summary</strong></a></p>"
        if summary_workbook else "<p>Excel creation was skipped. Open the combined CSV files in Excel.</p>"
    )

    dashboard = f"""<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>
<title>TTE Forecasting + Protected Hybrid RL Block Results</title>
<style>
body{{font-family:Arial,sans-serif;margin:28px;color:#222}}h1,h2{{color:#1b5e20}}
.cards{{display:grid;grid-template-columns:repeat(4,minmax(180px,1fr));gap:12px}}
.card{{background:#f3f8f3;border:1px solid #c8e6c9;border-radius:8px;padding:16px}}
.card strong{{display:block;font-size:24px;color:#1b5e20}}
.notice{{background:#fff8e1;border-left:6px solid #f9a825;padding:14px;margin:18px 0}}
a{{color:#1b5e20}}table{{border-collapse:collapse}}th,td{{border:1px solid #ddd;padding:7px}}th{{background:#1b5e20;color:white}}
</style></head><body>
<h1>TTE Forecasting + Protected Hybrid RL Block Shadow Allocation</h1>
<p><strong>Period:</strong> {html.escape(args.start_date)} to {html.escape(args.end_date)}</p>
<div class='cards'>
<div class='card'><strong>{len(day_folders)}</strong>Passing dates</div>
<div class='card'><strong>{total_model_invoked:,}</strong>RL model-invoked episodes</div>
<div class='card'><strong>{total_employee_rows:,}</strong>Named employee rows</div>
<div class='card'><strong>{total_safety}</strong>Safety violations</div>
</div>
<h2>Included workflow</h2><ul><li>Forecasting: YES</li><li>Plucker-demand calculation: YES</li><li>Named employee allocation: YES</li><li>Protected hybrid RL inference: YES</li><li>RL model retraining: NO</li><li>Safety shield: YES</li><li>Greedy fallback: YES</li><li>Live operational authorization: NO</li></ul><div class='notice'>Protected shadow simulation only. Current roster data is reused for future dates. Attendance, approved leave, fitness, movement restrictions, home-code verification, operational use and live authorization remain NO.</div>
<h2>Excel results</h2>{summary_link}<ul>{month_links}</ul>
<h2>Combined CSV results</h2>
<ul>
<li><a href='combined_csv/expected_employee_allocations.csv'>Expected named employee allocations</a></li>
<li><a href='combined_csv/conservative_employee_allocations.csv'>Conservative named employee allocations</a></li>
<li><a href='combined_csv/policy_decisions.csv'>Policy decisions</a></li>
<li><a href='combined_csv/field_results.csv'>Field results</a></li>
<li><a href='combined_csv/rl_action_audit.csv'>RL action audit</a></li>
<li><a href='combined_csv/daily_summary.csv'>Daily summary</a></li>
<li><a href='combined_csv/multi_day_allocation_gate.csv'>Multi-day safety gate</a></li>
</ul>
</body></html>"""
    (output_root / "START_HERE.html").write_text(dashboard, encoding="utf-8")

    print("\nPROTECTED HYBRID RL MULTI-DAY CONSOLIDATION FINISHED")
    print(json.dumps(summary, indent=2))
    return 0 if gate_failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
