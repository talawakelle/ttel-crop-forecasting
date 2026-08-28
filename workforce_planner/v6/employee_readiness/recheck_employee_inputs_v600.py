from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def estate_key(value: str) -> str:
    return "".join(ch for ch in clean(value).lower() if ch.isalnum())


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-folder", required=True)
    args = parser.parse_args()

    run_folder = Path(args.run_folder).resolve()
    availability_path = run_folder / "templates" / "employee_availability_template.csv"
    constraints_path = run_folder / "templates" / "employee_constraints_template.csv"
    candidate_path = run_folder / "candidates" / "first_date_field_employee_candidate_matrix.csv"
    readiness_path = run_folder / "quality" / "cp_sat_readiness_gate.csv"

    for path in (availability_path, constraints_path, candidate_path, readiness_path):
        if not path.exists():
            raise SystemExit(f"Missing required file: {path}")

    availability = read_csv(availability_path)
    constraints = read_csv(constraints_path)
    candidates = read_csv(candidate_path)
    base_gate = read_csv(readiness_path)

    availability_confirmed: defaultdict[str, set[str]] = defaultdict(set)
    available_ids: defaultdict[str, set[str]] = defaultdict(set)
    medically_fit_ids: defaultdict[str, set[str]] = defaultdict(set)

    for row in availability:
        key = estate_key(row["estate"])
        employee_id = row["employee_id"]
        confirmed = clean(row.get("supervisor_confirmed")).upper() == "YES"
        status = clean(row.get("available_status")).upper()
        medically_fit = clean(row.get("medically_fit_for_plucking")).upper()
        leave_status = clean(row.get("leave_status")).upper()

        if confirmed and status in {"AVAILABLE", "UNAVAILABLE"}:
            availability_confirmed[key].add(employee_id)
        if confirmed and status == "AVAILABLE" and leave_status not in {"ON_LEAVE", "LEAVE", "YES"}:
            available_ids[key].add(employee_id)
        if confirmed and medically_fit == "YES":
            medically_fit_ids[key].add(employee_id)

    constraints_confirmed: defaultdict[str, set[str]] = defaultdict(set)
    allowed_ids: defaultdict[str, set[str]] = defaultdict(set)

    for row in constraints:
        key = estate_key(row["estate"])
        employee_id = row["employee_id"]
        confirmed = clean(row.get("supervisor_confirmed")).upper() == "YES"
        cross_division = clean(row.get("cross_division_allowed")).upper()
        restriction = clean(row.get("restriction_status")).upper()

        if (
            confirmed
            and cross_division in {"YES", "NO"}
            and restriction in {"NONE", "RESTRICTED"}
        ):
            constraints_confirmed[key].add(employee_id)
            allowed_ids[key].add(employee_id)

    eligible_ids = {
        key: (
            available_ids[key]
            & medically_fit_ids[key]
            & allowed_ids[key]
        )
        for key in set(available_ids) | set(allowed_ids)
    }

    candidate_fields: defaultdict[tuple[str, str, str, str], set[str]] = defaultdict(set)
    required_by_field: dict[tuple[str, str, str, str], int] = {}
    for row in candidates:
        key = estate_key(row["estate"])
        field_key = (row["date"], key, row["division"], row["field"])
        required_by_field[field_key] = int(float(row["recommended_plucker_assignments"]))
        if row["employee_id"] in eligible_ids.get(key, set()):
            candidate_fields[field_key].add(row["employee_id"])

    field_status_by_estate: defaultdict[str, list[bool]] = defaultdict(list)
    for field_key, required in required_by_field.items():
        _, key, _, _ = field_key
        field_status_by_estate[key].append(
            len(candidate_fields.get(field_key, set())) >= required
        )

    output_rows = []
    for row in base_gate:
        key = estate_key(row["estate"])
        total_fields = len(field_status_by_estate.get(key, []))
        passing_fields = sum(field_status_by_estate.get(key, []))
        demand = int(float(row["recommended_assignment_demand"]))
        eligible_count = len(eligible_ids.get(key, set()))

        ready = (
            total_fields > 0
            and passing_fields == total_fields
            and eligible_count >= demand
        )

        output_rows.append({
            "date": row["date"],
            "estate": row["estate"],
            "recommended_assignment_demand": demand,
            "availability_confirmed_employees": len(availability_confirmed.get(key, set())),
            "constraints_confirmed_employees": len(constraints_confirmed.get(key, set())),
            "eligible_employee_pool": eligible_count,
            "active_fields": total_fields,
            "fields_with_confirmed_eligible_coverage": passing_fields,
            "confirmed_field_coverage_pct": (
                round(passing_fields / total_fields * 100, 2)
                if total_fields else 0.0
            ),
            "necessary_supply_check": (
                "PASS" if eligible_count >= demand else "FAIL"
            ),
            "cp_sat_readiness": (
                "READY_FOR_CP_SAT_SHADOW_INPUT"
                if ready
                else "NOT_READY_INPUT_CONFIRMATION_OR_COVERAGE_GAP"
            ),
            "cp_sat_started": "FALSE",
        })

    output_path = run_folder / "quality" / "cp_sat_input_recheck.csv"
    write_csv(
        output_path,
        output_rows,
        [
            "date", "estate", "recommended_assignment_demand",
            "availability_confirmed_employees",
            "constraints_confirmed_employees", "eligible_employee_pool",
            "active_fields", "fields_with_confirmed_eligible_coverage",
            "confirmed_field_coverage_pct", "necessary_supply_check",
            "cp_sat_readiness", "cp_sat_started",
        ],
    )

    summary = {
        "recheck_time": datetime.now().isoformat(timespec="seconds"),
        "estates": len(output_rows),
        "ready_estates": sum(
            1 for row in output_rows
            if row["cp_sat_readiness"] == "READY_FOR_CP_SAT_SHADOW_INPUT"
        ),
        "not_ready_estates": sum(
            1 for row in output_rows
            if row["cp_sat_readiness"] != "READY_FOR_CP_SAT_SHADOW_INPUT"
        ),
        "cp_sat_started": False,
        "output": str(output_path),
    }
    (run_folder / "quality" / "cp_sat_input_recheck_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
