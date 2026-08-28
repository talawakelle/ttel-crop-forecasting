from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


VERSION = "13.0.6"
CREATION_STATUS = (
    "PASS_RARE_CROSS_DIVISION_EXCEPTION_REVIEW_PACK_CREATED"
)
VALIDATION_STATUS = (
    "PASS_RARE_CROSS_DIVISION_EXCEPTION_VALIDATION_OUTPUTS"
)


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def upper(value: Any) -> str:
    return clean(value).upper()


def canonical(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", upper(value))


def as_float(value: Any) -> float | None:
    text = clean(value)
    if not text:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def yes(value: Any) -> bool:
    return upper(value) == "YES"


def no(value: Any) -> bool:
    return upper(value) == "NO"


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


def employee_key(
    row: dict[str, Any],
) -> tuple[str, str, str, str]:
    return (
        upper(row.get("allocation_date")),
        upper(row.get("scenario")),
        canonical(row.get("estate")),
        canonical(row.get("employee_id")),
    )


def exact_assignment_key(
    row: dict[str, Any],
) -> tuple[str, str, str, str, str, str]:
    return (
        *employee_key(row),
        canonical(
            row.get("allocation_division_context")
            or row.get("division")
        ),
        canonical(row.get("field")),
    )


def validate_source(
    rows: list[dict[str, str]],
    path: Path,
) -> None:
    required = {
        "allocation_date",
        "scenario",
        "estate",
        "division",
        "field",
        "employee_key",
        "employee_id",
        "plucker_capacity_kg",
        "inferred_home_division",
        "operational_use_allowed",
        "live_assignment_authorized",
    }
    if not rows:
        raise SystemExit(f"Source allocation is empty: {path}")
    headers = {clean(item) for item in rows[0].keys()}
    missing = sorted(required - headers)
    if missing:
        raise SystemExit(
            "Source allocation is missing required columns: "
            + ", ".join(missing)
        )


def discover_source(project_root: Path) -> tuple[Path, str]:
    v1305_root = (
        project_root
        / "workforce_planner"
        / "v13_0_5"
        / "mixed_division_capacity_runs"
    )
    v1305_pointer = (
        v1305_root
        / "LATEST_MIXED_DIVISION_CAPACITY_V1305_RUN.txt"
    )
    if v1305_pointer.exists():
        run_text = clean(v1305_pointer.read_text(encoding="utf-8"))
        if run_text:
            run_folder = Path(run_text)
            summary_path = run_folder / "run_summary.json"
            if summary_path.exists():
                summary = json.loads(
                    summary_path.read_text(encoding="utf-8")
                )
                source_path = Path(
                    clean(summary.get("source_allocation_path"))
                )
                if source_path.exists():
                    return source_path, str(run_folder)

    v1302_root = (
        project_root
        / "workforce_planner"
        / "v13_0_2"
        / "division_identity_normalization_runs"
    )
    v1302_pointer = (
        v1302_root
        / "LATEST_DIVISION_IDENTITY_NORMALIZATION_V1302_RUN.txt"
    )
    if v1302_pointer.exists():
        run_text = clean(v1302_pointer.read_text(encoding="utf-8"))
        if run_text:
            run_folder = Path(run_text)
            source_path = (
                run_folder
                / "allocation"
                / "suggested_division_normalization_preview.csv"
            )
            if source_path.exists():
                return source_path, str(run_folder)

    raise SystemExit(
        "No v13.0.5 or v13.0.2 allocation source was found."
    )


def create_review_pack(
    source_path: Path,
    output_root: Path,
    source_run: str = "",
) -> int:
    source_rows = read_csv(source_path)
    validate_source(source_rows, source_path)

    run_folder = (
        output_root
        / datetime.now().strftime(
            "rare_cross_division_exception_%Y%m%d_%H%M%S"
        )
    )
    review_input = run_folder / "review_input"
    quality_dir = run_folder / "quality"
    summary_dir = run_folder / "summary"
    allocation_dir = run_folder / "allocation"

    for folder in (
        review_input,
        quality_dir,
        summary_dir,
        allocation_dir,
    ):
        folder.mkdir(parents=True, exist_ok=True)

    groups: dict[
        tuple[str, str, str, str],
        list[dict[str, str]],
    ] = defaultdict(list)

    for row in source_rows:
        groups[employee_key(row)].append(row)

    review_rows: list[dict[str, Any]] = []
    exception_group_rows: list[dict[str, Any]] = []
    exact_counts = Counter(
        exact_assignment_key(row)
        for row in source_rows
    )

    exact_duplicate_rows = [
        {
            "allocation_date": key[0],
            "scenario": key[1],
            "estate": key[2],
            "employee_id": key[3],
            "division_context": key[4],
            "field": key[5],
            "row_count": count,
        }
        for key, count in exact_counts.items()
        if count > 1
    ]

    for key, rows in groups.items():
        division_contexts = sorted(
            {
                clean(row.get("division"))
                for row in rows
                if clean(row.get("division"))
            }
        )
        capacities = {
            round(value, 6)
            for value in (
                as_float(row.get("plucker_capacity_kg"))
                for row in rows
            )
            if value is not None
        }
        daily_capacity = (
            next(iter(capacities))
            if len(capacities) == 1
            else ""
        )
        is_exception = len(division_contexts) > 1

        if is_exception:
            exception_group_rows.append({
                "allocation_date": key[0],
                "scenario": key[1],
                "estate": clean(rows[0].get("estate")),
                "employee_key": clean(rows[0].get("employee_key")),
                "employee_id": clean(rows[0].get("employee_id")),
                "employee_home_division_code": clean(
                    rows[0].get("inferred_home_division")
                ),
                "assignment_row_count": len(rows),
                "division_contexts": "|".join(division_contexts),
                "employee_daily_capacity_kg": daily_capacity,
                "cross_division_exception": "YES",
                "exception_reason": "",
                "supervisor_exception_confirmed": "NO",
                "supervisor_name": "",
                "reviewed_at": "",
                "operational_use_allowed": "NO",
                "live_assignment_authorized": "NO",
            })

        for row in rows:
            review_rows.append({
                "allocation_date": clean(row.get("allocation_date")),
                "scenario": upper(row.get("scenario")),
                "estate": clean(row.get("estate")),
                "employee_key": clean(row.get("employee_key")),
                "employee_id": clean(row.get("employee_id")),
                "allocation_division_context": clean(
                    row.get("division")
                ),
                "field": clean(row.get("field")),
                "employee_home_division_code": clean(
                    row.get("inferred_home_division")
                ),
                "employee_daily_capacity_kg": daily_capacity,
                "employee_field_allocated_capacity_kg": (
                    daily_capacity if len(rows) == 1 else ""
                ),
                "assignment_row_count": len(rows),
                "cross_division_exception": (
                    "YES" if is_exception else "NO"
                ),
                "exception_reason": "",
                "supervisor_exception_confirmed": "NO",
                "supervisor_name": "",
                "reviewed_at": "",
                "employee_home_code_verified": "NO",
                "attendance_verified": "NO",
                "approved_leave_verified": "NO",
                "fitness_verified": "NO",
                "movement_restrictions_verified": "NO",
                "operational_use_allowed": "NO",
                "live_assignment_authorized": "NO",
                "review_status": (
                    "STANDARD_SAME_DIVISION_ACTIVITY"
                    if not is_exception
                    else "RARE_CROSS_DIVISION_EXCEPTION_REVIEW"
                ),
            })

    review_fields = list(review_rows[0].keys())
    write_csv(
        review_input
        / "employee_capacity_and_cross_division_exception_review.csv",
        review_rows,
        review_fields,
    )

    exception_fields = [
        "allocation_date",
        "scenario",
        "estate",
        "employee_key",
        "employee_id",
        "employee_home_division_code",
        "assignment_row_count",
        "division_contexts",
        "employee_daily_capacity_kg",
        "cross_division_exception",
        "exception_reason",
        "supervisor_exception_confirmed",
        "supervisor_name",
        "reviewed_at",
        "operational_use_allowed",
        "live_assignment_authorized",
    ]
    write_csv(
        review_input
        / "rare_cross_division_exception_only.csv",
        exception_group_rows,
        exception_fields,
    )

    write_csv(
        quality_dir
        / "exact_duplicate_assignment_check.csv",
        exact_duplicate_rows,
        [
            "allocation_date",
            "scenario",
            "estate",
            "employee_id",
            "division_context",
            "field",
            "row_count",
        ],
    )

    estate_scenario_counts = defaultdict(
        lambda: {
            "employee_groups": 0,
            "exception_groups": 0,
        }
    )
    for key, rows in groups.items():
        estate = clean(rows[0].get("estate"))
        scenario = upper(rows[0].get("scenario"))
        group = estate_scenario_counts[(estate, scenario)]
        group["employee_groups"] += 1
        if len(
            {
                clean(row.get("division"))
                for row in rows
                if clean(row.get("division"))
            }
        ) > 1:
            group["exception_groups"] += 1

    rate_rows = []
    for (estate, scenario), counts in sorted(
        estate_scenario_counts.items(),
        key=lambda item: (
            item[0][0].lower(),
            item[0][1],
        ),
    ):
        total = counts["employee_groups"]
        exceptions = counts["exception_groups"]
        rate_rows.append({
            "estate": estate,
            "scenario": scenario,
            "employee_daily_groups": total,
            "cross_division_exception_groups": exceptions,
            "cross_division_exception_rate_pct": (
                round(exceptions * 100.0 / total, 4)
                if total
                else 0.0
            ),
            "interpretation": (
                "NO_EXCEPTION_ACTIVITY_IN_CURRENT_DATA"
                if exceptions == 0
                else "SMALL_EXCEPTION_ACTIVITY_REQUIRES_REVIEW"
            ),
            "operational_use_allowed": "NO",
            "live_assignment_authorized": "NO",
        })

    write_csv(
        summary_dir
        / "cross_division_exception_rate_summary.csv",
        rate_rows,
        list(rate_rows[0].keys()),
    )

    creation_gate = [
        {
            "check": "SOURCE_ASSIGNMENT_ROWS",
            "value": len(source_rows),
            "required": 15014,
            "status": (
                "PASS"
                if len(source_rows) == 15014
                else "REVIEW"
            ),
        },
        {
            "check": "EMPLOYEE_DAILY_GROUPS",
            "value": len(groups),
            "required": ">0",
            "status": "PASS",
        },
        {
            "check": "RARE_CROSS_DIVISION_EXCEPTION_GROUPS",
            "value": len(exception_group_rows),
            "required": "REVIEW_ONLY_IF_PRESENT",
            "status": "PASS",
        },
        {
            "check": "EXACT_DUPLICATE_ASSIGNMENTS",
            "value": len(exact_duplicate_rows),
            "required": 0,
            "status": (
                "PASS"
                if not exact_duplicate_rows
                else "FAIL"
            ),
        },
        {
            "check": "LIVE_DEPLOYMENT_STARTED",
            "value": False,
            "required": False,
            "status": "PASS",
        },
    ]
    write_csv(
        quality_dir
        / "rare_cross_division_exception_creation_gate.csv",
        creation_gate,
        ["check", "value", "required", "status"],
    )

    instructions = (
        "Cross-division work is treated as a rare exception, not as the "
        "normal allocation model.\n\n"
        "Standard activity: one employee works within one division.\n"
        "Rare exception: one employee has allocation rows in more than "
        "one division on the same date and scenario.\n\n"
        "For any exception, an authorized supervisor must enter an "
        "exception reason, confirm the exception, and enter supervisor "
        "name and review date/time.\n\n"
        "The total employee_field_allocated_capacity_kg across all rows "
        "must not exceed employee_daily_capacity_kg.\n\n"
        "Keep all employee verification, operational-use and live "
        "assignment flags as NO.\n\n"
        "TLD and other unclear home codes remain unverified.\n\n"
        "Run VALIDATE_RARE_CROSS_DIVISION_EXCEPTION_v13.0.6.ps1 after "
        "review."
    )
    (
        review_input
        / "RARE_CROSS_DIVISION_EXCEPTION_INSTRUCTIONS.txt"
    ).write_text(instructions, encoding="utf-8")

    summary = {
        "status": CREATION_STATUS,
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "source_run": source_run,
        "source_allocation_path": str(source_path),
        "source_assignment_rows": len(source_rows),
        "employee_daily_groups": len(groups),
        "standard_same_division_groups": (
            len(groups) - len(exception_group_rows)
        ),
        "rare_cross_division_exception_groups": len(
            exception_group_rows
        ),
        "current_exception_rate_pct": round(
            len(exception_group_rows) * 100.0 / len(groups),
            4,
        ) if groups else 0.0,
        "exact_duplicate_assignment_failures": len(
            exact_duplicate_rows
        ),
        "review_gate": (
            "RARE_CROSS_DIVISION_EXCEPTION_REVIEW_READY"
        ),
        "operational_status": (
            "STANDARD_ALLOCATION_WITH_RARE_EXCEPTION_REVIEW"
        ),
        "live_deployment_started": False,
        "important_interpretation": [
            (
                "Cross-division work is treated as a rare exception, "
                "not a normal mixed-division model."
            ),
            (
                "Standard same-division allocation remains the default."
            ),
            (
                "Exception rows require reason and supervisor "
                "confirmation."
            ),
            (
                "No percentage threshold is invented; the actual "
                "exception rate is reported for management review."
            ),
            (
                "No employee notification or live assignment is "
                "authorized."
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
        output_root
        / "LATEST_RARE_CROSS_DIVISION_EXCEPTION_V1306_RUN.txt"
    ).write_text(str(run_folder), encoding="utf-8")

    print("")
    print("RARE CROSS-DIVISION EXCEPTION REVIEW PACK CREATED")
    print(json.dumps(summary, indent=2))
    return 0


def validate_review(
    run_folder: Path,
    tolerance_kg: float = 0.01,
) -> int:
    summary_path = run_folder / "run_summary.json"
    if not summary_path.exists():
        raise SystemExit(
            f"Missing run_summary.json: {run_folder}"
        )

    creation = json.loads(
        summary_path.read_text(encoding="utf-8")
    )
    source_path = Path(
        creation["source_allocation_path"]
    )
    review_path = (
        run_folder
        / "review_input"
        / "employee_capacity_and_cross_division_exception_review.csv"
    )

    source_rows = read_csv(source_path)
    review_rows = read_csv(review_path)
    validate_source(source_rows, source_path)

    failures = []
    groups = defaultdict(list)

    for row in review_rows:
        groups[employee_key(row)].append(row)

        allocated = as_float(
            row.get(
                "employee_field_allocated_capacity_kg"
            )
        )
        if allocated is None or allocated <= 0:
            failures.append({
                "failure_type": "ALLOCATED_CAPACITY_REQUIRED",
                "allocation_date": clean(
                    row.get("allocation_date")
                ),
                "scenario": clean(row.get("scenario")),
                "estate": clean(row.get("estate")),
                "employee_id": clean(
                    row.get("employee_id")
                ),
                "details": "",
            })

        for field in [
            "employee_home_code_verified",
            "attendance_verified",
            "approved_leave_verified",
            "fitness_verified",
            "movement_restrictions_verified",
            "operational_use_allowed",
            "live_assignment_authorized",
        ]:
            if not no(row.get(field)):
                failures.append({
                    "failure_type": (
                        f"{field.upper()}_MUST_REMAIN_NO"
                    ),
                    "allocation_date": clean(
                        row.get("allocation_date")
                    ),
                    "scenario": clean(
                        row.get("scenario")
                    ),
                    "estate": clean(
                        row.get("estate")
                    ),
                    "employee_id": clean(
                        row.get("employee_id")
                    ),
                    "details": "",
                })

    employee_summary = []

    for key, rows in sorted(groups.items()):
        capacities = {
            round(value, 6)
            for value in (
                as_float(
                    row.get(
                        "employee_daily_capacity_kg"
                    )
                )
                for row in rows
            )
            if value is not None
        }
        daily_capacity = (
            next(iter(capacities))
            if len(capacities) == 1
            else None
        )
        allocated_sum = sum(
            as_float(
                row.get(
                    "employee_field_allocated_capacity_kg"
                )
            )
            or 0.0
            for row in rows
        )
        divisions = {
            canonical(
                row.get(
                    "allocation_division_context"
                )
            )
            for row in rows
            if canonical(
                row.get(
                    "allocation_division_context"
                )
            )
        }
        is_exception = len(divisions) > 1

        if daily_capacity is None:
            failures.append({
                "failure_type": (
                    "INCONSISTENT_OR_MISSING_DAILY_CAPACITY"
                ),
                "allocation_date": key[0],
                "scenario": key[1],
                "estate": clean(rows[0].get("estate")),
                "employee_id": clean(
                    rows[0].get("employee_id")
                ),
                "details": "",
            })
        elif allocated_sum > daily_capacity + tolerance_kg:
            failures.append({
                "failure_type": (
                    "EMPLOYEE_DAILY_CAPACITY_EXCEEDED"
                ),
                "allocation_date": key[0],
                "scenario": key[1],
                "estate": clean(rows[0].get("estate")),
                "employee_id": clean(
                    rows[0].get("employee_id")
                ),
                "details": (
                    f"allocated={allocated_sum};"
                    f"capacity={daily_capacity}"
                ),
            })

        if is_exception:
            if not all(
                clean(row.get("exception_reason"))
                for row in rows
            ):
                failures.append({
                    "failure_type": (
                        "EXCEPTION_REASON_REQUIRED"
                    ),
                    "allocation_date": key[0],
                    "scenario": key[1],
                    "estate": clean(
                        rows[0].get("estate")
                    ),
                    "employee_id": clean(
                        rows[0].get("employee_id")
                    ),
                    "details": "",
                })
            if not all(
                yes(
                    row.get(
                        "supervisor_exception_confirmed"
                    )
                )
                and clean(row.get("supervisor_name"))
                and clean(row.get("reviewed_at"))
                for row in rows
            ):
                failures.append({
                    "failure_type": (
                        "SUPERVISOR_EXCEPTION_CONFIRMATION_REQUIRED"
                    ),
                    "allocation_date": key[0],
                    "scenario": key[1],
                    "estate": clean(
                        rows[0].get("estate")
                    ),
                    "employee_id": clean(
                        rows[0].get("employee_id")
                    ),
                    "details": "",
                })

        employee_summary.append({
            "allocation_date": key[0],
            "scenario": key[1],
            "estate": clean(rows[0].get("estate")),
            "employee_id": clean(
                rows[0].get("employee_id")
            ),
            "assignment_row_count": len(rows),
            "cross_division_exception": (
                "YES" if is_exception else "NO"
            ),
            "employee_daily_capacity_kg": (
                daily_capacity
                if daily_capacity is not None
                else ""
            ),
            "allocated_capacity_sum_kg": round(
                allocated_sum,
                6,
            ),
            "capacity_status": (
                "PASS"
                if daily_capacity is not None
                and allocated_sum
                <= daily_capacity + tolerance_kg
                else "FAIL"
            ),
            "operational_use_allowed": "NO",
            "live_assignment_authorized": "NO",
        })

    exact_counts = Counter(
        exact_assignment_key(row)
        for row in review_rows
    )
    exact_duplicate_count = sum(
        count > 1
        for count in exact_counts.values()
    )
    if exact_duplicate_count:
        failures.append({
            "failure_type": (
                "EXACT_DUPLICATE_ASSIGNMENT_ROWS"
            ),
            "allocation_date": "",
            "scenario": "",
            "estate": "",
            "employee_id": "",
            "details": str(exact_duplicate_count),
        })

    quality_dir = run_folder / "quality"
    summary_dir = run_folder / "summary"
    allocation_dir = run_folder / "allocation"

    write_csv(
        quality_dir
        / "rare_cross_division_exception_failures.csv",
        failures,
        [
            "failure_type",
            "allocation_date",
            "scenario",
            "estate",
            "employee_id",
            "details",
        ],
    )
    write_csv(
        summary_dir
        / "employee_exception_capacity_summary.csv",
        employee_summary,
        list(employee_summary[0].keys()),
    )

    final_pass = (
        not failures
        and len(review_rows) == len(source_rows)
    )

    output_rows = []
    if final_pass:
        for row in review_rows:
            output = dict(row)
            output["validation_status"] = "PASS"
            output["allocation_status"] = (
                "STANDARD_ALLOCATION_OR_APPROVED_"
                "RARE_EXCEPTION_REVIEW_ONLY"
            )
            output_rows.append(output)

        fields = list(output_rows[0].keys())
        write_csv(
            allocation_dir
            / "all_capacity_safe_with_rare_exception_review.csv",
            output_rows,
            fields,
        )
        write_csv(
            allocation_dir
            / "expected_primary_capacity_safe.csv",
            [
                row
                for row in output_rows
                if upper(row.get("scenario"))
                == "EXPECTED"
            ],
            fields,
        )
        write_csv(
            allocation_dir
            / "conservative_backup_capacity_safe.csv",
            [
                row
                for row in output_rows
                if upper(row.get("scenario"))
                == "CONSERVATIVE"
            ],
            fields,
        )

    gate_rows = [
        {
            "check": "SOURCE_ASSIGNMENT_ROWS",
            "value": len(source_rows),
            "required": len(source_rows),
            "status": "PASS",
        },
        {
            "check": "REVIEW_ASSIGNMENT_ROWS",
            "value": len(review_rows),
            "required": len(source_rows),
            "status": (
                "PASS"
                if len(review_rows) == len(source_rows)
                else "FAIL"
            ),
        },
        {
            "check": "VALIDATION_FAILURES",
            "value": len(failures),
            "required": 0,
            "status": (
                "PASS" if not failures else "FAIL"
            ),
        },
        {
            "check": "EXACT_DUPLICATE_ASSIGNMENTS",
            "value": exact_duplicate_count,
            "required": 0,
            "status": (
                "PASS"
                if exact_duplicate_count == 0
                else "FAIL"
            ),
        },
        {
            "check": "EMPLOYEE_HOME_CODES_VERIFIED",
            "value": False,
            "required": True,
            "status": "NEXT_REVIEW_REQUIRED",
        },
        {
            "check": "LIVE_DEPLOYMENT_STARTED",
            "value": False,
            "required": False,
            "status": "PASS",
        },
    ]
    write_csv(
        quality_dir
        / "rare_cross_division_exception_validation_gate.csv",
        gate_rows,
        ["check", "value", "required", "status"],
    )

    exception_count = sum(
        row["cross_division_exception"] == "YES"
        for row in employee_summary
    )
    validation_summary = {
        "status": VALIDATION_STATUS,
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "source_assignment_rows": len(source_rows),
        "review_assignment_rows": len(review_rows),
        "employee_daily_groups": len(employee_summary),
        "standard_same_division_groups": (
            len(employee_summary) - exception_count
        ),
        "rare_cross_division_exception_groups": exception_count,
        "exception_rate_pct": round(
            exception_count * 100.0 / len(employee_summary),
            4,
        ) if employee_summary else 0.0,
        "validation_failures": len(failures),
        "review_gate": (
            "READY_FOR_EMPLOYEE_HOME_CODE_SUPERVISOR_REVIEW"
            if final_pass
            else "RARE_CROSS_DIVISION_EXCEPTION_INPUT_OR_CORRECTION_REQUIRED"
        ),
        "employee_home_code_verification_completed": False,
        "operational_status": (
            "STANDARD_ALLOCATION_WITH_RARE_EXCEPTION_REVIEW_ONLY"
        ),
        "live_deployment_started": False,
    }
    (
        run_folder / "validation_summary.json"
    ).write_text(
        json.dumps(validation_summary, indent=2),
        encoding="utf-8",
    )

    print("")
    print("RARE CROSS-DIVISION EXCEPTION VALIDATION FINISHED")
    print(json.dumps(validation_summary, indent=2))
    return 0


def self_test() -> int:
    test_root = Path.cwd() / "_v1306_self_test_temp"
    if test_root.exists():
        shutil.rmtree(test_root)
    test_root.mkdir(parents=True)

    source_path = test_root / "source.csv"
    output_root = test_root / "runs"

    rows = [
        {
            "allocation_date": "2026-07-24",
            "scenario": "EXPECTED",
            "estate": "EstateA",
            "division": "Lower",
            "field": "F1",
            "employee_key": "EstateA|EMP-001",
            "employee_id": "EMP-001",
            "plucker_capacity_kg": "20",
            "inferred_home_division": "LOW",
            "operational_use_allowed": "NO",
            "live_assignment_authorized": "NO",
        },
        {
            "allocation_date": "2026-07-24",
            "scenario": "EXPECTED",
            "estate": "EstateA",
            "division": "Upper",
            "field": "F2",
            "employee_key": "EstateA|EMP-001",
            "employee_id": "EMP-001",
            "plucker_capacity_kg": "20",
            "inferred_home_division": "LOW",
            "operational_use_allowed": "NO",
            "live_assignment_authorized": "NO",
        },
        {
            "allocation_date": "2026-07-24",
            "scenario": "EXPECTED",
            "estate": "EstateA",
            "division": "Lower",
            "field": "F3",
            "employee_key": "EstateA|EMP-002",
            "employee_id": "EMP-002",
            "plucker_capacity_kg": "18",
            "inferred_home_division": "LOW",
            "operational_use_allowed": "NO",
            "live_assignment_authorized": "NO",
        },
    ]
    write_csv(
        source_path,
        rows,
        list(rows[0].keys()),
    )

    create_review_pack(
        source_path,
        output_root,
    )

    pointer = (
        output_root
        / "LATEST_RARE_CROSS_DIVISION_EXCEPTION_V1306_RUN.txt"
    )
    run_folder = Path(
        pointer.read_text(encoding="utf-8").strip()
    )
    review_path = (
        run_folder
        / "review_input"
        / "employee_capacity_and_cross_division_exception_review.csv"
    )
    review_rows = read_csv(review_path)

    for row in review_rows:
        if row["employee_id"] == "EMP-001":
            row["employee_field_allocated_capacity_kg"] = (
                "12"
                if row["allocation_division_context"]
                == "Lower"
                else "8"
            )
            row["exception_reason"] = (
                "Temporary operational requirement"
            )
            row["supervisor_exception_confirmed"] = "YES"
            row["supervisor_name"] = (
                "Authorized Test Reviewer"
            )
            row["reviewed_at"] = "2026-07-24 18:00"
        row["employee_home_code_verified"] = "NO"
        row["attendance_verified"] = "NO"
        row["approved_leave_verified"] = "NO"
        row["fitness_verified"] = "NO"
        row["movement_restrictions_verified"] = "NO"
        row["operational_use_allowed"] = "NO"
        row["live_assignment_authorized"] = "NO"

    write_csv(
        review_path,
        review_rows,
        list(review_rows[0].keys()),
    )

    validate_review(run_folder)

    result = json.loads(
        (run_folder / "validation_summary.json").read_text(
            encoding="utf-8"
        )
    )
    if result["validation_failures"] != 0:
        raise RuntimeError("Self-test validation failed.")
    if result["rare_cross_division_exception_groups"] != 1:
        raise RuntimeError(
            "Exception identification self-test failed."
        )
    if result["standard_same_division_groups"] != 1:
        raise RuntimeError(
            "Standard activity self-test failed."
        )
    if result["live_deployment_started"] is not False:
        raise RuntimeError("Live-control self-test failed.")

    shutil.rmtree(test_root)
    print("SELF_TEST_PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root")
    parser.add_argument("--output-root")
    parser.add_argument("--source-path")
    parser.add_argument("--source-run", default="")
    parser.add_argument("--validate-run")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    if args.validate_run:
        return validate_review(
            Path(args.validate_run).resolve()
        )

    if not args.output_root:
        raise SystemExit("--output-root is required.")

    if args.source_path:
        source_path = Path(args.source_path).resolve()
        source_run = args.source_run
    else:
        if not args.project_root:
            raise SystemExit(
                "--project-root is required when "
                "--source-path is omitted."
            )
        source_path, source_run = discover_source(
            Path(args.project_root).resolve()
        )

    return create_review_pack(
        source_path,
        Path(args.output_root).resolve(),
        source_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
