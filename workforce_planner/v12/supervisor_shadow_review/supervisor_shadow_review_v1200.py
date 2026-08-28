from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


VERSION = "12.0.0"
STATUS_CREATED = "PASS_SUPERVISOR_SHADOW_REVIEW_PACK_CREATED"
STATUS_VALIDATED = "PASS_SUPERVISOR_SHADOW_REVIEW_VALIDATION_OUTPUTS"
OPERATIONAL_STATUS = "SUPERVISOR_SHADOW_REVIEW_ONLY"

YES_VALUES = {"YES", "Y", "TRUE", "1"}
NO_VALUES = {"NO", "N", "FALSE", "0"}
CASE_DECISIONS = {"ACCEPT", "REJECT", "DEFER"}
SIGNOFF_VALUES = {
    "APPROVED_FOR_CONTINUED_SHADOW_REVIEW",
    "REJECTED_REVIEW_REQUIRED",
}
ATTENDANCE_VALUES = {"PRESENT", "ABSENT", "UNKNOWN"}
LEAVE_VALUES = {"YES", "NO", "UNKNOWN"}
FITNESS_VALUES = {"FIT", "NOT_FIT", "RESTRICTED", "UNKNOWN"}
MOVEMENT_VALUES = {"NONE", "RESTRICTED", "UNKNOWN"}


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def upper(value: Any) -> str:
    return clean(value).upper()


def number(value: Any, default: float | None = None) -> float | None:
    try:
        result = float(clean(value).replace(",", ""))
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


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


def latest_pointer_value(pointer: Path) -> Path:
    if not pointer.exists():
        raise SystemExit(f"Missing required pointer: {pointer}")
    value = pointer.read_text(encoding="utf-8-sig").strip()
    if not value:
        raise SystemExit(f"Pointer is empty: {pointer}")
    return Path(value)


def alias_value(
    row: dict[str, Any],
    aliases: tuple[str, ...],
) -> str:
    normalized = {
        clean(key).lower().replace(" ", "_"): clean(value)
        for key, value in row.items()
    }
    for alias in aliases:
        value = normalized.get(alias)
        if value:
            return value
    return ""


def discover_employee_master(
    project_root: Path,
) -> tuple[Path | None, list[dict[str, str]]]:
    run_root = (
        project_root
        / "workforce_planner"
        / "v6"
        / "all_employee_scenario_runs"
    )
    if not run_root.exists():
        return None, []

    run_dirs = sorted(
        [path for path in run_root.iterdir() if path.is_dir()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    id_aliases = (
        "employee_id",
        "employee_no",
        "employee_number",
        "emp_id",
        "worker_id",
        "registration_no",
    )
    estate_aliases = (
        "estate",
        "estate_name",
    )

    candidates: list[tuple[int, int, Path, list[dict[str, str]]]] = []

    for run_dir in run_dirs[:5]:
        for csv_path in run_dir.rglob("*.csv"):
            try:
                rows = read_csv(csv_path)
            except Exception:
                continue
            if not rows:
                continue

            first = rows[0]
            normalized_headers = {
                clean(key).lower().replace(" ", "_")
                for key in first
            }
            if not any(alias in normalized_headers for alias in id_aliases):
                continue
            if not any(
                alias in normalized_headers for alias in estate_aliases
            ):
                continue

            seen: set[str] = set()
            unique_rows: list[dict[str, str]] = []
            for row in rows:
                employee_id = alias_value(row, id_aliases)
                estate = alias_value(row, estate_aliases)
                if not employee_id or not estate:
                    continue
                key = employee_id.lower()
                if key in seen:
                    continue
                seen.add(key)
                unique_rows.append(row)

            unique_count = len(unique_rows)
            if unique_count < 1000 or unique_count > 50000:
                continue

            name_score = 2 if "master" in csv_path.name.lower() else 0
            ratio_score = int(
                1000 * unique_count / max(len(rows), 1)
            )
            candidates.append(
                (
                    name_score,
                    ratio_score,
                    csv_path,
                    unique_rows,
                )
            )

    if not candidates:
        return None, []

    candidates.sort(
        key=lambda item: (
            item[0],
            item[1],
            len(item[3]),
        ),
        reverse=True,
    )
    _, _, source_path, rows = candidates[0]
    return source_path, rows


def create_employee_template(
    source_path: Path | None,
    source_rows: list[dict[str, str]],
    output_path: Path,
) -> int:
    id_aliases = (
        "employee_id",
        "employee_no",
        "employee_number",
        "emp_id",
        "worker_id",
        "registration_no",
    )
    name_aliases = (
        "employee_name",
        "name",
        "worker_name",
        "full_name",
    )
    estate_aliases = (
        "estate",
        "estate_name",
    )
    division_aliases = (
        "division",
        "division_name",
    )

    rows = []
    for source in source_rows:
        rows.append({
            "employee_id": alias_value(source, id_aliases),
            "employee_name": alias_value(source, name_aliases),
            "estate": alias_value(source, estate_aliases),
            "division": alias_value(source, division_aliases),
            "included_in_shadow_sample": "NO",
            "review_date": "",
            "attendance_status": "UNKNOWN",
            "approved_leave": "UNKNOWN",
            "fitness_status": "UNKNOWN",
            "movement_restriction": "UNKNOWN",
            "restriction_details": "",
            "supervisor_confirmed": "NO",
            "reviewer_name": "",
            "reviewed_at": "",
            "comments": "",
            "live_assignment_authorized": "NO",
        })

    fields = [
        "employee_id",
        "employee_name",
        "estate",
        "division",
        "included_in_shadow_sample",
        "review_date",
        "attendance_status",
        "approved_leave",
        "fitness_status",
        "movement_restriction",
        "restriction_details",
        "supervisor_confirmed",
        "reviewer_name",
        "reviewed_at",
        "comments",
        "live_assignment_authorized",
    ]
    return write_csv(output_path, rows, fields)


def create_review_pack(
    project_root: Path,
    output_root: Path,
) -> int:
    repair_pointer = (
        project_root
        / "workforce_planner"
        / "v11_0_2"
        / "complete_fallback_routing_repair_runs"
        / "LATEST_MOVEMENT_AUDIT_REPAIR_RUN.txt"
    )
    repair_run = latest_pointer_value(repair_pointer)

    summary_path = repair_run / "run_summary.json"
    route_path = (
        repair_run
        / "policy"
        / "repaired_shadow_route_register.csv"
    )
    result_path = (
        repair_run
        / "evaluation"
        / "routed_policy_repaired_results.csv"
    )

    for path in (summary_path, route_path, result_path):
        if not path.exists():
            raise SystemExit(f"Missing required v11.0.2 file: {path}")

    repair_summary = json.loads(
        summary_path.read_text(encoding="utf-8")
    )
    if repair_summary.get("status") != (
        "PASS_COMPLETE_FALLBACK_ROUTING_OUTPUTS"
    ):
        raise SystemExit("The v11.0.2 output status did not pass.")
    if repair_summary.get("repair_gate") != (
        "READY_FOR_SUPERVISOR_SHADOW_REVIEW"
    ):
        raise SystemExit(
            "The v11.0.2 repair gate does not permit "
            "supervisor shadow review."
        )
    if repair_summary.get("live_deployment_started") is not False:
        raise SystemExit("Unexpected live-deployment flag.")

    route_rows = read_csv(route_path)
    result_rows = read_csv(result_path)
    if len(route_rows) != 396 or len(result_rows) != 396:
        raise SystemExit(
            "Expected 396 route rows and 396 result rows; "
            f"found {len(route_rows)} and {len(result_rows)}."
        )

    result_by_key = {
        (
            upper(row.get("episode_id")),
            upper(row.get("shock_id")),
        ): row
        for row in result_rows
    }

    case_rows: list[dict[str, Any]] = []
    for route in route_rows:
        key = (
            upper(route.get("episode_id")),
            upper(route.get("shock_id")),
        )
        result = result_by_key.get(key)
        if result is None:
            raise SystemExit(
                f"Missing result row for route key: {key}"
            )

        case_rows.append({
            "episode_id": route.get("episode_id", ""),
            "shock_id": route.get("shock_id", ""),
            "shock_group": result.get("shock_group", ""),
            "scenario": route.get("scenario", ""),
            "estate": route.get("estate", ""),
            "routed_shadow_policy": route.get(
                "routed_shadow_policy", ""
            ),
            "routed_source_policy": route.get(
                "routed_source_policy", ""
            ),
            "routed_reason": route.get("routed_reason", ""),
            "no_replan_final_objective": result.get(
                "no_replan_final_objective", ""
            ),
            "greedy_final_objective": result.get(
                "greedy_final_objective", ""
            ),
            "hybrid_final_objective": result.get(
                "hybrid_final_objective", ""
            ),
            "routed_final_objective": result.get(
                "routed_final_objective", ""
            ),
            "greedy_final_under_kg": result.get(
                "greedy_final_under_kg", ""
            ),
            "hybrid_final_under_kg": result.get(
                "hybrid_final_under_kg", ""
            ),
            "routed_final_under_kg": result.get(
                "routed_final_under_kg", ""
            ),
            "greedy_accepted_moves": result.get(
                "greedy_accepted_moves", ""
            ),
            "hybrid_accepted_moves": result.get(
                "hybrid_accepted_moves", ""
            ),
            "routed_accepted_moves": result.get(
                "routed_accepted_moves", ""
            ),
            "review_date": "",
            "actual_crop_context_available": "NO",
            "attendance_verified": "NO",
            "approved_leave_verified": "NO",
            "fitness_restrictions_verified": "NO",
            "movement_restrictions_verified": "NO",
            "field_access_verified": "NO",
            "supervisor_shadow_decision": "",
            "override_policy": "",
            "override_reason": "",
            "reviewer_name": "",
            "reviewed_at": "",
            "comments": "",
            "live_assignment_authorized": "NO",
        })

    estates = sorted(
        {
            clean(row.get("estate"))
            for row in route_rows
            if clean(row.get("estate"))
        },
        key=str.lower,
    )
    if len(estates) != 33:
        raise SystemExit(
            f"Expected 33 estates, found {len(estates)}."
        )

    estate_rows = [
        {
            "review_date": "",
            "estate": estate,
            "weather_status": "",
            "field_access_status": "",
            "transport_available": "",
            "actual_crop_kg": "",
            "verified_available_workers": "",
            "absent_workers": "",
            "approved_leave_workers": "",
            "fitness_restricted_workers": "",
            "movement_restricted_workers": "",
            "supervisor_name": "",
            "supervisor_confirmed": "NO",
            "reviewed_at": "",
            "comments": "",
            "live_assignment_authorized": "NO",
        }
        for estate in estates
    ]

    output_root.mkdir(parents=True, exist_ok=True)
    run_folder = (
        output_root
        / datetime.now().strftime(
            "supervisor_shadow_review_%Y%m%d_%H%M%S"
        )
    )
    input_dir = run_folder / "review_input"
    quality_dir = run_folder / "quality"
    source_dir = run_folder / "source_reference"
    for folder in (input_dir, quality_dir, source_dir):
        folder.mkdir(parents=True, exist_ok=True)

    case_fields = list(case_rows[0].keys())
    write_csv(
        input_dir / "supervisor_case_review.csv",
        case_rows,
        case_fields,
    )

    estate_fields = list(estate_rows[0].keys())
    write_csv(
        input_dir / "estate_daily_context.csv",
        estate_rows,
        estate_fields,
    )

    employee_source, employee_source_rows = (
        discover_employee_master(project_root)
    )
    employee_count = create_employee_template(
        employee_source,
        employee_source_rows,
        input_dir / "employee_daily_status_verification.csv",
    )

    signoff_rows = [{
        "review_period_start": "",
        "review_period_end": "",
        "total_cases_reviewed": "",
        "accepted_cases": "",
        "rejected_cases": "",
        "deferred_cases": "",
        "employee_sample_rows_verified": "",
        "estate_manager_name": "",
        "hr_verifier_name": "",
        "operations_verifier_name": "",
        "data_model_reviewer_name": "",
        "signoff_status": "",
        "signoff_date": "",
        "remarks": "",
        "live_assignment_authorized": "NO",
    }]
    write_csv(
        input_dir / "shadow_review_signoff.csv",
        signoff_rows,
        list(signoff_rows[0].keys()),
    )

    instruction_text = f"""\
TTE SUPERVISOR SHADOW REVIEW v{VERSION}

SOURCE
------
v11.0.2 run:
{repair_run}

PURPOSE
-------
This pack supports supervisor review of simulated routing recommendations.
It does not authorize live employee assignments.

FILES TO COMPLETE
-----------------
1. supervisor_case_review.csv
   - Complete all 396 rows.
   - Mark all six verification fields YES only after checking actual records.
   - Decision must be ACCEPT, REJECT or DEFER.
   - REJECT and DEFER require an override reason.
   - Keep live_assignment_authorized as NO.

2. estate_daily_context.csv
   - Complete all 33 estates.
   - Use actual daily crop and verified workforce counts.
   - Keep live_assignment_authorized as NO.

3. employee_daily_status_verification.csv
   - Select a representative shadow sample by changing
     included_in_shadow_sample to YES.
   - At least one verified employee is required per estate.
   - Attendance, leave, fitness and movement restrictions must come from
     approved records or direct supervisor confirmation.
   - Keep live_assignment_authorized as NO.

4. shadow_review_signoff.csv
   - Complete only after the three files above are reviewed.
   - Use APPROVED_FOR_CONTINUED_SHADOW_REVIEW or
     REJECTED_REVIEW_REQUIRED.
   - Keep live_assignment_authorized as NO.

VALIDATION
----------
Run:
.\\VALIDATE_SUPERVISOR_SHADOW_REVIEW_v12.0.0.ps1

A passing validation confirms review completeness only.
It does not permit live assignment, payroll use or employee notification.
"""
    (
        run_folder / "SUPERVISOR_REVIEW_INSTRUCTIONS.txt"
    ).write_text(instruction_text, encoding="utf-8")

    source_reference = {
        "source_repair_run": str(repair_run),
        "source_summary": str(summary_path),
        "source_route_register": str(route_path),
        "source_result_file": str(result_path),
        "source_employee_master": (
            "" if employee_source is None else str(employee_source)
        ),
        "employee_template_rows": employee_count,
        "source_route_counts": repair_summary.get(
            "route_case_counts", {}
        ),
        "total_exact_fallback_rules": repair_summary.get(
            "total_exact_fallback_rules"
        ),
        "live_deployment_started": False,
    }
    (
        source_dir / "source_reference.json"
    ).write_text(
        json.dumps(source_reference, indent=2),
        encoding="utf-8",
    )

    summary = {
        "status": STATUS_CREATED,
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "source_repair_run": str(repair_run),
        "source_repair_gate": repair_summary.get("repair_gate"),
        "case_review_rows": len(case_rows),
        "estate_context_rows": len(estate_rows),
        "employee_status_template_rows": employee_count,
        "employee_source_path": (
            "" if employee_source is None else str(employee_source)
        ),
        "review_gate": "SUPERVISOR_INPUT_REQUIRED",
        "supervisor_review_pack_created": True,
        "supervisor_review_started": False,
        "supervisor_review_completed": False,
        "live_deployment_started": False,
        "operational_status": OPERATIONAL_STATUS,
        "important_interpretation": [
            (
                "The 396 cases are simulated shadow-review cases."
            ),
            (
                "The employee template does not prove current attendance, "
                "leave status, fitness or availability."
            ),
            (
                "Supervisors must verify actual records before entering YES."
            ),
            (
                "A completed review remains shadow-only."
            ),
            (
                "No payroll connection, employee notification or live "
                "assignment is authorized."
            ),
        ],
    }
    (
        run_folder / "run_summary.json"
    ).write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    quality_rows = [
        {
            "check": "SOURCE_V11_0_2_GATE",
            "value": repair_summary.get("repair_gate"),
            "required": "READY_FOR_SUPERVISOR_SHADOW_REVIEW",
            "status": "PASS",
        },
        {
            "check": "CASE_REVIEW_TEMPLATE_ROWS",
            "value": len(case_rows),
            "required": 396,
            "status": "PASS",
        },
        {
            "check": "ESTATE_CONTEXT_TEMPLATE_ROWS",
            "value": len(estate_rows),
            "required": 33,
            "status": "PASS",
        },
        {
            "check": "LIVE_DEPLOYMENT_STARTED",
            "value": False,
            "required": False,
            "status": "PASS",
        },
        {
            "check": "SUPERVISOR_INPUT_COMPLETE",
            "value": False,
            "required": True,
            "status": "INPUT_REQUIRED",
        },
    ]
    write_csv(
        quality_dir / "review_pack_creation_gate.csv",
        quality_rows,
        ["check", "value", "required", "status"],
    )

    (
        output_root / "LATEST_SUPERVISOR_SHADOW_REVIEW_RUN.txt"
    ).write_text(str(run_folder), encoding="utf-8")

    print(f"Supervisor shadow review pack: {run_folder}")
    print(f"Case review rows: {len(case_rows)}")
    print(f"Estate context rows: {len(estate_rows)}")
    print(f"Employee template rows: {employee_count}")
    print("Review gate: SUPERVISOR_INPUT_REQUIRED")
    print("No live employee assignment will run.")
    print("")
    print("SUPERVISOR SHADOW REVIEW PACK CREATED")
    print(json.dumps(summary, indent=2))
    return 0


def is_yes(value: Any) -> bool:
    return upper(value) in YES_VALUES


def is_no(value: Any) -> bool:
    return upper(value) in NO_VALUES


def validate_review_run(run_folder: Path) -> int:
    input_dir = run_folder / "review_input"
    quality_dir = run_folder / "quality"
    case_path = input_dir / "supervisor_case_review.csv"
    estate_path = input_dir / "estate_daily_context.csv"
    employee_path = input_dir / "employee_daily_status_verification.csv"
    signoff_path = input_dir / "shadow_review_signoff.csv"

    for path in (case_path, estate_path, employee_path, signoff_path):
        if not path.exists():
            raise SystemExit(f"Missing review input file: {path}")

    case_rows = read_csv(case_path)
    estate_rows = read_csv(estate_path)
    employee_rows = read_csv(employee_path)
    signoff_rows = read_csv(signoff_path)

    case_failures: list[dict[str, Any]] = []
    case_keys: set[tuple[str, str]] = set()
    decision_counts = {"ACCEPT": 0, "REJECT": 0, "DEFER": 0}

    verification_fields = (
        "actual_crop_context_available",
        "attendance_verified",
        "approved_leave_verified",
        "fitness_restrictions_verified",
        "movement_restrictions_verified",
        "field_access_verified",
    )

    for row in case_rows:
        key = (
            upper(row.get("episode_id")),
            upper(row.get("shock_id")),
        )
        reasons: list[str] = []
        if not key[0] or not key[1]:
            reasons.append("MISSING_CASE_ID")
        elif key in case_keys:
            reasons.append("DUPLICATE_CASE_ID")
        case_keys.add(key)

        for field in verification_fields:
            if not is_yes(row.get(field)):
                reasons.append(f"{field.upper()}_NOT_YES")

        decision = upper(row.get("supervisor_shadow_decision"))
        if decision not in CASE_DECISIONS:
            reasons.append("INVALID_OR_MISSING_DECISION")
        else:
            decision_counts[decision] += 1

        if decision in {"REJECT", "DEFER"} and not clean(
            row.get("override_reason")
        ):
            reasons.append("OVERRIDE_REASON_REQUIRED")

        if not clean(row.get("review_date")):
            reasons.append("MISSING_REVIEW_DATE")
        if not clean(row.get("reviewer_name")):
            reasons.append("MISSING_REVIEWER_NAME")
        if not clean(row.get("reviewed_at")):
            reasons.append("MISSING_REVIEWED_AT")
        if not is_no(row.get("live_assignment_authorized")):
            reasons.append("LIVE_ASSIGNMENT_FLAG_MUST_REMAIN_NO")

        if reasons:
            case_failures.append({
                "episode_id": row.get("episode_id", ""),
                "shock_id": row.get("shock_id", ""),
                "scenario": row.get("scenario", ""),
                "estate": row.get("estate", ""),
                "failure_reasons": "|".join(reasons),
            })

    estate_failures: list[dict[str, Any]] = []
    reviewed_estates: set[str] = set()

    for row in estate_rows:
        estate = clean(row.get("estate"))
        reasons: list[str] = []
        if not estate:
            reasons.append("MISSING_ESTATE")
        else:
            reviewed_estates.add(estate.lower())

        if not clean(row.get("review_date")):
            reasons.append("MISSING_REVIEW_DATE")
        if not clean(row.get("weather_status")):
            reasons.append("MISSING_WEATHER_STATUS")
        if not clean(row.get("field_access_status")):
            reasons.append("MISSING_FIELD_ACCESS_STATUS")
        if upper(row.get("transport_available")) not in (
            YES_VALUES | NO_VALUES
        ):
            reasons.append("INVALID_TRANSPORT_AVAILABLE")

        actual_crop = number(row.get("actual_crop_kg"))
        available_workers = number(
            row.get("verified_available_workers")
        )
        if actual_crop is None or actual_crop < 0:
            reasons.append("INVALID_ACTUAL_CROP_KG")
        if available_workers is None or available_workers < 0:
            reasons.append("INVALID_VERIFIED_AVAILABLE_WORKERS")

        for field in (
            "absent_workers",
            "approved_leave_workers",
            "fitness_restricted_workers",
            "movement_restricted_workers",
        ):
            value = number(row.get(field))
            if value is None or value < 0:
                reasons.append(f"INVALID_{field.upper()}")

        if not clean(row.get("supervisor_name")):
            reasons.append("MISSING_SUPERVISOR_NAME")
        if not is_yes(row.get("supervisor_confirmed")):
            reasons.append("SUPERVISOR_NOT_CONFIRMED")
        if not clean(row.get("reviewed_at")):
            reasons.append("MISSING_REVIEWED_AT")
        if not is_no(row.get("live_assignment_authorized")):
            reasons.append("LIVE_ASSIGNMENT_FLAG_MUST_REMAIN_NO")

        if reasons:
            estate_failures.append({
                "estate": estate,
                "failure_reasons": "|".join(reasons),
            })

    employee_failures: list[dict[str, Any]] = []
    verified_sample_estates: set[str] = set()
    selected_employee_rows = 0

    for row in employee_rows:
        if not is_yes(row.get("included_in_shadow_sample")):
            if not is_no(row.get("live_assignment_authorized")):
                employee_failures.append({
                    "employee_id": row.get("employee_id", ""),
                    "estate": row.get("estate", ""),
                    "failure_reasons": (
                        "LIVE_ASSIGNMENT_FLAG_MUST_REMAIN_NO"
                    ),
                })
            continue

        selected_employee_rows += 1
        reasons: list[str] = []
        employee_id = clean(row.get("employee_id"))
        estate = clean(row.get("estate"))

        if not employee_id:
            reasons.append("MISSING_EMPLOYEE_ID")
        if not estate:
            reasons.append("MISSING_ESTATE")

        if upper(row.get("attendance_status")) not in ATTENDANCE_VALUES:
            reasons.append("INVALID_ATTENDANCE_STATUS")
        if upper(row.get("attendance_status")) == "UNKNOWN":
            reasons.append("ATTENDANCE_NOT_VERIFIED")

        if upper(row.get("approved_leave")) not in LEAVE_VALUES:
            reasons.append("INVALID_APPROVED_LEAVE")
        if upper(row.get("approved_leave")) == "UNKNOWN":
            reasons.append("LEAVE_NOT_VERIFIED")

        if upper(row.get("fitness_status")) not in FITNESS_VALUES:
            reasons.append("INVALID_FITNESS_STATUS")
        if upper(row.get("fitness_status")) == "UNKNOWN":
            reasons.append("FITNESS_NOT_VERIFIED")

        if upper(row.get("movement_restriction")) not in MOVEMENT_VALUES:
            reasons.append("INVALID_MOVEMENT_RESTRICTION")
        if upper(row.get("movement_restriction")) == "UNKNOWN":
            reasons.append("MOVEMENT_RESTRICTION_NOT_VERIFIED")

        if (
            upper(row.get("fitness_status")) == "RESTRICTED"
            or upper(row.get("movement_restriction")) == "RESTRICTED"
        ) and not clean(row.get("restriction_details")):
            reasons.append("RESTRICTION_DETAILS_REQUIRED")

        if not is_yes(row.get("supervisor_confirmed")):
            reasons.append("SUPERVISOR_NOT_CONFIRMED")
        if not clean(row.get("review_date")):
            reasons.append("MISSING_REVIEW_DATE")
        if not clean(row.get("reviewer_name")):
            reasons.append("MISSING_REVIEWER_NAME")
        if not clean(row.get("reviewed_at")):
            reasons.append("MISSING_REVIEWED_AT")
        if not is_no(row.get("live_assignment_authorized")):
            reasons.append("LIVE_ASSIGNMENT_FLAG_MUST_REMAIN_NO")

        if not reasons and estate:
            verified_sample_estates.add(estate.lower())
        else:
            employee_failures.append({
                "employee_id": employee_id,
                "estate": estate,
                "failure_reasons": "|".join(reasons),
            })

    expected_estates = {
        clean(row.get("estate")).lower()
        for row in estate_rows
        if clean(row.get("estate"))
    }
    missing_employee_sample_estates = sorted(
        expected_estates - verified_sample_estates
    )

    signoff_failures: list[dict[str, Any]] = []
    if len(signoff_rows) != 1:
        signoff_failures.append({
            "failure_reasons": "SIGNOFF_FILE_MUST_HAVE_ONE_ROW"
        })
    else:
        signoff = signoff_rows[0]
        reasons: list[str] = []
        status = upper(signoff.get("signoff_status"))
        if status not in SIGNOFF_VALUES:
            reasons.append("INVALID_OR_MISSING_SIGNOFF_STATUS")
        for field in (
            "review_period_start",
            "review_period_end",
            "estate_manager_name",
            "hr_verifier_name",
            "operations_verifier_name",
            "data_model_reviewer_name",
            "signoff_date",
        ):
            if not clean(signoff.get(field)):
                reasons.append(f"MISSING_{field.upper()}")

        reported_total = number(signoff.get("total_cases_reviewed"))
        reported_accept = number(signoff.get("accepted_cases"))
        reported_reject = number(signoff.get("rejected_cases"))
        reported_defer = number(signoff.get("deferred_cases"))
        reported_sample = number(
            signoff.get("employee_sample_rows_verified")
        )

        if reported_total != len(case_rows):
            reasons.append("TOTAL_CASES_REVIEWED_MISMATCH")
        if reported_accept != decision_counts["ACCEPT"]:
            reasons.append("ACCEPTED_CASES_MISMATCH")
        if reported_reject != decision_counts["REJECT"]:
            reasons.append("REJECTED_CASES_MISMATCH")
        if reported_defer != decision_counts["DEFER"]:
            reasons.append("DEFERRED_CASES_MISMATCH")
        verified_selected = (
            selected_employee_rows - len(employee_failures)
        )
        if reported_sample != verified_selected:
            reasons.append("EMPLOYEE_SAMPLE_ROWS_MISMATCH")
        if not is_no(signoff.get("live_assignment_authorized")):
            reasons.append("LIVE_ASSIGNMENT_FLAG_MUST_REMAIN_NO")

        if reasons:
            signoff_failures.append({
                "failure_reasons": "|".join(reasons)
            })

    case_count_ok = (
        len(case_rows) == 396
        and len(case_keys) == 396
    )
    estate_count_ok = (
        len(estate_rows) == 33
        and len(reviewed_estates) == 33
    )
    employee_sample_ok = (
        selected_employee_rows >= 33
        and not employee_failures
        and not missing_employee_sample_estates
    )
    no_live_flags = (
        all(
            is_no(row.get("live_assignment_authorized"))
            for row in case_rows
        )
        and all(
            is_no(row.get("live_assignment_authorized"))
            for row in estate_rows
        )
        and all(
            is_no(row.get("live_assignment_authorized"))
            for row in employee_rows
        )
        and all(
            is_no(row.get("live_assignment_authorized"))
            for row in signoff_rows
        )
    )

    gate_pass = (
        case_count_ok
        and not case_failures
        and estate_count_ok
        and not estate_failures
        and employee_sample_ok
        and not signoff_failures
        and no_live_flags
    )
    review_gate = (
        "SUPERVISOR_SHADOW_REVIEW_COMPLETE"
        if gate_pass
        else "SUPERVISOR_INPUT_OR_CORRECTION_REQUIRED"
    )

    quality_dir.mkdir(parents=True, exist_ok=True)
    write_csv(
        quality_dir / "case_review_failures.csv",
        case_failures,
        [
            "episode_id",
            "shock_id",
            "scenario",
            "estate",
            "failure_reasons",
        ],
    )
    write_csv(
        quality_dir / "estate_context_failures.csv",
        estate_failures,
        ["estate", "failure_reasons"],
    )
    write_csv(
        quality_dir / "employee_sample_failures.csv",
        employee_failures,
        ["employee_id", "estate", "failure_reasons"],
    )
    write_csv(
        quality_dir / "missing_employee_sample_estates.csv",
        [
            {"estate": estate}
            for estate in missing_employee_sample_estates
        ],
        ["estate"],
    )
    write_csv(
        quality_dir / "signoff_failures.csv",
        signoff_failures,
        ["failure_reasons"],
    )

    gate_rows = [
        {
            "check": "CASE_REVIEW_ROWS",
            "value": len(case_rows),
            "required": 396,
            "status": "PASS" if case_count_ok else "FAIL",
        },
        {
            "check": "CASE_REVIEW_FAILURES",
            "value": len(case_failures),
            "required": 0,
            "status": "PASS" if not case_failures else "FAIL",
        },
        {
            "check": "ESTATE_CONTEXT_ROWS",
            "value": len(estate_rows),
            "required": 33,
            "status": "PASS" if estate_count_ok else "FAIL",
        },
        {
            "check": "ESTATE_CONTEXT_FAILURES",
            "value": len(estate_failures),
            "required": 0,
            "status": "PASS" if not estate_failures else "FAIL",
        },
        {
            "check": "EMPLOYEE_SAMPLE_ROWS_SELECTED",
            "value": selected_employee_rows,
            "required": ">=33 and >=1 per estate",
            "status": "PASS" if employee_sample_ok else "FAIL",
        },
        {
            "check": "EMPLOYEE_SAMPLE_FAILURES",
            "value": len(employee_failures),
            "required": 0,
            "status": "PASS" if not employee_failures else "FAIL",
        },
        {
            "check": "ESTATES_MISSING_EMPLOYEE_SAMPLE",
            "value": len(missing_employee_sample_estates),
            "required": 0,
            "status": (
                "PASS"
                if not missing_employee_sample_estates
                else "FAIL"
            ),
        },
        {
            "check": "SIGNOFF_FAILURES",
            "value": len(signoff_failures),
            "required": 0,
            "status": "PASS" if not signoff_failures else "FAIL",
        },
        {
            "check": "LIVE_ASSIGNMENT_FLAGS_ALL_NO",
            "value": no_live_flags,
            "required": True,
            "status": "PASS" if no_live_flags else "FAIL",
        },
    ]
    write_csv(
        quality_dir / "supervisor_shadow_review_gate.csv",
        gate_rows,
        ["check", "value", "required", "status"],
    )

    summary = {
        "status": STATUS_VALIDATED,
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "case_review_rows": len(case_rows),
        "case_review_failures": len(case_failures),
        "estate_context_rows": len(estate_rows),
        "estate_context_failures": len(estate_failures),
        "employee_template_rows": len(employee_rows),
        "employee_sample_rows_selected": selected_employee_rows,
        "employee_sample_failures": len(employee_failures),
        "estates_missing_employee_sample": len(
            missing_employee_sample_estates
        ),
        "signoff_failures": len(signoff_failures),
        "decision_counts": decision_counts,
        "review_gate": review_gate,
        "supervisor_review_started": (
            selected_employee_rows > 0
            or bool(decision_counts["ACCEPT"])
            or bool(decision_counts["REJECT"])
            or bool(decision_counts["DEFER"])
        ),
        "supervisor_review_completed": gate_pass,
        "live_deployment_started": False,
        "operational_status": OPERATIONAL_STATUS,
        "important_interpretation": [
            (
                "A passing review confirms documentation completeness "
                "and supervisor shadow review only."
            ),
            (
                "It does not approve live employee assignment."
            ),
            (
                "Actual attendance, leave, fitness and restrictions "
                "must remain supported by approved records."
            ),
        ],
    }
    (
        run_folder / "validation_summary.json"
    ).write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    print("")
    print("SUPERVISOR SHADOW REVIEW VALIDATION FINISHED")
    print(json.dumps(summary, indent=2))
    return 0


def run_self_test() -> int:
    test_root = Path.cwd() / "_v12_self_test_temp"
    if test_root.exists():
        import shutil
        shutil.rmtree(test_root)
    input_dir = test_root / "review_input"
    quality_dir = test_root / "quality"
    input_dir.mkdir(parents=True)

    case_rows = []
    for index in range(396):
        case_rows.append({
            "episode_id": f"EP_{index // 6 + 1:03d}",
            "shock_id": f"SHOCK_{index % 6:02d}",
            "scenario": "EXPECTED",
            "estate": f"Estate{index // 12 + 1:02d}",
            "actual_crop_context_available": "YES",
            "attendance_verified": "YES",
            "approved_leave_verified": "YES",
            "fitness_restrictions_verified": "YES",
            "movement_restrictions_verified": "YES",
            "field_access_verified": "YES",
            "supervisor_shadow_decision": "ACCEPT",
            "override_reason": "",
            "review_date": "2026-07-24",
            "reviewer_name": "Tester",
            "reviewed_at": "2026-07-24 12:00",
            "live_assignment_authorized": "NO",
        })
    write_csv(
        input_dir / "supervisor_case_review.csv",
        case_rows,
        list(case_rows[0].keys()),
    )

    estate_rows = []
    for index in range(33):
        estate_rows.append({
            "review_date": "2026-07-24",
            "estate": f"Estate{index + 1:02d}",
            "weather_status": "NORMAL",
            "field_access_status": "OPEN",
            "transport_available": "YES",
            "actual_crop_kg": "1000",
            "verified_available_workers": "100",
            "absent_workers": "0",
            "approved_leave_workers": "0",
            "fitness_restricted_workers": "0",
            "movement_restricted_workers": "0",
            "supervisor_name": "Tester",
            "supervisor_confirmed": "YES",
            "reviewed_at": "2026-07-24 12:00",
            "live_assignment_authorized": "NO",
        })
    write_csv(
        input_dir / "estate_daily_context.csv",
        estate_rows,
        list(estate_rows[0].keys()),
    )

    employee_rows = []
    for index in range(33):
        employee_rows.append({
            "employee_id": f"E{index + 1:04d}",
            "estate": f"Estate{index + 1:02d}",
            "included_in_shadow_sample": "YES",
            "review_date": "2026-07-24",
            "attendance_status": "PRESENT",
            "approved_leave": "NO",
            "fitness_status": "FIT",
            "movement_restriction": "NONE",
            "restriction_details": "",
            "supervisor_confirmed": "YES",
            "reviewer_name": "Tester",
            "reviewed_at": "2026-07-24 12:00",
            "live_assignment_authorized": "NO",
        })
    write_csv(
        input_dir / "employee_daily_status_verification.csv",
        employee_rows,
        list(employee_rows[0].keys()),
    )

    signoff_rows = [{
        "review_period_start": "2026-07-24",
        "review_period_end": "2026-07-24",
        "total_cases_reviewed": "396",
        "accepted_cases": "396",
        "rejected_cases": "0",
        "deferred_cases": "0",
        "employee_sample_rows_verified": "33",
        "estate_manager_name": "Tester",
        "hr_verifier_name": "Tester",
        "operations_verifier_name": "Tester",
        "data_model_reviewer_name": "Tester",
        "signoff_status": "APPROVED_FOR_CONTINUED_SHADOW_REVIEW",
        "signoff_date": "2026-07-24",
        "live_assignment_authorized": "NO",
    }]
    write_csv(
        input_dir / "shadow_review_signoff.csv",
        signoff_rows,
        list(signoff_rows[0].keys()),
    )

    rc = validate_review_run(test_root)
    summary = json.loads(
        (test_root / "validation_summary.json").read_text(
            encoding="utf-8"
        )
    )
    if rc != 0 or summary["review_gate"] != (
        "SUPERVISOR_SHADOW_REVIEW_COMPLETE"
    ):
        raise RuntimeError("v12 self-test failed.")

    import shutil
    shutil.rmtree(test_root)
    print("SELF_TEST_PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create or validate the TTE supervisor shadow review pack."
        )
    )
    parser.add_argument("--project-root")
    parser.add_argument("--output-root")
    parser.add_argument("--validate-run")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    if args.validate_run:
        return validate_review_run(
            Path(args.validate_run).resolve()
        )

    if not args.project_root or not args.output_root:
        raise SystemExit(
            "--project-root and --output-root are required."
        )

    return create_review_pack(
        Path(args.project_root).resolve(),
        Path(args.output_root).resolve(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
