from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


VERSION = "13.0.1"
STATUS = "PASS_SIMULATION_NAMED_PLUCKER_ALLOCATION_KG_REPAIR_CREATED"
OPERATIONAL_STATUS = "DEVELOPMENT_SIMULATION_ONLY"


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def upper(value: Any) -> str:
    return clean(value).upper()


def number(value: Any) -> float | None:
    try:
        result = float(clean(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def normalized_headers(row: dict[str, Any]) -> dict[str, str]:
    return {
        clean(key).lower().replace(" ", "_"): key
        for key in row.keys()
    }


def alias_value(
    row: dict[str, Any],
    aliases: tuple[str, ...],
) -> str:
    headers = normalized_headers(row)
    for alias in aliases:
        source_key = headers.get(alias)
        if source_key is not None:
            value = clean(row.get(source_key))
            if value:
                return value
    return ""


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(
    path: Path,
    rows: Iterable[dict[str, Any]],
    fields: list[str],
) -> int:
    materialized = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(materialized)
    return len(materialized)


def latest_run(run_root: Path) -> Path:
    if not run_root.exists():
        raise SystemExit(f"Missing CP-SAT run root: {run_root}")

    candidates = sorted(
        [
            path
            for path in run_root.iterdir()
            if path.is_dir()
            and path.name.startswith("capacity_matching_")
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise SystemExit(
            f"No capacity_matching_* run folder was found under {run_root}"
        )
    return candidates[0]


def discover_assignment_file(
    cp_sat_run: Path,
) -> tuple[Path, list[dict[str, str]]]:
    employee_aliases = (
        "employee_id",
        "employee_no",
        "employee_number",
        "emp_id",
        "worker_id",
    )
    estate_aliases = ("estate", "estate_name")
    field_aliases = (
        "field",
        "field_name",
        "field_id",
        "field_code",
    )
    scenario_aliases = ("scenario", "demand_scenario")
    date_aliases = (
        "date",
        "allocation_date",
        "planning_date",
        "work_date",
    )

    candidates: list[
        tuple[int, int, int, Path, list[dict[str, str]]]
    ] = []

    for path in cp_sat_run.rglob("*.csv"):
        try:
            rows = read_csv(path)
        except Exception:
            continue
        if not rows:
            continue

        headers = {
            clean(key).lower().replace(" ", "_")
            for key in rows[0].keys()
        }
        has_employee = any(a in headers for a in employee_aliases)
        has_estate = any(a in headers for a in estate_aliases)
        has_field = any(a in headers for a in field_aliases)
        if not (has_employee and has_estate and has_field):
            continue

        name = path.name.lower()
        name_score = 0
        if "assignment" in name:
            name_score += 10
        if "employee" in name:
            name_score += 5
        if "field" in name:
            name_score += 2
        if "summary" in name or "failure" in name:
            name_score -= 10

        has_scenario = int(
            any(a in headers for a in scenario_aliases)
        )
        has_date = int(any(a in headers for a in date_aliases))
        row_score = -abs(len(rows) - 15014)

        candidates.append(
            (
                name_score + has_scenario + has_date,
                row_score,
                len(rows),
                path,
                rows,
            )
        )

    if not candidates:
        raise SystemExit(
            "No named employee-field assignment CSV was found "
            "inside the latest CP-SAT run."
        )

    candidates.sort(
        key=lambda item: (item[0], item[1], item[2]),
        reverse=True,
    )
    _, _, _, path, rows = candidates[0]
    return path, rows


def standardize_assignment(
    source: dict[str, Any],
) -> dict[str, Any]:
    date_value = alias_value(
        source,
        (
            "date",
            "allocation_date",
            "planning_date",
            "work_date",
        ),
    )
    scenario = alias_value(
        source,
        ("scenario", "demand_scenario"),
    )
    estate = alias_value(
        source,
        ("estate", "estate_name"),
    )
    division = alias_value(
        source,
        (
            "division",
            "division_name",
            "home_division",
            "assigned_division",
        ),
    )
    field_value = alias_value(
        source,
        (
            "field",
            "field_name",
            "field_id",
            "field_code",
        ),
    )
    employee_id = alias_value(
        source,
        (
            "employee_id",
            "employee_no",
            "employee_number",
            "emp_id",
            "worker_id",
        ),
    )

    crop_kg = alias_value(
        source,
        (
            "target_crop_kg",
            "field_crop_kg",
            "crop_kg",
            "expected_crop_kg",
            "required_crop_kg",
            "field_demand_kg",
        ),
    )
    capacity_kg = alias_value(
        source,
        (
            "expected_productivity_kg",
            "employee_capacity_kg",
            "capacity_kg",
            "plucker_capacity_kg",
            "recommended_capacity_kg",
            "productivity_kg",
        ),
    )
    allocated_kg = alias_value(
        source,
        (
            "field_assigned_capacity_kg",
            "allocated_kg",
            "allocated_capacity_kg",
            "assigned_capacity_kg",
            "effective_capacity_kg",
        ),
    )
    under_kg = alias_value(
        source,
        ("field_under_kg", "under_kg", "shortfall_kg"),
    )
    over_kg = alias_value(
        source,
        ("field_over_kg", "over_kg", "excess_kg"),
    )
    candidate_scope = alias_value(
        source,
        ("candidate_scope",),
    )
    cross_division = alias_value(
        source,
        ("cross_division",),
    )
    inferred_home_division = alias_value(
        source,
        ("inferred_home_division", "home_division"),
    )
    solver_status = alias_value(
        source,
        ("solver_status",),
    )
    assignment_method = alias_value(
        source,
        (
            "assignment_method",
            "allocation_method",
            "solver_method",
            "method",
        ),
    )

    return {
        "allocation_date": date_value,
        "scenario": scenario,
        "estate": estate,
        "division": division,
        "field": field_value,
        "employee_key": f"{estate}|{employee_id}",
        "employee_id": employee_id,
        "field_crop_kg": crop_kg,
        "plucker_capacity_kg": capacity_kg,
        "field_assigned_capacity_kg": allocated_kg,
        "field_under_kg": under_kg,
        "field_over_kg": over_kg,
        "candidate_scope": candidate_scope,
        "cross_division": cross_division,
        "inferred_home_division": inferred_home_division,
        "solver_status": solver_status,
        "source_assignment_method": (
            assignment_method or "CP_SAT_BASELINE"
        ),
        "supervisor_simulation_decision": "ACCEPT",
        "supervisor_acceptance_basis": (
            "USER_REQUESTED_SIMULATION_ACCEPT_ALL"
        ),
        "actual_supervisor_verified": "NO",
        "attendance_verified": "NO",
        "approved_leave_verified": "NO",
        "fitness_verified": "NO",
        "movement_restrictions_verified": "NO",
        "operational_use_allowed": "NO",
        "live_assignment_authorized": "NO",
        "allocation_status": (
            "SIMULATION_NAMED_ALLOCATION_FOR_REVIEW"
        ),
    }


def create_allocation(
    project_root: Path,
    output_root: Path,
) -> int:
    cp_sat_root = (
        project_root
        / "workforce_planner"
        / "v7"
        / "cp_sat_capacity_matching_runs"
    )
    cp_sat_run = latest_run(cp_sat_root)
    source_path, source_rows = discover_assignment_file(cp_sat_run)

    standardized = [
        standardize_assignment(row)
        for row in source_rows
    ]

    missing_identity = [
        row
        for row in standardized
        if not clean(row["estate"])
        or not clean(row["employee_id"])
        or not clean(row["field"])
    ]
    missing_crop_kg = [
        row for row in standardized
        if number(row["field_crop_kg"]) is None
    ]
    missing_plucker_capacity_kg = [
        row for row in standardized
        if number(row["plucker_capacity_kg"]) is None
    ]
    missing_field_capacity_kg = [
        row for row in standardized
        if number(row["field_assigned_capacity_kg"]) is None
    ]
    if missing_identity:
        raise SystemExit(
            f"Found {len(missing_identity)} rows with missing "
            "estate, employee_id or field."
        )
    if (
        missing_crop_kg
        or missing_plucker_capacity_kg
        or missing_field_capacity_kg
    ):
        raise SystemExit(
            "The v7.1 assignment source was found, but required kg "
            "values were missing. Missing field_crop_kg="
            f"{len(missing_crop_kg)}, missing plucker_capacity_kg="
            f"{len(missing_plucker_capacity_kg)}, missing "
            "field_assigned_capacity_kg="
            f"{len(missing_field_capacity_kg)}."
        )

    duplicate_keys: list[dict[str, Any]] = []
    seen: Counter[tuple[str, str, str, str]] = Counter()
    for row in standardized:
        key = (
            upper(row["allocation_date"]),
            upper(row["scenario"]),
            upper(row["estate"]),
            upper(row["employee_id"]),
        )
        seen[key] += 1

    for key, count in seen.items():
        if count > 1:
            duplicate_keys.append({
                "allocation_date": key[0],
                "scenario": key[1],
                "estate": key[2],
                "employee_id": key[3],
                "assignment_count": count,
            })

    run_folder = (
        output_root
        / datetime.now().strftime(
            "named_plucker_allocation_kg_repair_%Y%m%d_%H%M%S"
        )
    )
    allocation_dir = run_folder / "allocation"
    quality_dir = run_folder / "quality"
    summary_dir = run_folder / "summary"
    for folder in (allocation_dir, quality_dir, summary_dir):
        folder.mkdir(parents=True, exist_ok=True)

    fields = list(standardized[0].keys())
    allocation_path = (
        allocation_dir
        / "named_plucker_allocation_simulation.csv"
    )
    write_csv(allocation_path, standardized, fields)

    # Estate/scenario/date summary.
    grouped: dict[
        tuple[str, str, str],
        dict[str, Any],
    ] = defaultdict(
        lambda: {
            "assignment_rows": 0,
            "unique_employees": set(),
            "unique_fields": set(),
        }
    )

    for row in standardized:
        key = (
            row["allocation_date"],
            row["scenario"],
            row["estate"],
        )
        grouped[key]["assignment_rows"] += 1
        grouped[key]["unique_employees"].add(
            row["employee_id"]
        )
        grouped[key]["unique_fields"].add(row["field"])

    summary_rows = []
    for key in sorted(
        grouped,
        key=lambda value: (
            value[0],
            value[1],
            value[2].lower(),
        ),
    ):
        data = grouped[key]
        summary_rows.append({
            "allocation_date": key[0],
            "scenario": key[1],
            "estate": key[2],
            "assignment_rows": data["assignment_rows"],
            "unique_employees_assigned": len(
                data["unique_employees"]
            ),
            "unique_fields_covered": len(
                data["unique_fields"]
            ),
            "actual_supervisor_verified": "NO",
            "operational_use_allowed": "NO",
            "live_assignment_authorized": "NO",
        })

    write_csv(
        summary_dir / "estate_named_allocation_summary.csv",
        summary_rows,
        list(summary_rows[0].keys()),
    )

    write_csv(
        quality_dir / "duplicate_employee_assignment_check.csv",
        duplicate_keys,
        [
            "allocation_date",
            "scenario",
            "estate",
            "employee_id",
            "assignment_count",
        ],
    )

    route_counts = Counter(
        row["source_assignment_method"]
        for row in standardized
    )
    dates = sorted(
        {
            row["allocation_date"]
            for row in standardized
            if row["allocation_date"]
        }
    )
    scenarios = sorted(
        {
            row["scenario"]
            for row in standardized
            if row["scenario"]
        }
    )
    estates = sorted(
        {
            row["estate"]
            for row in standardized
            if row["estate"]
        },
        key=str.lower,
    )

    gate_status = (
        "PASS"
        if not duplicate_keys
        and not missing_crop_kg
        and not missing_plucker_capacity_kg
        and not missing_field_capacity_kg
        and len(standardized) > 0
        else "FAIL"
    )
    gate_rows = [
        {
            "check": "NAMED_ASSIGNMENT_ROWS",
            "value": len(standardized),
            "required": ">0",
            "status": (
                "PASS" if len(standardized) > 0 else "FAIL"
            ),
        },
        {
            "check": "MISSING_IDENTITY_ROWS",
            "value": len(missing_identity),
            "required": 0,
            "status": (
                "PASS" if not missing_identity else "FAIL"
            ),
        },
        {
            "check": "DUPLICATE_EMPLOYEE_ASSIGNMENTS",
            "value": len(duplicate_keys),
            "required": 0,
            "status": (
                "PASS" if not duplicate_keys else "FAIL"
            ),
        },
        {
            "check": "MISSING_FIELD_CROP_KG",
            "value": len(missing_crop_kg),
            "required": 0,
            "status": (
                "PASS" if not missing_crop_kg else "FAIL"
            ),
        },
        {
            "check": "MISSING_PLUCKER_CAPACITY_KG",
            "value": len(missing_plucker_capacity_kg),
            "required": 0,
            "status": (
                "PASS"
                if not missing_plucker_capacity_kg
                else "FAIL"
            ),
        },
        {
            "check": "MISSING_FIELD_ASSIGNED_CAPACITY_KG",
            "value": len(missing_field_capacity_kg),
            "required": 0,
            "status": (
                "PASS"
                if not missing_field_capacity_kg
                else "FAIL"
            ),
        },
        {
            "check": "ACTUAL_SUPERVISOR_VERIFIED",
            "value": False,
            "required": False,
            "status": "PASS",
        },
        {
            "check": "LIVE_ASSIGNMENT_AUTHORIZED",
            "value": False,
            "required": False,
            "status": "PASS",
        },
    ]
    write_csv(
        quality_dir / "named_allocation_creation_gate.csv",
        gate_rows,
        ["check", "value", "required", "status"],
    )

    summary = {
        "status": STATUS,
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "source_cp_sat_run": str(cp_sat_run),
        "source_assignment_file": str(source_path),
        "named_assignment_rows": len(standardized),
        "allocation_dates": dates,
        "scenarios": scenarios,
        "estate_count": len(estates),
        "duplicate_employee_assignment_failures": len(
            duplicate_keys
        ),
        "missing_field_crop_kg_rows": len(missing_crop_kg),
        "missing_plucker_capacity_kg_rows": len(
            missing_plucker_capacity_kg
        ),
        "missing_field_assigned_capacity_kg_rows": len(
            missing_field_capacity_kg
        ),
        "source_assignment_method_counts": dict(route_counts),
        "supervisor_acceptance_mode": (
            "SIMULATION_ACCEPT_ALL_NOT_REAL_APPROVAL"
        ),
        "actual_supervisor_verified": False,
        "attendance_verified": False,
        "approved_leave_verified": False,
        "fitness_verified": False,
        "movement_restrictions_verified": False,
        "allocation_gate": (
            "READY_FOR_SUPERVISOR_NAMED_ALLOCATION_REVIEW"
            if gate_status == "PASS"
            else "NAMED_ALLOCATION_REPAIR_REQUIRED"
        ),
        "operational_status": OPERATIONAL_STATUS,
        "live_deployment_started": False,
        "important_interpretation": [
            (
                "This version repairs the blank kg columns found in "
                "v13.0.0 by mapping the exact v7.1 CP-SAT fields: "
                "target_crop_kg, expected_productivity_kg and "
                "field_assigned_capacity_kg."
            ),
            (
                "This output allocates named employee IDs from the "
                "development CP-SAT baseline."
            ),
            (
                "The ACCEPT decision is a simulation marker requested "
                "by the user; it is not evidence of real supervisor "
                "approval."
            ),
            (
                "Attendance, leave, fitness and movement restrictions "
                "remain unverified."
            ),
            (
                "The output must not be sent to employees or used for "
                "live field deployment."
            ),
        ],
    }
    (
        run_folder / "run_summary.json"
    ).write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    (
        output_root / "LATEST_NAMED_PLUCKER_ALLOCATION_V1301_RUN.txt"
    ).write_text(str(run_folder), encoding="utf-8")

    print("")
    print("SIMULATION NAMED PLUCKER ALLOCATION CREATED")
    print(json.dumps(summary, indent=2))
    return 0 if gate_status == "PASS" else 1


def run_self_test() -> int:
    import shutil

    test_root = Path.cwd() / "_v13_self_test_temp"
    if test_root.exists():
        shutil.rmtree(test_root)

    project_root = test_root / "project"
    cp_sat_run = (
        project_root
        / "workforce_planner"
        / "v7"
        / "cp_sat_capacity_matching_runs"
        / "capacity_matching_20260724_000000"
        / "allocation"
    )
    cp_sat_run.mkdir(parents=True)

    rows = []
    for index in range(66):
        rows.append({
            "date": "2026-07-24",
            "scenario": (
                "EXPECTED" if index % 2 else "CONSERVATIVE"
            ),
            "estate": f"Estate{index % 33 + 1:02d}",
            "division": f"D{index % 3 + 1}",
            "field": f"F{index + 1:03d}",
            "employee_id": f"EMP-{index + 1:04d}",
            "target_crop_kg": "100",
            "expected_productivity_kg": "20",
            "field_assigned_capacity_kg": "100",
            "field_under_kg": "0",
            "field_over_kg": "0",
            "candidate_scope": "SAME_DIVISION",
            "cross_division": "NO",
            "inferred_home_division": f"D{index % 3 + 1}",
            "solver_status": "OPTIMAL",
            "allocation_method": "CP_SAT",
        })

    write_csv(
        cp_sat_run / "employee_field_assignments.csv",
        rows,
        list(rows[0].keys()),
    )

    output_root = test_root / "output"
    rc = create_allocation(project_root, output_root)
    pointer = (
        output_root / "LATEST_NAMED_PLUCKER_ALLOCATION_V1301_RUN.txt"
    )
    run_folder = Path(pointer.read_text(encoding="utf-8"))
    summary = json.loads(
        (run_folder / "run_summary.json").read_text(
            encoding="utf-8"
        )
    )
    if rc != 0:
        raise RuntimeError("v13 self-test returned a failure.")
    if summary["named_assignment_rows"] != 66:
        raise RuntimeError("v13 self-test row count mismatch.")
    if summary["duplicate_employee_assignment_failures"] != 0:
        raise RuntimeError("v13 self-test duplicate failure.")
    if summary["missing_field_crop_kg_rows"] != 0:
        raise RuntimeError("v13 self-test crop kg failure.")
    if summary["missing_plucker_capacity_kg_rows"] != 0:
        raise RuntimeError("v13 self-test plucker kg failure.")
    if summary["missing_field_assigned_capacity_kg_rows"] != 0:
        raise RuntimeError("v13 self-test field capacity failure.")
    if summary["live_deployment_started"] is not False:
        raise RuntimeError("v13 self-test live flag failure.")

    shutil.rmtree(test_root)
    print("SELF_TEST_PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root")
    parser.add_argument("--output-root")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    if not args.project_root or not args.output_root:
        raise SystemExit(
            "--project-root and --output-root are required."
        )

    return create_allocation(
        Path(args.project_root).resolve(),
        Path(args.output_root).resolve(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
