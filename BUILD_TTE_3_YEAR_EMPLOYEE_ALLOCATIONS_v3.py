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
from typing import Any, Iterator


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def canon(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", clean(value).upper())


ESTATE_ALIASES = {
    "BAMBRAKELLY": "BAMBARAKELLY",
    "GLASSAUGH": "GLASSUGH",
    "OILPHANT": "OLIPHANT",
    "NUWARAELIYA": "NUWARAELIYA",
    "UDARADELLA": "UDARADELLA",
    "EILDONHALL": "EILDONHALL",
}


def estate_key(value: Any) -> str:
    key = canon(value)
    return ESTATE_ALIASES.get(key, key)


def as_float(value: Any) -> float | None:
    text = clean(value)
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def as_int_count(value: Any) -> int:
    number = as_float(value)
    if number is None or number <= 0:
        return 0
    return int(math.ceil(number - 1e-9))


def parse_date(value: Any) -> date:
    text = clean(value)
    if not text:
        raise ValueError("blank date")
    return datetime.fromisoformat(text.replace("Z", "+00:00")).date()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def choose_exact_or_tokens(
    headers: list[str],
    exact: list[str],
    token_options: list[tuple[str, ...]],
) -> str | None:
    lower_map = {header.lower(): header for header in headers}

    for candidate in exact:
        result = lower_map.get(candidate.lower())
        if result:
            return result

    for tokens in token_options:
        for header in headers:
            lowered = header.lower()
            if all(token in lowered for token in tokens):
                return header

    return None


def safe_name(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    return text.strip("_") or "estate"


def planning_year(d: date, start: date) -> int:
    if d < start.replace(year=start.year + 1):
        return 1
    if d < start.replace(year=start.year + 2):
        return 2
    return 3


class PartitionWriter:
    def __init__(self, root: Path, fields: list[str]) -> None:
        self.root = root
        self.fields = fields
        self.handles: dict[tuple[str, str, int], Any] = {}
        self.writers: dict[tuple[str, str, int], csv.DictWriter] = {}

    def write(
        self,
        estate: str,
        scenario: str,
        year_no: int,
        row: dict[str, Any],
    ) -> None:
        key = (estate, scenario, year_no)

        if key not in self.writers:
            folder = (
                self.root
                / scenario
                / safe_name(estate)
            )
            folder.mkdir(parents=True, exist_ok=True)

            path = folder / f"Planning_Year_{year_no}.csv"
            handle = path.open("w", newline="", encoding="utf-8-sig")
            writer = csv.DictWriter(
                handle,
                fieldnames=self.fields,
                extrasaction="ignore",
            )
            writer.writeheader()

            self.handles[key] = handle
            self.writers[key] = writer

        self.writers[key].writerow(row)

    def close(self) -> None:
        for handle in self.handles.values():
            handle.close()
        self.handles.clear()
        self.writers.clear()


def build_employee_pools(
    template_path: Path,
) -> tuple[
    dict[tuple[str, str], list[dict[str, Any]]],
    dict[str, str],
]:
    rows = read_csv(template_path)
    if not rows:
        raise SystemExit("Employee allocation template is empty.")

    required = {
        "scenario",
        "estate",
        "employee_key",
        "employee_id",
        "allocation_division_context",
        "field",
        "employee_daily_capacity_kg",
    }
    missing = required - set(rows[0])
    if missing:
        raise SystemExit(
            "Employee template is missing columns: "
            + ", ".join(sorted(missing))
        )

    pools: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    estate_display: dict[str, str] = {}

    for row in rows:
        estate = clean(row.get("estate"))
        estate_id = estate_key(estate)
        scenario = clean(row.get("scenario")).upper()
        employee_id = clean(row.get("employee_id"))

        if not estate_id or scenario not in {"EXPECTED", "CONSERVATIVE"}:
            continue
        if not employee_id:
            continue

        estate_display.setdefault(estate_id, estate)

        employee = {
            "employee_key": clean(row.get("employee_key")),
            "employee_id": employee_id,
            "baseline_division": clean(
                row.get("allocation_division_context")
            ),
            "baseline_field": clean(row.get("field")),
            "official_assigned_division_code": clean(
                row.get("official_assigned_division_code")
            ),
            "employee_home_division_code_observed": clean(
                row.get("employee_home_division_code_observed")
            ),
            "employee_home_code_exception": clean(
                row.get("employee_home_code_exception")
            ) or "NO",
            "employee_daily_capacity_kg": (
                as_float(row.get("employee_daily_capacity_kg")) or 0.0
            ),
        }

        pools[(estate_id, scenario)].setdefault(employee_id, employee)

    final_pools: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for key, employee_map in pools.items():
        final_pools[key] = sorted(
            employee_map.values(),
            key=lambda item: item["employee_id"],
        )

    return final_pools, estate_display


def identify_field_columns(
    headers: list[str],
) -> dict[str, str | None]:
    return {
        "date": choose_exact_or_tokens(
            headers,
            ["date", "forecast_date", "allocation_date", "forecast_day"],
            [("forecast", "date"), ("date",)],
        ),
        "estate": choose_exact_or_tokens(
            headers,
            ["estate", "estate_name"],
            [("estate",)],
        ),
        "division": choose_exact_or_tokens(
            headers,
            ["division", "division_name", "allocation_division_context"],
            [("division",)],
        ),
        "field": choose_exact_or_tokens(
            headers,
            ["field", "field_name", "field_code"],
            [("field",)],
        ),
        "expected_count": choose_exact_or_tokens(
            headers,
            [
                "expected_plucker_assignments",
                "expected_required_pluckers",
                "expected_pluckers",
            ],
            [
                ("expected", "plucker", "assignment"),
                ("expected", "plucker"),
            ],
        ),
        "conservative_count": choose_exact_or_tokens(
            headers,
            [
                "recommended_assignment_demand",
                "recommended_plucker_assignments",
                "conservative_plucker_assignments",
                "recommended_assignments",
            ],
            [
                ("recommended", "assignment"),
                ("recommended", "plucker"),
                ("conservative", "plucker"),
            ],
        ),
        "central_crop": choose_exact_or_tokens(
            headers,
            [
                "central_crop_kg",
                "forecast_kg",
                "expected_crop_kg",
            ],
            [
                ("central", "crop", "kg"),
                ("forecast", "kg"),
            ],
        ),
        "upper_crop": choose_exact_or_tokens(
            headers,
            [
                "upper_conservative_crop_kg",
                "upper_80_kg",
                "conservative_crop_kg",
            ],
            [
                ("upper", "conservative", "crop"),
                ("upper", "kg"),
            ],
        ),
    }


def rotated(values: list[dict[str, Any]], offset: int) -> list[dict[str, Any]]:
    if not values:
        return []
    offset %= len(values)
    return values[offset:] + values[:offset]


def select_employees(
    pool: list[dict[str, Any]],
    used: set[str],
    division: str,
    field: str,
    required: int,
    rotation_offset: int,
) -> list[tuple[dict[str, Any], str]]:
    if required <= 0:
        return []

    ordered = rotated(pool, rotation_offset)
    division_id = canon(division)
    field_id = canon(field)

    exact_field: list[dict[str, Any]] = []
    same_division: list[dict[str, Any]] = []

    for employee in ordered:
        employee_id = employee["employee_id"]
        if employee_id in used:
            continue

        baseline_division = canon(employee["baseline_division"])
        baseline_field = canon(employee["baseline_field"])

        if division_id and baseline_division == division_id:
            if field_id and baseline_field == field_id:
                exact_field.append(employee)
            else:
                same_division.append(employee)

    selected: list[tuple[dict[str, Any], str]] = []

    for employee in exact_field:
        if len(selected) >= required:
            break
        selected.append((employee, "BASELINE_FIELD"))

    for employee in same_division:
        if len(selected) >= required:
            break
        selected.append((employee, "SAME_DIVISION_DIFFERENT_FIELD"))

    for employee, _ in selected:
        used.add(employee["employee_id"])

    return selected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v4-run", required=True)
    parser.add_argument("--v5-run", required=True)
    parser.add_argument("--field-demand", required=True)
    parser.add_argument("--employee-template", required=True)
    parser.add_argument("--output-folder", required=True)
    parser.add_argument("--forecast-start", required=True)
    parser.add_argument("--forecast-days", type=int, required=True)
    parser.add_argument("--expected-estates", type=int, default=33)
    args = parser.parse_args()

    v4_run = Path(args.v4_run).resolve()
    v5_run = Path(args.v5_run).resolve()
    field_demand_path = Path(args.field_demand).resolve()
    template_path = Path(args.employee_template).resolve()
    output = Path(args.output_folder).resolve()
    output.mkdir(parents=True, exist_ok=True)

    start = datetime.strptime(args.forecast_start, "%Y-%m-%d").date()
    expected_end = start + timedelta(days=args.forecast_days - 1)

    pools, estate_display = build_employee_pools(template_path)

    field_rows = read_csv(field_demand_path)
    if not field_rows:
        raise SystemExit("Field plucker-demand file is empty.")

    headers = list(field_rows[0].keys())
    columns = identify_field_columns(headers)

    required_columns = [
        "date",
        "estate",
        "division",
        "field",
        "expected_count",
        "conservative_count",
    ]
    missing = [name for name in required_columns if not columns.get(name)]
    if missing:
        raise SystemExit(
            "Could not identify field-demand columns: "
            + ", ".join(missing)
            + "\nHeaders found: "
            + ", ".join(headers)
        )

    normalized_demands: list[dict[str, Any]] = []
    for row in field_rows:
        try:
            forecast_date = parse_date(row.get(columns["date"]))
        except ValueError:
            continue

        estate = clean(row.get(columns["estate"]))
        division = clean(row.get(columns["division"]))
        field = clean(row.get(columns["field"]))

        normalized_demands.append({
            "date": forecast_date,
            "estate": estate,
            "estate_key": estate_key(estate),
            "division": division,
            "field": field,
            "expected_count": as_int_count(
                row.get(columns["expected_count"])
            ),
            "conservative_count": as_int_count(
                row.get(columns["conservative_count"])
            ),
            "central_crop_kg": (
                as_float(row.get(columns["central_crop"]))
                if columns.get("central_crop")
                else None
            ),
            "upper_conservative_crop_kg": (
                as_float(row.get(columns["upper_crop"]))
                if columns.get("upper_crop")
                else None
            ),
        })

    normalized_demands.sort(
        key=lambda row: (
            row["date"],
            row["estate_key"],
            canon(row["division"]),
            canon(row["field"]),
        )
    )

    distinct_dates = sorted({row["date"] for row in normalized_demands})
    distinct_estates = sorted(
        {row["estate_key"] for row in normalized_demands}
    )

    if len(distinct_dates) != args.forecast_days:
        raise SystemExit(
            f"Expected {args.forecast_days} forecast dates, "
            f"but field demand contains {len(distinct_dates)}."
        )

    if distinct_dates[0] != start or distinct_dates[-1] != expected_end:
        raise SystemExit(
            "Field-demand date range does not match the requested period: "
            f"{distinct_dates[0]} to {distinct_dates[-1]}"
        )

    if len(distinct_estates) != args.expected_estates:
        raise SystemExit(
            f"Expected {args.expected_estates} estates, "
            f"but field demand contains {len(distinct_estates)}."
        )

    allocation_fields = [
        "forecast_date",
        "planning_year",
        "scenario",
        "estate",
        "division",
        "field",
        "employee_key",
        "employee_id",
        "employee_daily_capacity_kg",
        "assignment_sequence",
        "assignment_basis",
        "official_assigned_division_code_reference",
        "employee_home_division_code_observed",
        "employee_home_code_exception",
        "field_required_pluckers",
        "field_central_crop_kg",
        "field_upper_conservative_crop_kg",
        "employee_home_code_verified",
        "attendance_verified",
        "approved_leave_verified",
        "fitness_verified",
        "movement_restrictions_verified",
        "operational_use_allowed",
        "live_assignment_authorized",
        "allocation_status",
    ]

    allocation_root = output / "Employee_Allocations"
    writer = PartitionWriter(allocation_root, allocation_fields)

    daily_summary_path = output / "TTE_Daily_Estate_Allocation_Summary.csv"
    field_summary_path = output / "TTE_Daily_Field_Allocation_Summary.csv"

    daily_summary_fields = [
        "forecast_date",
        "planning_year",
        "scenario",
        "estate",
        "required_pluckers",
        "assigned_employees",
        "unfilled_positions",
        "employee_pool",
        "central_crop_kg",
        "upper_conservative_crop_kg",
        "allocation_status",
    ]

    field_summary_fields = [
        "forecast_date",
        "planning_year",
        "scenario",
        "estate",
        "division",
        "field",
        "required_pluckers",
        "assigned_employees",
        "unfilled_positions",
        "central_crop_kg",
        "upper_conservative_crop_kg",
        "allocation_status",
    ]

    total_allocation_rows = 0
    total_required = defaultdict(int)
    total_assigned = defaultdict(int)
    total_unfilled = defaultdict(int)
    shortage_estate_days = 0

    grouped_by_date_estate: dict[
        tuple[date, str],
        list[dict[str, Any]],
    ] = defaultdict(list)

    for demand in normalized_demands:
        grouped_by_date_estate[
            (demand["date"], demand["estate_key"])
        ].append(demand)

    with daily_summary_path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as daily_handle, field_summary_path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as field_handle:
        daily_writer = csv.DictWriter(
            daily_handle,
            fieldnames=daily_summary_fields,
        )
        field_writer = csv.DictWriter(
            field_handle,
            fieldnames=field_summary_fields,
        )
        daily_writer.writeheader()
        field_writer.writeheader()

        group_items = sorted(
            grouped_by_date_estate.items(),
            key=lambda item: (item[0][0], item[0][1]),
        )

        for group_index, ((forecast_date, estate_id), demands) in enumerate(
            group_items
        ):
            estate = estate_display.get(
                estate_id,
                demands[0]["estate"],
            )
            day_index = (forecast_date - start).days
            year_no = planning_year(forecast_date, start)

            for scenario in ("EXPECTED", "CONSERVATIVE"):
                pool = pools.get((estate_id, scenario), [])
                used: set[str] = set()

                estate_required = 0
                estate_assigned = 0
                estate_unfilled = 0
                estate_central_crop = 0.0
                estate_upper_crop = 0.0

                for field_index, demand in enumerate(demands):
                    required = (
                        demand["expected_count"]
                        if scenario == "EXPECTED"
                        else demand["conservative_count"]
                    )

                    selected = select_employees(
                        pool=pool,
                        used=used,
                        division=demand["division"],
                        field=demand["field"],
                        required=required,
                        rotation_offset=day_index + field_index,
                    )

                    assigned_count = len(selected)
                    unfilled = max(0, required - assigned_count)

                    estate_required += required
                    estate_assigned += assigned_count
                    estate_unfilled += unfilled

                    if demand["central_crop_kg"] is not None:
                        estate_central_crop += demand["central_crop_kg"]
                    if demand["upper_conservative_crop_kg"] is not None:
                        estate_upper_crop += demand[
                            "upper_conservative_crop_kg"
                        ]

                    field_status = (
                        "FULLY_ALLOCATED_SIMULATION"
                        if unfilled == 0
                        else "SIMULATION_SHORTAGE_REVIEW"
                    )

                    field_writer.writerow({
                        "forecast_date": forecast_date.isoformat(),
                        "planning_year": year_no,
                        "scenario": scenario,
                        "estate": estate,
                        "division": demand["division"],
                        "field": demand["field"],
                        "required_pluckers": required,
                        "assigned_employees": assigned_count,
                        "unfilled_positions": unfilled,
                        "central_crop_kg": (
                            ""
                            if demand["central_crop_kg"] is None
                            else round(demand["central_crop_kg"], 4)
                        ),
                        "upper_conservative_crop_kg": (
                            ""
                            if demand["upper_conservative_crop_kg"] is None
                            else round(
                                demand["upper_conservative_crop_kg"],
                                4,
                            )
                        ),
                        "allocation_status": field_status,
                    })

                    for sequence, (employee, basis) in enumerate(
                        selected,
                        start=1,
                    ):
                        writer.write(
                            estate=estate,
                            scenario=scenario,
                            year_no=year_no,
                            row={
                                "forecast_date": forecast_date.isoformat(),
                                "planning_year": year_no,
                                "scenario": scenario,
                                "estate": estate,
                                "division": demand["division"],
                                "field": demand["field"],
                                "employee_key": employee["employee_key"],
                                "employee_id": employee["employee_id"],
                                "employee_daily_capacity_kg": round(
                                    employee["employee_daily_capacity_kg"],
                                    4,
                                ),
                                "assignment_sequence": sequence,
                                "assignment_basis": basis,
                                "official_assigned_division_code_reference": (
                                    employee[
                                        "official_assigned_division_code"
                                    ]
                                ),
                                "employee_home_division_code_observed": (
                                    employee[
                                        "employee_home_division_code_observed"
                                    ]
                                ),
                                "employee_home_code_exception": employee[
                                    "employee_home_code_exception"
                                ],
                                "field_required_pluckers": required,
                                "field_central_crop_kg": (
                                    ""
                                    if demand["central_crop_kg"] is None
                                    else round(
                                        demand["central_crop_kg"],
                                        4,
                                    )
                                ),
                                "field_upper_conservative_crop_kg": (
                                    ""
                                    if demand[
                                        "upper_conservative_crop_kg"
                                    ] is None
                                    else round(
                                        demand[
                                            "upper_conservative_crop_kg"
                                        ],
                                        4,
                                    )
                                ),
                                "employee_home_code_verified": "NO",
                                "attendance_verified": "NO",
                                "approved_leave_verified": "NO",
                                "fitness_verified": "NO",
                                "movement_restrictions_verified": "NO",
                                "operational_use_allowed": "NO",
                                "live_assignment_authorized": "NO",
                                "allocation_status": (
                                    "NAMED_EMPLOYEE_SIMULATION_ONLY"
                                ),
                            },
                        )
                        total_allocation_rows += 1

                estate_status = (
                    "FULLY_ALLOCATED_SIMULATION"
                    if estate_unfilled == 0
                    else "SIMULATION_SHORTAGE_REVIEW"
                )

                if estate_unfilled > 0:
                    shortage_estate_days += 1

                daily_writer.writerow({
                    "forecast_date": forecast_date.isoformat(),
                    "planning_year": year_no,
                    "scenario": scenario,
                    "estate": estate,
                    "required_pluckers": estate_required,
                    "assigned_employees": estate_assigned,
                    "unfilled_positions": estate_unfilled,
                    "employee_pool": len(pool),
                    "central_crop_kg": round(estate_central_crop, 4),
                    "upper_conservative_crop_kg": round(
                        estate_upper_crop,
                        4,
                    ),
                    "allocation_status": estate_status,
                })

                total_required[scenario] += estate_required
                total_assigned[scenario] += estate_assigned
                total_unfilled[scenario] += estate_unfilled

            if group_index % 500 == 0:
                print(
                    f"Processed {group_index + 1:,} of "
                    f"{len(group_items):,} estate-day groups"
                )

    writer.close()

    gate_rows = [
        {
            "check": "FORECAST_DATES",
            "value": len(distinct_dates),
            "required": args.forecast_days,
            "status": "PASS",
        },
        {
            "check": "ESTATES",
            "value": len(distinct_estates),
            "required": args.expected_estates,
            "status": "PASS",
        },
        {
            "check": "EXPECTED_REQUIRED_PLUCKER_ROWS_TOTAL",
            "value": total_required["EXPECTED"],
            "required": "INFORMATIONAL",
            "status": "PASS",
        },
        {
            "check": "EXPECTED_UNFILLED_POSITIONS_TOTAL",
            "value": total_unfilled["EXPECTED"],
            "required": 0,
            "status": (
                "PASS"
                if total_unfilled["EXPECTED"] == 0
                else "REVIEW"
            ),
        },
        {
            "check": "CONSERVATIVE_REQUIRED_PLUCKER_ROWS_TOTAL",
            "value": total_required["CONSERVATIVE"],
            "required": "INFORMATIONAL",
            "status": "PASS",
        },
        {
            "check": "CONSERVATIVE_UNFILLED_POSITIONS_TOTAL",
            "value": total_unfilled["CONSERVATIVE"],
            "required": 0,
            "status": (
                "PASS"
                if total_unfilled["CONSERVATIVE"] == 0
                else "REVIEW"
            ),
        },
        {
            "check": "EMPLOYEE_HOME_CODE_VERIFIED",
            "value": "NO",
            "required": "NO",
            "status": "PASS",
        },
        {
            "check": "ATTENDANCE_VERIFIED",
            "value": "NO",
            "required": "NO",
            "status": "PASS",
        },
        {
            "check": "LIVE_ASSIGNMENT_AUTHORIZED",
            "value": "NO",
            "required": "NO",
            "status": "PASS",
        },
    ]

    gate_path = output / "TTE_3_Year_Employee_Allocation_Gate.csv"
    with gate_path.open("w", newline="", encoding="utf-8-sig") as handle:
        gate_writer = csv.DictWriter(
            handle,
            fieldnames=["check", "value", "required", "status"],
        )
        gate_writer.writeheader()
        gate_writer.writerows(gate_rows)

    summary = {
        "status": "PASS_3_YEAR_DAILY_FORECAST_AND_EMPLOYEE_ALLOCATION_OUTPUTS",
        "forecast_start": distinct_dates[0].isoformat(),
        "forecast_end": distinct_dates[-1].isoformat(),
        "forecast_days": len(distinct_dates),
        "estates": len(distinct_estates),
        "field_demand_rows": len(normalized_demands),
        "named_employee_allocation_rows": total_allocation_rows,
        "expected_total_required_positions": total_required["EXPECTED"],
        "expected_total_assigned_positions": total_assigned["EXPECTED"],
        "expected_total_unfilled_positions": total_unfilled["EXPECTED"],
        "conservative_total_required_positions": total_required[
            "CONSERVATIVE"
        ],
        "conservative_total_assigned_positions": total_assigned[
            "CONSERVATIVE"
        ],
        "conservative_total_unfilled_positions": total_unfilled[
            "CONSERVATIVE"
        ],
        "estate_scenario_days_with_shortage": shortage_estate_days,
        "source_v4_run": str(v4_run),
        "source_v5_run": str(v5_run),
        "source_field_demand": str(field_demand_path),
        "source_employee_template": str(template_path),
        "allocation_mode": (
            "SAME_DIVISION_NAMED_EMPLOYEE_SIMULATION_WITH_DAILY_ROTATION"
        ),
        "employee_home_code_verified": False,
        "attendance_verified": False,
        "operational_use_allowed": False,
        "live_assignment_authorized": False,
    }

    (output / "run_summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    estate_links = []
    for estate_id in distinct_estates:
        estate = estate_display.get(estate_id, estate_id)
        estate_safe = safe_name(estate)
        estate_links.append(
            "<tr>"
            f"<td>{html.escape(estate)}</td>"
            f"<td><a href='Employee_Allocations/EXPECTED/"
            f"{html.escape(estate_safe)}/'>EXPECTED files</a></td>"
            f"<td><a href='Employee_Allocations/CONSERVATIVE/"
            f"{html.escape(estate_safe)}/'>CONSERVATIVE files</a></td>"
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
.cards {{ display: grid; grid-template-columns: repeat(4, minmax(160px,1fr));
gap: 12px; margin: 18px 0; }}
.card {{ background: #f3f8f3; border: 1px solid #c8e6c9;
border-radius: 8px; padding: 16px; }}
.card strong {{ display: block; font-size: 24px; color: #1b5e20; }}
.notice {{ background: #fff8e1; border-left: 6px solid #f9a825;
padding: 14px; margin: 18px 0; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #2e7d32; color: white; }}
tr:nth-child(even) {{ background: #f7f7f7; }}
a {{ color: #1565c0; }}
</style>
</head>
<body>
<h1>TTE 3-Year Daily Forecast and Employee Allocation</h1>
<p><strong>Period:</strong> {summary['forecast_start']} to
{summary['forecast_end']}</p>

<div class="cards">
<div class="card"><strong>{summary['estates']}</strong>Estates</div>
<div class="card"><strong>{summary['forecast_days']:,}</strong>Daily dates</div>
<div class="card"><strong>{summary['field_demand_rows']:,}</strong>Field-demand rows</div>
<div class="card"><strong>{summary['named_employee_allocation_rows']:,}</strong>Named allocation rows</div>
</div>

<div class="notice">
The same daily forecast-to-workforce process has been applied across
the full three-year period. Employee names are generated from the
current allocation roster and rotated within the same division.
Attendance, leave and fitness are not pre-confirmed for future dates,
so the output remains an employee allocation simulation until each
day is refreshed with actual employee status.
</div>

<h2>Main Results</h2>
<p><a href="TTE_Daily_Estate_Allocation_Summary.csv">
Daily estate allocation summary</a></p>
<p><a href="TTE_Daily_Field_Allocation_Summary.csv">
Daily field allocation summary</a></p>
<p><a href="TTE_3_Year_Employee_Allocation_Gate.csv">
Allocation quality gate</a></p>
<p><a href="run_summary.json">Run summary</a></p>

<h2>Estate Employee Allocation Files</h2>
<table>
<thead>
<tr><th>Estate</th><th>EXPECTED</th><th>CONSERVATIVE</th></tr>
</thead>
<tbody>
{''.join(estate_links)}
</tbody>
</table>
</body>
</html>
"""

    (output / "START_HERE.html").write_text(
        dashboard,
        encoding="utf-8",
    )

    print("")
    print("3-YEAR EMPLOYEE ALLOCATION BUILD FINISHED")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
