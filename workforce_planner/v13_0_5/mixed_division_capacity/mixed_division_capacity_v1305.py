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


VERSION = "13.0.5"
CREATION_STATUS = (
    "PASS_MIXED_DIVISION_CAPACITY_REVIEW_PACK_CREATED"
)
VALIDATION_STATUS = (
    "PASS_MIXED_DIVISION_CAPACITY_VALIDATION_OUTPUTS"
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
        result = float(text)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def no(value: Any) -> bool:
    return upper(value) == "NO"


def yes(value: Any) -> bool:
    return upper(value) == "YES"


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


def employee_group_key(
    row: dict[str, Any],
) -> tuple[str, str, str, str]:
    return (
        upper(row.get("allocation_date")),
        upper(row.get("scenario")),
        canonical(row.get("estate")),
        canonical(row.get("employee_id")),
    )


def field_group_key(
    row: dict[str, Any],
) -> tuple[str, str, str, str, str]:
    return (
        upper(row.get("allocation_date")),
        upper(row.get("scenario")),
        canonical(row.get("estate")),
        canonical(
            row.get("allocation_division_context")
            or row.get("division")
        ),
        canonical(row.get("field")),
    )


def exact_assignment_key(
    row: dict[str, Any],
) -> tuple[str, str, str, str, str, str]:
    return (
        *employee_group_key(row),
        canonical(
            row.get("allocation_division_context")
            or row.get("division")
        ),
        canonical(row.get("field")),
    )


def validate_source_rows(
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
        "field_assigned_capacity_kg",
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


def discover_source(
    project_root: Path,
) -> tuple[Path, Path | None, str]:
    v1304_root = (
        project_root
        / "workforce_planner"
        / "v13_0_4"
        / "code_only_division_normalization_runs"
    )
    v1304_pointer = (
        v1304_root
        / "LATEST_CODE_ONLY_DIVISION_NORMALIZATION_V1304_RUN.txt"
    )

    if v1304_pointer.exists():
        run_text = clean(
            v1304_pointer.read_text(encoding="utf-8")
        )
        if run_text:
            run_folder = Path(run_text)
            summary_path = run_folder / "run_summary.json"
            evidence_path = (
                run_folder
                / "review_input"
                / "official_field_division_code_input.csv"
            )
            if summary_path.exists():
                summary = json.loads(
                    summary_path.read_text(encoding="utf-8")
                )
                source_path = Path(
                    clean(summary.get("source_preview_path"))
                )
                if source_path.exists():
                    return (
                        source_path,
                        evidence_path if evidence_path.exists() else None,
                        str(run_folder),
                    )

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
        run_text = clean(
            v1302_pointer.read_text(encoding="utf-8")
        )
        if run_text:
            run_folder = Path(run_text)
            source_path = (
                run_folder
                / "allocation"
                / "suggested_division_normalization_preview.csv"
            )
            if source_path.exists():
                return source_path, None, str(run_folder)

    raise SystemExit(
        "No v13.0.4 or v13.0.2 allocation source was found."
    )


def build_official_code_lookup(
    evidence_path: Path | None,
) -> dict[tuple[str, str, str], dict[str, str]]:
    if evidence_path is None or not evidence_path.exists():
        return {}

    rows = read_csv(evidence_path)
    lookup: dict[
        tuple[str, str, str],
        dict[str, str],
    ] = {}

    for row in rows:
        key = (
            canonical(row.get("estate")),
            canonical(
                row.get("allocation_division_context")
            ),
            canonical(row.get("field")),
        )
        lookup[key] = {
            "official_assigned_division_code": clean(
                row.get("official_assigned_division_code")
            ),
            "official_code_evidence_status": clean(
                row.get("evidence_status")
            ),
            "official_code_source_document": clean(
                row.get("source_document_name")
            ),
            "official_code_source_reference": " | ".join(
                item
                for item in [
                    clean(row.get("source_sheet_or_page")),
                    clean(
                        row.get(
                            "source_row_or_cell_reference"
                        )
                    ),
                ]
                if item
            ),
        }

    return lookup


def prepare_review_pack(
    source_path: Path,
    output_root: Path,
    evidence_path: Path | None = None,
    source_run: str = "",
) -> int:
    source_rows = read_csv(source_path)
    validate_source_rows(source_rows, source_path)

    code_lookup = build_official_code_lookup(
        evidence_path
    )

    run_folder = (
        output_root
        / datetime.now().strftime(
            "mixed_division_capacity_%Y%m%d_%H%M%S"
        )
    )
    review_input = run_folder / "review_input"
    quality_dir = run_folder / "quality"
    allocation_dir = run_folder / "allocation"
    summary_dir = run_folder / "summary"

    for folder in (
        review_input,
        quality_dir,
        allocation_dir,
        summary_dir,
    ):
        folder.mkdir(parents=True, exist_ok=True)

    employee_groups: dict[
        tuple[str, str, str, str],
        list[dict[str, str]],
    ] = defaultdict(list)
    field_groups: dict[
        tuple[str, str, str, str, str],
        list[dict[str, str]],
    ] = defaultdict(list)

    for row in source_rows:
        employee_groups[employee_group_key(row)].append(row)
        field_groups[
            (
                upper(row.get("allocation_date")),
                upper(row.get("scenario")),
                canonical(row.get("estate")),
                canonical(row.get("division")),
                canonical(row.get("field")),
            )
        ].append(row)

    review_rows: list[dict[str, Any]] = []
    multi_group_rows: list[dict[str, Any]] = []
    inconsistent_capacity_groups: list[
        dict[str, Any]
    ] = []

    for employee_key, group_rows in employee_groups.items():
        capacities = {
            round(value, 6)
            for value in (
                as_float(row.get("plucker_capacity_kg"))
                for row in group_rows
            )
            if value is not None
        }

        daily_capacity = (
            next(iter(capacities))
            if len(capacities) == 1
            else None
        )

        if len(capacities) != 1:
            inconsistent_capacity_groups.append({
                "allocation_date": employee_key[0],
                "scenario": employee_key[1],
                "estate": clean(
                    group_rows[0].get("estate")
                ),
                "employee_id": clean(
                    group_rows[0].get("employee_id")
                ),
                "capacity_values": "|".join(
                    str(value)
                    for value in sorted(capacities)
                ),
                "failure_reason": (
                    "EMPLOYEE_DAILY_CAPACITY_INCONSISTENT"
                ),
            })

        division_contexts = {
            clean(row.get("division"))
            for row in group_rows
            if clean(row.get("division"))
        }

        official_codes = set()
        for row in group_rows:
            lookup_key = (
                canonical(row.get("estate")),
                canonical(row.get("division")),
                canonical(row.get("field")),
            )
            code = clean(
                code_lookup.get(
                    lookup_key,
                    {},
                ).get(
                    "official_assigned_division_code"
                )
            )
            if code:
                official_codes.add(code)

        mixed_division = (
            len(official_codes) > 1
            if official_codes
            else len(division_contexts) > 1
        )
        capacity_split_required = len(group_rows) > 1

        for row in group_rows:
            lookup_key = (
                canonical(row.get("estate")),
                canonical(row.get("division")),
                canonical(row.get("field")),
            )
            code_evidence = code_lookup.get(
                lookup_key,
                {},
            )

            allocated_capacity = (
                daily_capacity
                if (
                    len(group_rows) == 1
                    and daily_capacity is not None
                )
                else ""
            )

            output = {
                "allocation_date": clean(
                    row.get("allocation_date")
                ),
                "scenario": upper(row.get("scenario")),
                "estate": clean(row.get("estate")),
                "employee_key": clean(
                    row.get("employee_key")
                ),
                "employee_id": clean(
                    row.get("employee_id")
                ),
                "allocation_division_context": clean(
                    row.get("division")
                ),
                "field": clean(row.get("field")),
                "employee_home_division_code": clean(
                    row.get("inferred_home_division")
                ),
                "official_assigned_division_code": clean(
                    code_evidence.get(
                        "official_assigned_division_code"
                    )
                ),
                "official_code_evidence_status": clean(
                    code_evidence.get(
                        "official_code_evidence_status"
                    )
                ),
                "employee_daily_capacity_kg": (
                    daily_capacity
                    if daily_capacity is not None
                    else ""
                ),
                "employee_field_allocated_capacity_kg": (
                    allocated_capacity
                ),
                "employee_assignment_row_count": len(
                    group_rows
                ),
                "employee_distinct_division_count": (
                    len(official_codes)
                    if official_codes
                    else len(division_contexts)
                ),
                "capacity_split_required": (
                    "YES"
                    if capacity_split_required
                    else "NO"
                ),
                "mixed_division_assignment": (
                    "YES" if mixed_division else "NO"
                ),
                "supervisor_mixed_division_confirmed": "NO",
                "supervisor_name": "",
                "reviewed_at": "",
                "supervisor_comments": "",
                "employee_home_code_verified": "NO",
                "attendance_verified": "NO",
                "approved_leave_verified": "NO",
                "fitness_verified": "NO",
                "movement_restrictions_verified": "NO",
                "operational_use_allowed": "NO",
                "live_assignment_authorized": "NO",
                "review_status": (
                    "CAPACITY_PREFILLED_SINGLE_ASSIGNMENT"
                    if len(group_rows) == 1
                    and daily_capacity is not None
                    else "CAPACITY_SPLIT_INPUT_REQUIRED"
                ),
            }
            review_rows.append(output)

        if capacity_split_required or mixed_division:
            multi_group_rows.append({
                "allocation_date": employee_key[0],
                "scenario": employee_key[1],
                "estate": clean(
                    group_rows[0].get("estate")
                ),
                "employee_key": clean(
                    group_rows[0].get("employee_key")
                ),
                "employee_id": clean(
                    group_rows[0].get("employee_id")
                ),
                "employee_home_division_code": clean(
                    group_rows[0].get(
                        "inferred_home_division"
                    )
                ),
                "assignment_row_count": len(group_rows),
                "distinct_division_contexts": "|".join(
                    sorted(division_contexts)
                ),
                "official_assigned_division_codes": (
                    "|".join(sorted(official_codes))
                ),
                "employee_daily_capacity_kg": (
                    daily_capacity
                    if daily_capacity is not None
                    else ""
                ),
                "capacity_split_required": (
                    "YES"
                    if capacity_split_required
                    else "NO"
                ),
                "mixed_division_assignment": (
                    "YES" if mixed_division else "NO"
                ),
                "supervisor_mixed_division_confirmed": "NO",
                "supervisor_name": "",
                "reviewed_at": "",
                "operational_use_allowed": "NO",
                "live_assignment_authorized": "NO",
            })

    review_fields = list(review_rows[0].keys())

    write_csv(
        review_input
        / "employee_field_capacity_allocation_review.csv",
        review_rows,
        review_fields,
    )

    multi_fields = [
        "allocation_date",
        "scenario",
        "estate",
        "employee_key",
        "employee_id",
        "employee_home_division_code",
        "assignment_row_count",
        "distinct_division_contexts",
        "official_assigned_division_codes",
        "employee_daily_capacity_kg",
        "capacity_split_required",
        "mixed_division_assignment",
        "supervisor_mixed_division_confirmed",
        "supervisor_name",
        "reviewed_at",
        "operational_use_allowed",
        "live_assignment_authorized",
    ]
    write_csv(
        review_input
        / "multi_row_or_mixed_division_employee_review.csv",
        multi_group_rows,
        multi_fields,
    )

    exact_counts = Counter(
        (
            upper(row.get("allocation_date")),
            upper(row.get("scenario")),
            canonical(row.get("estate")),
            canonical(row.get("employee_id")),
            canonical(row.get("division")),
            canonical(row.get("field")),
        )
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

    write_csv(
        quality_dir
        / "inconsistent_employee_capacity_groups.csv",
        inconsistent_capacity_groups,
        [
            "allocation_date",
            "scenario",
            "estate",
            "employee_id",
            "capacity_values",
            "failure_reason",
        ],
    )

    field_reconciliation_preview = []
    for key, group_rows in sorted(field_groups.items()):
        employee_capacity_sum = sum(
            as_float(row.get("plucker_capacity_kg"))
            or 0.0
            for row in group_rows
        )
        field_capacity_values = {
            round(value, 6)
            for value in (
                as_float(
                    row.get(
                        "field_assigned_capacity_kg"
                    )
                )
                for row in group_rows
            )
            if value is not None
        }
        field_assigned_capacity = (
            next(iter(field_capacity_values))
            if len(field_capacity_values) == 1
            else None
        )
        difference = (
            employee_capacity_sum
            - field_assigned_capacity
            if field_assigned_capacity is not None
            else None
        )

        field_reconciliation_preview.append({
            "allocation_date": key[0],
            "scenario": key[1],
            "estate": clean(
                group_rows[0].get("estate")
            ),
            "allocation_division_context": clean(
                group_rows[0].get("division")
            ),
            "field": clean(
                group_rows[0].get("field")
            ),
            "assignment_rows": len(group_rows),
            "employee_capacity_sum_kg": round(
                employee_capacity_sum,
                6,
            ),
            "source_field_assigned_capacity_kg": (
                field_assigned_capacity
                if field_assigned_capacity is not None
                else ""
            ),
            "difference_kg": (
                round(difference, 6)
                if difference is not None
                else ""
            ),
            "status": (
                "PASS"
                if difference is not None
                and abs(difference) <= 0.01
                else "REVIEW"
            ),
        })

    write_csv(
        summary_dir
        / "source_field_capacity_reconciliation.csv",
        field_reconciliation_preview,
        list(field_reconciliation_preview[0].keys()),
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
            "value": len(employee_groups),
            "required": ">0",
            "status": "PASS",
        },
        {
            "check": "MULTI_ROW_EMPLOYEE_GROUPS",
            "value": sum(
                len(rows) > 1
                for rows in employee_groups.values()
            ),
            "required": "SUPPORTED",
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
            "check": "INCONSISTENT_DAILY_CAPACITY_GROUPS",
            "value": len(
                inconsistent_capacity_groups
            ),
            "required": 0,
            "status": (
                "PASS"
                if not inconsistent_capacity_groups
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
        / "mixed_division_capacity_creation_gate.csv",
        creation_gate,
        ["check", "value", "required", "status"],
    )

    instructions = (
        "This stage allows one employee to have several field or "
        "division allocation rows on the same day.\n\n"
        "The rule is:\n"
        "sum(employee_field_allocated_capacity_kg) must not exceed "
        "employee_daily_capacity_kg for the same date, scenario, estate "
        "and employee.\n\n"
        "Single-row employees are prefilled with their full daily "
        "capacity. If an employee has several rows, enter the capacity "
        "split for each row. Do not repeat the full daily capacity on "
        "every row.\n\n"
        "When an employee is assigned to more than one division, an "
        "authorized supervisor must complete "
        "supervisor_mixed_division_confirmed, supervisor_name and "
        "reviewed_at. This does not verify attendance, leave, fitness or "
        "movement restrictions.\n\n"
        "Keep employee_home_code_verified, attendance_verified, "
        "approved_leave_verified, fitness_verified, "
        "movement_restrictions_verified, operational_use_allowed and "
        "live_assignment_authorized as NO.\n\n"
        "TLD or any other unclear home code must remain unverified until "
        "an authorized reviewer confirms its meaning.\n\n"
        "After review, run "
        "VALIDATE_MIXED_DIVISION_CAPACITY_v13.0.5.ps1.\n"
    )
    (
        review_input
        / "MIXED_DIVISION_CAPACITY_INSTRUCTIONS.txt"
    ).write_text(instructions, encoding="utf-8")

    summary = {
        "status": CREATION_STATUS,
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "source_run": source_run,
        "source_allocation_path": str(source_path),
        "source_code_evidence_path": (
            str(evidence_path)
            if evidence_path is not None
            else ""
        ),
        "source_assignment_rows": len(source_rows),
        "employee_daily_groups": len(employee_groups),
        "single_row_employee_groups": sum(
            len(rows) == 1
            for rows in employee_groups.values()
        ),
        "multi_row_employee_groups": sum(
            len(rows) > 1
            for rows in employee_groups.values()
        ),
        "mixed_division_employee_groups": len(
            multi_group_rows
        ),
        "field_groups": len(field_groups),
        "exact_duplicate_assignment_failures": len(
            exact_duplicate_rows
        ),
        "inconsistent_daily_capacity_groups": len(
            inconsistent_capacity_groups
        ),
        "review_gate": (
            "MIXED_DIVISION_CAPACITY_REVIEW_READY"
        ),
        "operational_status": (
            "CAPACITY_SPLIT_AND_MOVEMENT_REVIEW_ONLY"
        ),
        "live_deployment_started": False,
        "important_interpretation": [
            (
                "Multiple rows for one employee are allowed when their "
                "total allocated capacity does not exceed daily "
                "capacity."
            ),
            (
                "An exact duplicate employee-division-field row remains "
                "a data failure."
            ),
            (
                "A different-division assignment requires supervisor "
                "confirmation and is not automatically approved."
            ),
            (
                "Employee home codes, including unclear codes such as "
                "TLD, remain unverified."
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
        / "LATEST_MIXED_DIVISION_CAPACITY_V1305_RUN.txt"
    ).write_text(str(run_folder), encoding="utf-8")

    print("")
    print("MIXED-DIVISION CAPACITY REVIEW PACK CREATED")
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
        / "employee_field_capacity_allocation_review.csv"
    )

    source_rows = read_csv(source_path)
    review_rows = read_csv(review_path)
    validate_source_rows(source_rows, source_path)

    failures: list[dict[str, Any]] = []

    source_exact_keys = Counter(
        (
            upper(row.get("allocation_date")),
            upper(row.get("scenario")),
            canonical(row.get("estate")),
            canonical(row.get("employee_id")),
            canonical(row.get("division")),
            canonical(row.get("field")),
        )
        for row in source_rows
    )
    review_exact_keys = Counter(
        (
            upper(row.get("allocation_date")),
            upper(row.get("scenario")),
            canonical(row.get("estate")),
            canonical(row.get("employee_id")),
            canonical(
                row.get("allocation_division_context")
            ),
            canonical(row.get("field")),
        )
        for row in review_rows
    )

    for key, count in review_exact_keys.items():
        if count > 1:
            failures.append({
                "failure_type": "EXACT_DUPLICATE_REVIEW_ROW",
                "allocation_date": key[0],
                "scenario": key[1],
                "estate": key[2],
                "employee_id": key[3],
                "division_context": key[4],
                "field": key[5],
                "details": f"row_count={count}",
            })

    missing_keys = set(source_exact_keys) - set(
        review_exact_keys
    )
    extra_keys = set(review_exact_keys) - set(
        source_exact_keys
    )

    for key in sorted(missing_keys):
        failures.append({
            "failure_type": "MISSING_REVIEW_ASSIGNMENT_ROW",
            "allocation_date": key[0],
            "scenario": key[1],
            "estate": key[2],
            "employee_id": key[3],
            "division_context": key[4],
            "field": key[5],
            "details": "",
        })

    for key in sorted(extra_keys):
        failures.append({
            "failure_type": "EXTRA_REVIEW_ASSIGNMENT_ROW",
            "allocation_date": key[0],
            "scenario": key[1],
            "estate": key[2],
            "employee_id": key[3],
            "division_context": key[4],
            "field": key[5],
            "details": "",
        })

    employee_groups: dict[
        tuple[str, str, str, str],
        list[dict[str, str]],
    ] = defaultdict(list)
    field_groups: dict[
        tuple[str, str, str, str, str],
        list[dict[str, str]],
    ] = defaultdict(list)

    for row in review_rows:
        employee_groups[employee_group_key(row)].append(row)
        field_groups[field_group_key(row)].append(row)

        allocated = as_float(
            row.get(
                "employee_field_allocated_capacity_kg"
            )
        )
        daily_capacity = as_float(
            row.get("employee_daily_capacity_kg")
        )

        if allocated is None or allocated <= 0:
            failures.append({
                "failure_type": (
                    "ALLOCATED_CAPACITY_REQUIRED"
                ),
                "allocation_date": clean(
                    row.get("allocation_date")
                ),
                "scenario": clean(row.get("scenario")),
                "estate": clean(row.get("estate")),
                "employee_id": clean(
                    row.get("employee_id")
                ),
                "division_context": clean(
                    row.get(
                        "allocation_division_context"
                    )
                ),
                "field": clean(row.get("field")),
                "details": (
                    "employee_field_allocated_capacity_kg "
                    "must be a positive number"
                ),
            })

        if daily_capacity is None or daily_capacity <= 0:
            failures.append({
                "failure_type": (
                    "DAILY_CAPACITY_REQUIRED"
                ),
                "allocation_date": clean(
                    row.get("allocation_date")
                ),
                "scenario": clean(row.get("scenario")),
                "estate": clean(row.get("estate")),
                "employee_id": clean(
                    row.get("employee_id")
                ),
                "division_context": clean(
                    row.get(
                        "allocation_division_context"
                    )
                ),
                "field": clean(row.get("field")),
                "details": (
                    "employee_daily_capacity_kg must be "
                    "a positive number"
                ),
            })

        safety_fields = [
            "employee_home_code_verified",
            "attendance_verified",
            "approved_leave_verified",
            "fitness_verified",
            "movement_restrictions_verified",
            "operational_use_allowed",
            "live_assignment_authorized",
        ]
        for field in safety_fields:
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
                    "division_context": clean(
                        row.get(
                            "allocation_division_context"
                        )
                    ),
                    "field": clean(
                        row.get("field")
                    ),
                    "details": "",
                })

    employee_summary_rows: list[dict[str, Any]] = []

    for key, group_rows in sorted(employee_groups.items()):
        capacities = {
            round(value, 6)
            for value in (
                as_float(
                    row.get(
                        "employee_daily_capacity_kg"
                    )
                )
                for row in group_rows
            )
            if value is not None
        }
        daily_capacity = (
            next(iter(capacities))
            if len(capacities) == 1
            else None
        )
        allocated_values = [
            as_float(
                row.get(
                    "employee_field_allocated_capacity_kg"
                )
            )
            for row in group_rows
        ]
        allocated_sum = sum(
            value or 0.0
            for value in allocated_values
        )

        official_codes = {
            canonical(
                row.get(
                    "official_assigned_division_code"
                )
            )
            for row in group_rows
            if canonical(
                row.get(
                    "official_assigned_division_code"
                )
            )
        }
        division_contexts = {
            canonical(
                row.get(
                    "allocation_division_context"
                )
            )
            for row in group_rows
            if canonical(
                row.get(
                    "allocation_division_context"
                )
            )
        }
        distinct_divisions = (
            len(official_codes)
            if official_codes
            else len(division_contexts)
        )
        mixed_division = distinct_divisions > 1

        if len(capacities) != 1:
            failures.append({
                "failure_type": (
                    "INCONSISTENT_EMPLOYEE_DAILY_CAPACITY"
                ),
                "allocation_date": key[0],
                "scenario": key[1],
                "estate": clean(
                    group_rows[0].get("estate")
                ),
                "employee_id": clean(
                    group_rows[0].get("employee_id")
                ),
                "division_context": "",
                "field": "",
                "details": (
                    "capacity_values="
                    + "|".join(
                        str(value)
                        for value in sorted(capacities)
                    )
                ),
            })

        if (
            daily_capacity is not None
            and allocated_sum
            > daily_capacity + tolerance_kg
        ):
            failures.append({
                "failure_type": (
                    "EMPLOYEE_DAILY_CAPACITY_EXCEEDED"
                ),
                "allocation_date": key[0],
                "scenario": key[1],
                "estate": clean(
                    group_rows[0].get("estate")
                ),
                "employee_id": clean(
                    group_rows[0].get("employee_id")
                ),
                "division_context": "",
                "field": "",
                "details": (
                    f"allocated={allocated_sum:.6f};"
                    f"daily_capacity={daily_capacity:.6f}"
                ),
            })

        if mixed_division:
            if not all(
                yes(
                    row.get(
                        "supervisor_mixed_division_confirmed"
                    )
                )
                for row in group_rows
            ):
                failures.append({
                    "failure_type": (
                        "MIXED_DIVISION_SUPERVISOR_CONFIRMATION_REQUIRED"
                    ),
                    "allocation_date": key[0],
                    "scenario": key[1],
                    "estate": clean(
                        group_rows[0].get("estate")
                    ),
                    "employee_id": clean(
                        group_rows[0].get("employee_id")
                    ),
                    "division_context": "",
                    "field": "",
                    "details": "",
                })

            if not all(
                clean(row.get("supervisor_name"))
                and clean(row.get("reviewed_at"))
                for row in group_rows
            ):
                failures.append({
                    "failure_type": (
                        "MIXED_DIVISION_REVIEWER_DETAILS_REQUIRED"
                    ),
                    "allocation_date": key[0],
                    "scenario": key[1],
                    "estate": clean(
                        group_rows[0].get("estate")
                    ),
                    "employee_id": clean(
                        group_rows[0].get("employee_id")
                    ),
                    "division_context": "",
                    "field": "",
                    "details": "",
                })

        employee_summary_rows.append({
            "allocation_date": key[0],
            "scenario": key[1],
            "estate": clean(
                group_rows[0].get("estate")
            ),
            "employee_key": clean(
                group_rows[0].get("employee_key")
            ),
            "employee_id": clean(
                group_rows[0].get("employee_id")
            ),
            "assignment_row_count": len(group_rows),
            "distinct_division_count": distinct_divisions,
            "mixed_division_assignment": (
                "YES" if mixed_division else "NO"
            ),
            "employee_daily_capacity_kg": (
                daily_capacity
                if daily_capacity is not None
                else ""
            ),
            "total_allocated_capacity_kg": round(
                allocated_sum,
                6,
            ),
            "remaining_capacity_kg": (
                round(
                    daily_capacity - allocated_sum,
                    6,
                )
                if daily_capacity is not None
                else ""
            ),
            "capacity_status": (
                "PASS"
                if daily_capacity is not None
                and allocated_sum
                <= daily_capacity + tolerance_kg
                else "FAIL"
            ),
            "employee_home_code_verified": "NO",
            "operational_use_allowed": "NO",
            "live_assignment_authorized": "NO",
        })

    source_field_targets = {
        (
            upper(row.get("allocation_date")),
            upper(row.get("scenario")),
            canonical(row.get("estate")),
            canonical(row.get("division")),
            canonical(row.get("field")),
        ): as_float(
            row.get("field_assigned_capacity_kg")
        )
        for row in source_rows
    }

    field_summary_rows: list[dict[str, Any]] = []

    for key, group_rows in sorted(field_groups.items()):
        allocated_sum = sum(
            as_float(
                row.get(
                    "employee_field_allocated_capacity_kg"
                )
            )
            or 0.0
            for row in group_rows
        )
        source_target = source_field_targets.get(key)
        difference = (
            allocated_sum - source_target
            if source_target is not None
            else None
        )

        status = (
            "PASS"
            if difference is not None
            and abs(difference) <= tolerance_kg
            else "FAIL"
        )

        if status == "FAIL":
            failures.append({
                "failure_type": (
                    "FIELD_CAPACITY_RECONCILIATION_FAILURE"
                ),
                "allocation_date": key[0],
                "scenario": key[1],
                "estate": clean(
                    group_rows[0].get("estate")
                ),
                "employee_id": "",
                "division_context": clean(
                    group_rows[0].get(
                        "allocation_division_context"
                    )
                ),
                "field": clean(
                    group_rows[0].get("field")
                ),
                "details": (
                    f"allocated={allocated_sum:.6f};"
                    f"source_target={source_target}"
                ),
            })

        field_summary_rows.append({
            "allocation_date": key[0],
            "scenario": key[1],
            "estate": clean(
                group_rows[0].get("estate")
            ),
            "allocation_division_context": clean(
                group_rows[0].get(
                    "allocation_division_context"
                )
            ),
            "field": clean(
                group_rows[0].get("field")
            ),
            "assignment_rows": len(group_rows),
            "allocated_capacity_sum_kg": round(
                allocated_sum,
                6,
            ),
            "source_field_assigned_capacity_kg": (
                source_target
                if source_target is not None
                else ""
            ),
            "difference_kg": (
                round(difference, 6)
                if difference is not None
                else ""
            ),
            "status": status,
        })

    quality_dir = run_folder / "quality"
    summary_dir = run_folder / "summary"
    allocation_dir = run_folder / "allocation"

    write_csv(
        quality_dir
        / "mixed_division_capacity_failures.csv",
        failures,
        [
            "failure_type",
            "allocation_date",
            "scenario",
            "estate",
            "employee_id",
            "division_context",
            "field",
            "details",
        ],
    )

    write_csv(
        summary_dir
        / "employee_daily_capacity_summary.csv",
        employee_summary_rows,
        list(employee_summary_rows[0].keys()),
    )

    write_csv(
        summary_dir
        / "field_capacity_reconciliation.csv",
        field_summary_rows,
        list(field_summary_rows[0].keys()),
    )

    final_pass = (
        not failures
        and len(review_rows) == len(source_rows)
    )

    output_rows: list[dict[str, Any]] = []

    if final_pass:
        for row in review_rows:
            output = dict(row)
            output["capacity_validation_status"] = "PASS"
            output["allocation_status"] = (
                "MIXED_DIVISION_CAPACITY_SAFE_"
                "SUPERVISOR_REVIEW_ONLY"
            )
            output_rows.append(output)

        output_fields = list(output_rows[0].keys())

        expected_rows = [
            row
            for row in output_rows
            if upper(row.get("scenario")) == "EXPECTED"
        ]
        conservative_rows = [
            row
            for row in output_rows
            if upper(row.get("scenario"))
            == "CONSERVATIVE"
        ]

        write_csv(
            allocation_dir
            / "expected_primary_mixed_division_capacity_safe.csv",
            expected_rows,
            output_fields,
        )
        write_csv(
            allocation_dir
            / "conservative_backup_mixed_division_capacity_safe.csv",
            conservative_rows,
            output_fields,
        )
        write_csv(
            allocation_dir
            / "all_mixed_division_capacity_safe.csv",
            output_rows,
            output_fields,
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
            "check": "EMPLOYEE_DAILY_CAPACITY_GROUPS",
            "value": len(employee_summary_rows),
            "required": ">0",
            "status": "PASS",
        },
        {
            "check": "FIELD_RECONCILIATION_FAILURES",
            "value": sum(
                row["status"] != "PASS"
                for row in field_summary_rows
            ),
            "required": 0,
            "status": (
                "PASS"
                if all(
                    row["status"] == "PASS"
                    for row in field_summary_rows
                )
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
        / "mixed_division_capacity_validation_gate.csv",
        gate_rows,
        ["check", "value", "required", "status"],
    )

    validation_summary = {
        "status": VALIDATION_STATUS,
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "source_assignment_rows": len(source_rows),
        "review_assignment_rows": len(review_rows),
        "employee_daily_groups": len(
            employee_summary_rows
        ),
        "multi_row_employee_groups": sum(
            row["assignment_row_count"] > 1
            for row in employee_summary_rows
        ),
        "mixed_division_employee_groups": sum(
            row["mixed_division_assignment"] == "YES"
            for row in employee_summary_rows
        ),
        "validation_failures": len(failures),
        "field_reconciliation_failures": sum(
            row["status"] != "PASS"
            for row in field_summary_rows
        ),
        "expected_primary_rows": sum(
            upper(row.get("scenario")) == "EXPECTED"
            for row in output_rows
        ),
        "conservative_backup_rows": sum(
            upper(row.get("scenario"))
            == "CONSERVATIVE"
            for row in output_rows
        ),
        "review_gate": (
            "READY_FOR_EMPLOYEE_HOME_CODE_SUPERVISOR_REVIEW"
            if final_pass
            else "MIXED_DIVISION_CAPACITY_INPUT_OR_CORRECTION_REQUIRED"
        ),
        "employee_home_code_verification_completed": False,
        "operational_status": (
            "CAPACITY_SAFE_SUPERVISOR_REVIEW_ONLY"
        ),
        "live_deployment_started": False,
        "important_interpretation": [
            (
                "Multiple employee allocation rows are allowed when "
                "their total does not exceed daily capacity."
            ),
            (
                "Mixed-division rows require supervisor confirmation."
            ),
            (
                "Passing this gate does not verify attendance, leave, "
                "fitness, movement restrictions or home division codes."
            ),
            (
                "No employee notification or live assignment is "
                "authorized."
            ),
        ],
    }
    (
        run_folder / "validation_summary.json"
    ).write_text(
        json.dumps(validation_summary, indent=2),
        encoding="utf-8",
    )

    print("")
    print("MIXED-DIVISION CAPACITY VALIDATION FINISHED")
    print(json.dumps(validation_summary, indent=2))
    return 0


def self_test() -> int:
    test_root = Path.cwd() / "_v1305_self_test_temp"
    if test_root.exists():
        shutil.rmtree(test_root)
    test_root.mkdir(parents=True)

    source_path = test_root / "source.csv"
    output_root = test_root / "runs"

    rows = [
        {
            "allocation_date": "2026-07-24",
            "scenario": "EXPECTED",
            "estate": "Tillyrie",
            "division": "Lower",
            "field": "F1",
            "employee_key": "Tillyrie|EMP-001",
            "employee_id": "EMP-001",
            "plucker_capacity_kg": "20",
            "field_assigned_capacity_kg": "12",
            "inferred_home_division": "TLD",
            "operational_use_allowed": "NO",
            "live_assignment_authorized": "NO",
        },
        {
            "allocation_date": "2026-07-24",
            "scenario": "EXPECTED",
            "estate": "Tillyrie",
            "division": "Upper",
            "field": "F2",
            "employee_key": "Tillyrie|EMP-001",
            "employee_id": "EMP-001",
            "plucker_capacity_kg": "20",
            "field_assigned_capacity_kg": "8",
            "inferred_home_division": "TLD",
            "operational_use_allowed": "NO",
            "live_assignment_authorized": "NO",
        },
    ]
    write_csv(
        source_path,
        rows,
        list(rows[0].keys()),
    )

    prepare_review_pack(
        source_path,
        output_root,
    )

    pointer = (
        output_root
        / "LATEST_MIXED_DIVISION_CAPACITY_V1305_RUN.txt"
    )
    run_folder = Path(
        pointer.read_text(encoding="utf-8").strip()
    )
    review_path = (
        run_folder
        / "review_input"
        / "employee_field_capacity_allocation_review.csv"
    )
    review_rows = read_csv(review_path)

    for row in review_rows:
        row["employee_field_allocated_capacity_kg"] = (
            "12"
            if row["allocation_division_context"]
            == "Lower"
            else "8"
        )
        row[
            "supervisor_mixed_division_confirmed"
        ] = "YES"
        row["supervisor_name"] = (
            "Authorized Test Reviewer"
        )
        row["reviewed_at"] = "2026-07-24 17:30"
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

    validation = json.loads(
        (run_folder / "validation_summary.json").read_text(
            encoding="utf-8"
        )
    )

    if validation["validation_failures"] != 0:
        raise RuntimeError(
            "Mixed-division capacity self-test failed."
        )
    if validation["multi_row_employee_groups"] != 1:
        raise RuntimeError(
            "Multi-row employee self-test failed."
        )
    if validation["mixed_division_employee_groups"] != 1:
        raise RuntimeError(
            "Mixed-division employee self-test failed."
        )
    if validation["expected_primary_rows"] != 2:
        raise RuntimeError(
            "Expected output self-test failed."
        )
    if validation["live_deployment_started"] is not False:
        raise RuntimeError(
            "Live-control self-test failed."
        )

    shutil.rmtree(test_root)
    print("SELF_TEST_PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root")
    parser.add_argument("--output-root")
    parser.add_argument("--source-path")
    parser.add_argument("--evidence-path")
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
        evidence_path = (
            Path(args.evidence_path).resolve()
            if args.evidence_path
            else None
        )
        source_run = args.source_run
    else:
        if not args.project_root:
            raise SystemExit(
                "--project-root is required when "
                "--source-path is omitted."
            )
        (
            source_path,
            evidence_path,
            source_run,
        ) = discover_source(
            Path(args.project_root).resolve()
        )

    return prepare_review_pack(
        source_path,
        Path(args.output_root).resolve(),
        evidence_path,
        source_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
