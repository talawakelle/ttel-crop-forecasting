from __future__ import annotations

import argparse
import csv
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

PASS_BLOCK = "PASS_PROTECTED_HYBRID_RL_MULTI_DAY_SHADOW_ALLOCATION"
PASS_MASTER = "PASS_FORECASTING_PROTECTED_HYBRID_RL_CONTINUOUS_SHADOW_PROJECT"
IN_PROGRESS = "FORECASTING_PROTECTED_HYBRID_RL_CONTINUOUS_IN_PROGRESS"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def integer(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(str(value).replace(",", "").strip())))
    except (TypeError, ValueError):
        return default


def read_plan(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-root", required=True)
    parser.add_argument("--plan-file", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--skip-excel", action="store_true")
    args = parser.parse_args()

    master_root = Path(args.master_root).resolve()
    plan_file = Path(args.plan_file).resolve()
    plan_rows = read_plan(plan_file)

    index_rows: list[dict[str, Any]] = []
    monthly_rows: list[dict[str, Any]] = []

    totals = {
        "planned_days": 0,
        "completed_days": 0,
        "episodes": 0,
        "employee_allocation_rows": 0,
        "rl_model_invoked_episodes": 0,
        "rl_actions_used": 0,
        "accepted_move_count": 0,
        "safety_violations": 0,
        "duplicate_assignment_failures": 0,
    }
    completed_blocks = 0

    for plan in plan_rows:
        block_number = integer(plan.get("block_number"))
        days = integer(plan.get("days"))
        totals["planned_days"] += days
        rel_folder = plan["output_folder"]
        block_folder = master_root / rel_folder
        summary_path = block_folder / "run_summary.json"
        summary: dict[str, Any] = {}
        status = "NOT_STARTED"

        if summary_path.exists():
            try:
                summary = read_json(summary_path)
                status = str(summary.get("status", "UNKNOWN"))
            except Exception as exc:
                status = f"INVALID_SUMMARY: {exc}"

        passed = status == PASS_BLOCK
        if passed:
            completed_blocks += 1
            totals["completed_days"] += integer(summary.get("completed_days"))
            for key in (
                "episodes",
                "employee_allocation_rows",
                "rl_model_invoked_episodes",
                "rl_actions_used",
                "accepted_move_count",
                "safety_violations",
                "duplicate_assignment_failures",
            ):
                totals[key] += integer(summary.get(key))

        index_rows.append(
            {
                "block_number": block_number,
                "start_date": plan["start_date"],
                "end_date": plan["end_date"],
                "days": days,
                "status": status,
                "completed_days": integer(summary.get("completed_days")),
                "episodes": integer(summary.get("episodes")),
                "employee_allocation_rows": integer(summary.get("employee_allocation_rows")),
                "rl_model_invoked_episodes": integer(summary.get("rl_model_invoked_episodes")),
                "rl_actions_used": integer(summary.get("rl_actions_used")),
                "accepted_move_count": integer(summary.get("accepted_move_count")),
                "safety_violations": integer(summary.get("safety_violations")),
                "duplicate_assignment_failures": integer(summary.get("duplicate_assignment_failures")),
                "forecasting": "YES" if passed else "",
                "plucker_demand_calculation": "YES" if passed else "",
                "named_employee_allocation": "YES" if passed else "",
                "protected_hybrid_rl_inference": "YES" if passed else "",
                "rl_model_retraining": "NO",
                "safety_shield": "YES" if passed else "",
                "greedy_fallback": "YES" if passed else "",
                "live_operational_authorization": "NO",
                "output_folder": rel_folder,
                "start_page": f"{rel_folder}/START_HERE.html",
            }
        )

        excel_root = block_folder / "excel"
        if excel_root.exists():
            for workbook in sorted(excel_root.glob("*.xlsx")):
                rel_path = workbook.relative_to(master_root).as_posix()
                monthly_rows.append(
                    {
                        "block_number": block_number,
                        "block_start_date": plan["start_date"],
                        "block_end_date": plan["end_date"],
                        "workbook_name": workbook.name,
                        "workbook_path": rel_path,
                    }
                )

    all_blocks_passed = completed_blocks == len(plan_rows) and len(plan_rows) > 0
    status = PASS_MASTER if all_blocks_passed else IN_PROGRESS

    summary = {
        "status": status,
        "package_version": "16.0.0",
        "start_date": args.start_date,
        "end_date": args.end_date,
        "planned_blocks": len(plan_rows),
        "completed_blocks": completed_blocks,
        **totals,
        "forecasting": True,
        "plucker_demand_calculation": True,
        "named_employee_allocation": True,
        "protected_hybrid_rl_inference": True,
        "rl_model_retraining": False,
        "safety_shield": True,
        "greedy_fallback": True,
        "current_roster_future_date_simulation": True,
        "employee_home_code_verified": False,
        "attendance_verified": False,
        "approved_leave_verified": False,
        "fitness_verified": False,
        "movement_restrictions_verified": False,
        "operational_use_allowed": False,
        "live_assignment_authorized": False,
        "last_index_refresh": datetime.now().isoformat(timespec="seconds"),
    }

    master_dir = master_root / "master"
    master_dir.mkdir(parents=True, exist_ok=True)

    block_fields = list(index_rows[0].keys()) if index_rows else []
    write_csv(master_dir / "master_block_index.csv", index_rows, block_fields)

    monthly_fields = list(monthly_rows[0].keys()) if monthly_rows else [
        "block_number", "block_start_date", "block_end_date", "workbook_name", "workbook_path"
    ]
    write_csv(master_dir / "monthly_workbook_index.csv", monthly_rows, monthly_fields)

    (master_root / "run_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    summary_workbook = ""
    if not args.skip_excel:
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Font, PatternFill

            wb = Workbook()
            ws = wb.active
            ws.title = "Overview"
            ws["A1"] = "TTE Forecasting + Protected Hybrid RL Continuous Shadow Project"
            ws["A1"].font = Font(bold=True, size=16, color="1B5E20")
            ws.merge_cells("A1:D1")

            metrics = [
                ("Status", status),
                ("Period", f"{args.start_date} to {args.end_date}"),
                ("Planned blocks", len(plan_rows)),
                ("Completed blocks", completed_blocks),
                ("Planned days", totals["planned_days"]),
                ("Completed days", totals["completed_days"]),
                ("Forecasting", "YES"),
                ("Plucker-demand calculation", "YES"),
                ("Named employee allocation", "YES"),
                ("Protected hybrid RL inference", "YES"),
                ("RL model retraining", "NO"),
                ("Safety shield", "YES"),
                ("Greedy fallback", "YES"),
                ("Live operational authorization", "NO"),
                ("Named employee rows", totals["employee_allocation_rows"]),
                ("RL model-invoked episodes", totals["rl_model_invoked_episodes"]),
                ("RL actions used", totals["rl_actions_used"]),
                ("Accepted moves", totals["accepted_move_count"]),
                ("Safety violations", totals["safety_violations"]),
                ("Duplicate failures", totals["duplicate_assignment_failures"]),
            ]
            ws.append([])
            ws.append(["Metric", "Value"])
            for cell in ws[3]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="1B5E20")
            for metric, value in metrics:
                ws.append([metric, value])
            ws.column_dimensions["A"].width = 38
            ws.column_dimensions["B"].width = 48

            notice_row = ws.max_row + 2
            ws.cell(notice_row, 1, "Important")
            ws.cell(notice_row, 1).font = Font(bold=True, color="9C6500")
            ws.cell(
                notice_row,
                2,
                "This is overnight batch processing and protected hybrid RL inference, not RL model retraining. All future named employee allocations are current-roster shadow simulations. Attendance, approved leave, fitness, movement restrictions, home-code verification, operational use and live authorization remain NO.",
            )
            ws.cell(notice_row, 2).alignment = Alignment(wrap_text=True, vertical="top")
            ws.row_dimensions[notice_row].height = 74

            blocks_ws = wb.create_sheet("Block Index")
            blocks_ws.append(block_fields)
            for cell in blocks_ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="1B5E20")
                cell.alignment = Alignment(horizontal="center", wrap_text=True)
            for row in index_rows:
                blocks_ws.append([row.get(field, "") for field in block_fields])
            blocks_ws.freeze_panes = "A2"
            blocks_ws.auto_filter.ref = blocks_ws.dimensions

            monthly_ws = wb.create_sheet("Monthly Workbooks")
            monthly_ws.append(monthly_fields)
            for cell in monthly_ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="1B5E20")
            for row in monthly_rows:
                monthly_ws.append([row.get(field, "") for field in monthly_fields])
            monthly_ws.freeze_panes = "A2"
            monthly_ws.auto_filter.ref = monthly_ws.dimensions

            workbook_path = master_dir / "TTE_Forecasting_Protected_Hybrid_RL_Continuous_Summary.xlsx"
            wb.save(workbook_path)
            summary_workbook = workbook_path.relative_to(master_root).as_posix()
            summary["summary_workbook"] = summary_workbook
            (master_root / "run_summary.json").write_text(
                json.dumps(summary, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            summary["excel_error"] = str(exc)
            (master_root / "run_summary.json").write_text(
                json.dumps(summary, indent=2), encoding="utf-8"
            )

    block_links = []
    for row in index_rows:
        start_page = html.escape(row["start_page"])
        block_links.append(
            "<tr>"
            f"<td>{row['block_number']}</td>"
            f"<td>{html.escape(str(row['start_date']))}</td>"
            f"<td>{html.escape(str(row['end_date']))}</td>"
            f"<td>{row['days']}</td>"
            f"<td>{html.escape(str(row['status']))}</td>"
            f"<td><a href='{start_page}'>Open block</a></td>"
            "</tr>"
        )

    workbook_links = "".join(
        f"<li><a href='{html.escape(row['workbook_path'])}'>{html.escape(row['workbook_name'])}</a> "
        f"(Block {row['block_number']})</li>"
        for row in monthly_rows
    )
    summary_link = (
        f"<p><a href='{html.escape(summary_workbook)}'><strong>Open continuous project Excel summary</strong></a></p>"
        if summary_workbook
        else "<p>Excel summary was skipped or could not be created.</p>"
    )

    dashboard = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>TTE Forecasting + Protected Hybrid RL Continuous Project</title>
<style>
body{{font-family:Arial,sans-serif;margin:28px;color:#222}}
h1,h2{{color:#1b5e20}}
.cards{{display:grid;grid-template-columns:repeat(4,minmax(180px,1fr));gap:12px}}
.card{{background:#f3f8f3;border:1px solid #c8e6c9;border-radius:8px;padding:16px}}
.card strong{{display:block;font-size:24px;color:#1b5e20}}
.notice{{background:#fff8e1;border-left:6px solid #f9a825;padding:14px;margin:18px 0}}
a{{color:#1b5e20}}table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ddd;padding:7px}}th{{background:#1b5e20;color:white}}
</style></head><body>
<h1>TTE Forecasting + Protected Hybrid RL Continuous Shadow Project</h1>
<p><strong>Period:</strong> {html.escape(args.start_date)} to {html.escape(args.end_date)}</p>
<div class="cards">
<div class="card"><strong>{completed_blocks}/{len(plan_rows)}</strong>Completed blocks</div>
<div class="card"><strong>{totals['completed_days']:,}</strong>Completed dates</div>
<div class="card"><strong>{totals['employee_allocation_rows']:,}</strong>Named employee rows</div>
<div class="card"><strong>{totals['safety_violations']}</strong>Safety violations</div>
</div>
<h2>Included workflow</h2>
<ul>
<li>Forecasting: YES</li>
<li>Plucker-demand calculation: YES</li>
<li>Named employee allocation: YES</li>
<li>Protected hybrid RL inference: YES</li>
<li>RL model retraining: NO</li>
<li>Safety shield: YES</li>
<li>Greedy fallback: YES</li>
<li>Live operational authorization: NO</li>
</ul>
<div class="notice">This is resumable overnight processing and protected hybrid RL inference, not model retraining. Future named employee allocations remain current-roster shadow simulations. Attendance, leave, fitness, movement restrictions, home-code verification and live authorization remain NO.</div>
{summary_link}
<h2>Block results</h2>
<table><tr><th>Block</th><th>Start</th><th>End</th><th>Days</th><th>Status</th><th>Results</th></tr>
{''.join(block_links)}
</table>
<h2>Monthly Excel workbooks</h2>
<ul>{workbook_links}</ul>
</body></html>"""
    (master_root / "START_HERE.html").write_text(dashboard, encoding="utf-8")

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
