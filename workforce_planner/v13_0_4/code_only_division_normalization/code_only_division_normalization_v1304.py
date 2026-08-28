from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


VERSION = "13.0.4"
CREATION_STATUS = (
    "PASS_CODE_ONLY_DIVISION_EVIDENCE_PACK_CREATED"
)
VALIDATION_STATUS = (
    "PASS_CODE_ONLY_DIVISION_NORMALIZATION_OUTPUTS"
)


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def upper(value: Any) -> str:
    return clean(value).upper()


def canonical_code(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", upper(value))


def canonical_text(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", upper(value))


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


def field_key(
    estate: Any,
    division_context: Any,
    field: Any,
) -> tuple[str, str, str]:
    return (
        canonical_text(estate),
        canonical_text(division_context),
        canonical_text(field),
    )


def employee_assignment_key(
    row: dict[str, Any],
) -> tuple[str, str, str, str]:
    return (
        upper(row.get("allocation_date")),
        upper(row.get("scenario")),
        canonical_text(row.get("estate")),
        canonical_text(row.get("employee_id")),
    )


def validate_preview(
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
        "field_crop_kg",
        "plucker_capacity_kg",
        "field_assigned_capacity_kg",
        "inferred_home_division",
        "operational_use_allowed",
        "live_assignment_authorized",
    }

    if not rows:
        raise SystemExit(f"Allocation preview is empty: {path}")

    headers = {clean(item) for item in rows[0].keys()}
    missing = sorted(required - headers)

    if missing:
        raise SystemExit(
            "Allocation preview is missing required columns: "
            + ", ".join(missing)
        )


def discover_source_preview(
    project_root: Path,
) -> tuple[Path, str]:
    evidence_root = (
        project_root
        / "workforce_planner"
        / "v13_0_3"
        / "official_division_evidence_runs"
    )
    evidence_pointer = (
        evidence_root
        / "LATEST_OFFICIAL_DIVISION_EVIDENCE_V1303_RUN.txt"
    )

    if evidence_pointer.exists():
        run_folder_text = clean(
            evidence_pointer.read_text(encoding="utf-8")
        )
        if run_folder_text:
            run_folder = Path(run_folder_text)
            summary_path = run_folder / "run_summary.json"
            if summary_path.exists():
                summary = json.loads(
                    summary_path.read_text(encoding="utf-8")
                )
                preview = Path(
                    summary.get("source_preview_path", "")
                )
                if preview.exists():
                    return preview, str(run_folder)

    normalization_root = (
        project_root
        / "workforce_planner"
        / "v13_0_2"
        / "division_identity_normalization_runs"
    )
    normalization_pointer = (
        normalization_root
        / "LATEST_DIVISION_IDENTITY_NORMALIZATION_V1302_RUN.txt"
    )

    if normalization_pointer.exists():
        run_folder_text = clean(
            normalization_pointer.read_text(encoding="utf-8")
        )
        if run_folder_text:
            run_folder = Path(run_folder_text)
            preview = (
                run_folder
                / "allocation"
                / "suggested_division_normalization_preview.csv"
            )
            if preview.exists():
                return preview, str(run_folder)

    raise SystemExit(
        "No v13.0.3 or v13.0.2 allocation preview was found."
    )


def prepare_code_only_pack(
    preview_path: Path,
    output_root: Path,
    source_run: str = "",
) -> int:
    preview_rows = read_csv(preview_path)
    validate_preview(preview_rows, preview_path)

    run_folder = (
        output_root
        / datetime.now().strftime(
            "code_only_division_normalization_%Y%m%d_%H%M%S"
        )
    )
    review_input = run_folder / "review_input"
    allocation_dir = run_folder / "allocation"
    quality_dir = run_folder / "quality"
    summary_dir = run_folder / "summary"

    for folder in (
        review_input,
        allocation_dir,
        quality_dir,
        summary_dir,
    ):
        folder.mkdir(parents=True, exist_ok=True)

    grouped: dict[
        tuple[str, str, str],
        dict[str, Any],
    ] = {}

    for row in preview_rows:
        estate = clean(row.get("estate"))
        division = clean(row.get("division"))
        field = clean(row.get("field"))
        key = field_key(estate, division, field)

        if key not in grouped:
            grouped[key] = {
                "estate": estate,
                "allocation_division_context": division,
                "field": field,
                "assignment_rows": 0,
                "scenarios": set(),
                "allocation_dates": set(),
                "employee_count": set(),
            }

        grouped[key]["assignment_rows"] += 1
        grouped[key]["scenarios"].add(
            upper(row.get("scenario"))
        )
        grouped[key]["allocation_dates"].add(
            clean(row.get("allocation_date"))
        )
        grouped[key]["employee_count"].add(
            clean(row.get("employee_key"))
        )

    evidence_rows: list[dict[str, Any]] = []

    for key in sorted(
        grouped,
        key=lambda item: (
            grouped[item]["estate"].lower(),
            grouped[item]["allocation_division_context"].lower(),
            grouped[item]["field"].lower(),
        ),
    ):
        group = grouped[key]
        evidence_rows.append({
            "estate": group["estate"],
            "allocation_division_context": (
                group["allocation_division_context"]
            ),
            "field": group["field"],
            "assignment_rows": group["assignment_rows"],
            "unique_employee_rows": len(
                group["employee_count"]
            ),
            "scenarios": "|".join(
                sorted(group["scenarios"])
            ),
            "allocation_dates": "|".join(
                sorted(group["allocation_dates"])
            ),
            "official_assigned_division_code": "",
            "source_document_name": "",
            "source_document_date": "",
            "source_sheet_or_page": "",
            "source_row_or_cell_reference": "",
            "source_document_owner": "",
            "verified_by": "",
            "verified_at": "",
            "evidence_status": "PENDING",
            "comments": "",
            "employee_home_code_source": (
                "INFERRED_HISTORICAL_CONTEXT_ONLY"
            ),
            "employee_home_code_verified": "NO",
            "operational_use_allowed": "NO",
            "live_assignment_authorized": "NO",
        })

    evidence_fields = list(evidence_rows[0].keys())

    evidence_path = (
        review_input
        / "official_field_division_code_input.csv"
    )
    write_csv(
        evidence_path,
        evidence_rows,
        evidence_fields,
    )

    home_code_context: dict[
        tuple[str, str],
        dict[str, Any],
    ] = {}

    for row in preview_rows:
        key = (
            canonical_text(row.get("estate")),
            canonical_code(
                row.get("inferred_home_division")
            ),
        )

        if key not in home_code_context:
            home_code_context[key] = {
                "estate": clean(row.get("estate")),
                "employee_home_division_code": clean(
                    row.get("inferred_home_division")
                ),
                "assignment_rows": 0,
                "unique_employees": set(),
                "employee_home_code_verified": "NO",
                "operational_use_allowed": "NO",
                "live_assignment_authorized": "NO",
            }

        home_code_context[key]["assignment_rows"] += 1
        home_code_context[key]["unique_employees"].add(
            clean(row.get("employee_key"))
        )

    home_context_rows = []
    for key in sorted(
        home_code_context,
        key=lambda item: (
            home_code_context[item]["estate"].lower(),
            home_code_context[item][
                "employee_home_division_code"
            ].lower(),
        ),
    ):
        item = home_code_context[key]
        home_context_rows.append({
            "estate": item["estate"],
            "employee_home_division_code": (
                item["employee_home_division_code"]
            ),
            "assignment_rows": item["assignment_rows"],
            "unique_employees": len(
                item["unique_employees"]
            ),
            "employee_home_code_verified": "NO",
            "verification_status": (
                "SUPERVISOR_VERIFICATION_REQUIRED_LATER"
            ),
            "operational_use_allowed": "NO",
            "live_assignment_authorized": "NO",
        })

    write_csv(
        review_input
        / "employee_home_division_code_context.csv",
        home_context_rows,
        list(home_context_rows[0].keys()),
    )

    duplicate_estate_field_counts = Counter(
        (
            canonical_text(row["estate"]),
            canonical_text(row["field"]),
        )
        for row in evidence_rows
    )
    duplicate_estate_field_rows = [
        {
            "estate": row["estate"],
            "allocation_division_context": (
                row["allocation_division_context"]
            ),
            "field": row["field"],
            "same_estate_field_occurrences": (
                duplicate_estate_field_counts[
                    (
                        canonical_text(row["estate"]),
                        canonical_text(row["field"]),
                    )
                ]
            ),
            "interpretation": (
                "DIVISION_CONTEXT_REQUIRED"
                if duplicate_estate_field_counts[
                    (
                        canonical_text(row["estate"]),
                        canonical_text(row["field"]),
                    )
                ] > 1
                else "ESTATE_FIELD_UNIQUE"
            ),
        }
        for row in evidence_rows
        if duplicate_estate_field_counts[
            (
                canonical_text(row["estate"]),
                canonical_text(row["field"]),
            )
        ] > 1
    ]

    write_csv(
        quality_dir
        / "duplicate_estate_field_context_check.csv",
        duplicate_estate_field_rows,
        [
            "estate",
            "allocation_division_context",
            "field",
            "same_estate_field_occurrences",
            "interpretation",
        ],
    )

    estate_summary_groups: dict[
        str,
        dict[str, Any],
    ] = defaultdict(
        lambda: {
            "field_context_rows": 0,
            "assignment_rows": 0,
            "home_codes": set(),
        }
    )

    for row in evidence_rows:
        estate_summary_groups[row["estate"]][
            "field_context_rows"
        ] += 1
        estate_summary_groups[row["estate"]][
            "assignment_rows"
        ] += int(row["assignment_rows"])

    for row in home_context_rows:
        estate_summary_groups[row["estate"]][
            "home_codes"
        ].add(row["employee_home_division_code"])

    estate_summary_rows = []
    for estate in sorted(
        estate_summary_groups,
        key=str.lower,
    ):
        group = estate_summary_groups[estate]
        estate_summary_rows.append({
            "estate": estate,
            "field_context_rows": group[
                "field_context_rows"
            ],
            "allocation_assignment_rows": group[
                "assignment_rows"
            ],
            "employee_home_code_count": len(
                group["home_codes"]
            ),
            "official_field_codes_verified": 0,
            "status": "OFFICIAL_CODE_INPUT_REQUIRED",
            "operational_use_allowed": "NO",
            "live_assignment_authorized": "NO",
        })

    write_csv(
        summary_dir
        / "estate_code_only_evidence_summary.csv",
        estate_summary_rows,
        list(estate_summary_rows[0].keys()),
    )

    creation_gate = [
        {
            "check": "SOURCE_ALLOCATION_ROWS",
            "value": len(preview_rows),
            "required": 15014,
            "status": (
                "PASS"
                if len(preview_rows) == 15014
                else "FAIL"
            ),
        },
        {
            "check": "FIELD_DIVISION_CONTEXT_ROWS",
            "value": len(evidence_rows),
            "required": 447,
            "status": (
                "PASS"
                if len(evidence_rows) == 447
                else "REVIEW"
            ),
        },
        {
            "check": "EMPLOYEE_HOME_CODE_CONTEXT_KEYS",
            "value": len(home_context_rows),
            "required": 107,
            "status": (
                "PASS"
                if len(home_context_rows) == 107
                else "REVIEW"
            ),
        },
        {
            "check": "OFFICIAL_FIELD_CODE_INPUT_COMPLETE",
            "value": False,
            "required": True,
            "status": "INPUT_REQUIRED",
        },
        {
            "check": "EMPLOYEE_HOME_CODES_VERIFIED",
            "value": False,
            "required": True,
            "status": "LATER_REVIEW_REQUIRED",
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
        / "code_only_evidence_pack_gate.csv",
        creation_gate,
        ["check", "value", "required", "status"],
    )

    instructions = (
        "This stage uses division codes only. A long division name is "
        "not required in the official source document.\n\n"
        "Complete official_field_division_code_input.csv.\n"
        "For every estate + allocation_division_context + field row:\n"
        "1. Enter official_assigned_division_code from the approved "
        "source document.\n"
        "2. Enter the source-document name, date, sheet/page, row/cell "
        "reference, owner, verifier and verification date/time.\n"
        "3. Set evidence_status to VERIFIED only when the source "
        "document supports the code.\n"
        "4. Keep employee_home_code_verified, operational_use_allowed "
        "and live_assignment_authorized as NO.\n\n"
        "allocation_division_context is retained only to distinguish "
        "allocation rows. It is not treated as official evidence.\n\n"
        "The program will compare:\n"
        "official_assigned_division_code versus "
        "inferred_home_division.\n"
        "The inferred employee home code remains historical context "
        "and requires later supervisor verification.\n\n"
        "After official field codes are completed, run "
        "VALIDATE_CODE_ONLY_DIVISION_NORMALIZATION_v13.0.4.ps1.\n"
    )
    (
        review_input / "CODE_ONLY_EVIDENCE_INSTRUCTIONS.txt"
    ).write_text(instructions, encoding="utf-8")

    summary = {
        "status": CREATION_STATUS,
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "source_run": source_run,
        "source_preview_path": str(preview_path),
        "source_allocation_rows": len(preview_rows),
        "field_division_context_rows": len(evidence_rows),
        "employee_home_code_context_keys": len(
            home_context_rows
        ),
        "estate_count": len(estate_summary_rows),
        "duplicate_estate_field_context_rows": len(
            duplicate_estate_field_rows
        ),
        "review_gate": (
            "OFFICIAL_FIELD_DIVISION_CODE_INPUT_REQUIRED"
        ),
        "official_field_code_input_started": False,
        "official_field_code_input_completed": False,
        "employee_home_code_verification_completed": False,
        "operational_status": (
            "CODE_ONLY_DIVISION_EVIDENCE_COLLECTION"
        ),
        "live_deployment_started": False,
        "important_interpretation": [
            (
                "Official division long names are not required in this "
                "stage."
            ),
            (
                "The official assigned division code is entered at "
                "estate + division-context + field level."
            ),
            (
                "Allocation division text is context only and is not "
                "official evidence."
            ),
            (
                "Employee home division codes remain inferred "
                "historical context until supervisor verification."
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
        / "LATEST_CODE_ONLY_DIVISION_NORMALIZATION_V1304_RUN.txt"
    ).write_text(str(run_folder), encoding="utf-8")

    print("")
    print("CODE-ONLY DIVISION EVIDENCE PACK CREATED")
    print(json.dumps(summary, indent=2))
    return 0


def validate_code_only_run(run_folder: Path) -> int:
    summary_path = run_folder / "run_summary.json"
    if not summary_path.exists():
        raise SystemExit(
            f"Missing run_summary.json: {run_folder}"
        )

    creation = json.loads(
        summary_path.read_text(encoding="utf-8")
    )
    preview_path = Path(creation["source_preview_path"])
    evidence_path = (
        run_folder
        / "review_input"
        / "official_field_division_code_input.csv"
    )

    if not preview_path.exists():
        raise SystemExit(
            f"Source preview is missing: {preview_path}"
        )
    if not evidence_path.exists():
        raise SystemExit(
            f"Code evidence input is missing: {evidence_path}"
        )

    preview_rows = read_csv(preview_path)
    evidence_rows = read_csv(evidence_path)
    validate_preview(preview_rows, preview_path)

    source_keys = {
        field_key(
            row.get("estate"),
            row.get("division"),
            row.get("field"),
        )
        for row in preview_rows
    }

    evidence_counts = Counter(
        field_key(
            row.get("estate"),
            row.get("allocation_division_context"),
            row.get("field"),
        )
        for row in evidence_rows
    )
    evidence_keys = set(evidence_counts)

    duplicate_keys = {
        key
        for key, count in evidence_counts.items()
        if count > 1
    }
    missing_keys = source_keys - evidence_keys
    extra_keys = evidence_keys - source_keys

    failures: list[dict[str, Any]] = []
    code_lookup: dict[
        tuple[str, str, str],
        dict[str, str],
    ] = {}

    for row in evidence_rows:
        key = field_key(
            row.get("estate"),
            row.get("allocation_division_context"),
            row.get("field"),
        )
        reasons: list[str] = []
        code = clean(
            row.get("official_assigned_division_code")
        )

        if key in duplicate_keys:
            reasons.append("DUPLICATE_FIELD_CONTEXT_KEY")

        if key not in source_keys:
            reasons.append("UNKNOWN_FIELD_CONTEXT_KEY")

        if not canonical_code(code):
            reasons.append(
                "OFFICIAL_ASSIGNED_DIVISION_CODE_REQUIRED"
            )

        required_fields = [
            "source_document_name",
            "source_document_date",
            "source_sheet_or_page",
            "source_row_or_cell_reference",
            "source_document_owner",
            "verified_by",
            "verified_at",
        ]

        for field in required_fields:
            if not clean(row.get(field)):
                reasons.append(
                    f"{field.upper()}_REQUIRED"
                )

        if upper(row.get("evidence_status")) != "VERIFIED":
            reasons.append(
                "EVIDENCE_STATUS_MUST_BE_VERIFIED"
            )

        if not no(row.get("employee_home_code_verified")):
            reasons.append(
                "EMPLOYEE_HOME_CODE_VERIFIED_MUST_REMAIN_NO"
            )

        if not no(row.get("operational_use_allowed")):
            reasons.append(
                "OPERATIONAL_USE_ALLOWED_MUST_REMAIN_NO"
            )

        if not no(row.get("live_assignment_authorized")):
            reasons.append(
                "LIVE_ASSIGNMENT_AUTHORIZED_MUST_REMAIN_NO"
            )

        if reasons:
            failures.append({
                "estate": clean(row.get("estate")),
                "allocation_division_context": clean(
                    row.get(
                        "allocation_division_context"
                    )
                ),
                "field": clean(row.get("field")),
                "official_assigned_division_code": code,
                "failure_reasons": "|".join(reasons),
            })
        else:
            code_lookup[key] = {
                "official_assigned_division_code": code,
                "source_document_name": clean(
                    row.get("source_document_name")
                ),
                "source_document_date": clean(
                    row.get("source_document_date")
                ),
                "source_sheet_or_page": clean(
                    row.get("source_sheet_or_page")
                ),
                "source_row_or_cell_reference": clean(
                    row.get(
                        "source_row_or_cell_reference"
                    )
                ),
                "source_document_owner": clean(
                    row.get("source_document_owner")
                ),
                "verified_by": clean(
                    row.get("verified_by")
                ),
                "verified_at": clean(
                    row.get("verified_at")
                ),
            }

    for key in sorted(missing_keys):
        failures.append({
            "estate": key[0],
            "allocation_division_context": key[1],
            "field": key[2],
            "official_assigned_division_code": "",
            "failure_reasons": "MISSING_FIELD_CONTEXT_KEY",
        })

    for key in sorted(extra_keys):
        failures.append({
            "estate": key[0],
            "allocation_division_context": key[1],
            "field": key[2],
            "official_assigned_division_code": "",
            "failure_reasons": "EXTRA_FIELD_CONTEXT_KEY",
        })

    quality_dir = run_folder / "quality"
    allocation_dir = run_folder / "allocation"
    summary_dir = run_folder / "summary"

    for folder in (
        quality_dir,
        allocation_dir,
        summary_dir,
    ):
        folder.mkdir(exist_ok=True)

    write_csv(
        quality_dir
        / "code_only_division_evidence_failures.csv",
        failures,
        [
            "estate",
            "allocation_division_context",
            "field",
            "official_assigned_division_code",
            "failure_reasons",
        ],
    )

    normalized_rows: list[dict[str, Any]] = []
    duplicate_assignment_failures: list[
        dict[str, Any]
    ] = []

    official_field_codes_complete = (
        not failures
        and not duplicate_keys
        and not missing_keys
        and not extra_keys
        and len(code_lookup) == len(source_keys)
    )

    if official_field_codes_complete:
        for source in preview_rows:
            key = field_key(
                source.get("estate"),
                source.get("division"),
                source.get("field"),
            )
            evidence = code_lookup[key]
            assigned_code = evidence[
                "official_assigned_division_code"
            ]
            home_code = clean(
                source.get("inferred_home_division")
            )
            comparison = (
                "NO"
                if canonical_code(assigned_code)
                == canonical_code(home_code)
                else "YES"
            )

            row = dict(source)
            row.update({
                "allocation_division_context": clean(
                    source.get("division")
                ),
                "official_assigned_division_code": (
                    assigned_code
                ),
                "employee_home_division_code": home_code,
                "normalized_cross_division_code_comparison": (
                    comparison
                ),
                "official_field_division_code_verified": "YES",
                "official_code_source_document": evidence[
                    "source_document_name"
                ],
                "official_code_source_reference": (
                    evidence[
                        "source_sheet_or_page"
                    ]
                    + " | "
                    + evidence[
                        "source_row_or_cell_reference"
                    ]
                ),
                "employee_home_division_code_verified": "NO",
                "actual_supervisor_verified": "NO",
                "attendance_verified": "NO",
                "approved_leave_verified": "NO",
                "fitness_verified": "NO",
                "movement_restrictions_verified": "NO",
                "operational_use_allowed": "NO",
                "live_assignment_authorized": "NO",
                "allocation_status": (
                    "CODE_ONLY_DIVISION_COMPARISON_"
                    "FOR_SUPERVISOR_REVIEW"
                ),
            })
            normalized_rows.append(row)

        assignment_counts = Counter(
            employee_assignment_key(row)
            for row in normalized_rows
        )

        for key, count in assignment_counts.items():
            if count > 1:
                duplicate_assignment_failures.append({
                    "allocation_date": key[0],
                    "scenario": key[1],
                    "estate": key[2],
                    "employee_id": key[3],
                    "assignment_count": count,
                })

        fields = list(normalized_rows[0].keys())

        expected_rows = [
            row
            for row in normalized_rows
            if upper(row.get("scenario")) == "EXPECTED"
        ]
        conservative_rows = [
            row
            for row in normalized_rows
            if upper(row.get("scenario")) == "CONSERVATIVE"
        ]

        write_csv(
            allocation_dir
            / "expected_primary_code_only_division_comparison.csv",
            expected_rows,
            fields,
        )
        write_csv(
            allocation_dir
            / "conservative_backup_code_only_division_comparison.csv",
            conservative_rows,
            fields,
        )
        write_csv(
            allocation_dir
            / "all_code_only_division_comparisons.csv",
            normalized_rows,
            fields,
        )

        movement_groups: dict[
            tuple[str, str],
            Counter[str],
        ] = defaultdict(Counter)

        for row in normalized_rows:
            group = (
                clean(row.get("estate")),
                upper(row.get("scenario")),
            )
            movement_groups[group][
                upper(
                    row.get(
                        "normalized_cross_division_code_comparison"
                    )
                )
            ] += 1

        movement_summary = []

        for group in sorted(
            movement_groups,
            key=lambda item: (
                item[0].lower(),
                item[1],
            ),
        ):
            counts = movement_groups[group]
            total = counts["YES"] + counts["NO"]
            movement_summary.append({
                "estate": group[0],
                "scenario": group[1],
                "assignment_rows": total,
                "same_code_rows": counts["NO"],
                "different_code_rows": counts["YES"],
                "different_code_rate_pct": (
                    round(
                        counts["YES"] * 100.0 / total,
                        2,
                    )
                    if total
                    else 0.0
                ),
                "employee_home_codes_verified": "NO",
                "operational_use_allowed": "NO",
                "live_assignment_authorized": "NO",
            })

        write_csv(
            summary_dir
            / "estate_scenario_code_comparison_summary.csv",
            movement_summary,
            list(movement_summary[0].keys()),
        )

    write_csv(
        quality_dir
        / "duplicate_employee_assignment_check.csv",
        duplicate_assignment_failures,
        [
            "allocation_date",
            "scenario",
            "estate",
            "employee_id",
            "assignment_count",
        ],
    )

    all_safety_flags_no = all(
        no(row.get("employee_home_code_verified"))
        and no(row.get("operational_use_allowed"))
        and no(row.get("live_assignment_authorized"))
        for row in evidence_rows
    ) and all(
        no(row.get("employee_home_division_code_verified"))
        and no(row.get("operational_use_allowed"))
        and no(row.get("live_assignment_authorized"))
        for row in normalized_rows
    )

    final_pass = (
        official_field_codes_complete
        and len(normalized_rows) == len(preview_rows)
        and not duplicate_assignment_failures
        and all_safety_flags_no
    )

    validation_gate = [
        {
            "check": "SOURCE_FIELD_CONTEXT_KEYS",
            "value": len(source_keys),
            "required": len(source_keys),
            "status": "PASS",
        },
        {
            "check": "CODE_EVIDENCE_ROWS",
            "value": len(evidence_rows),
            "required": len(source_keys),
            "status": (
                "PASS"
                if len(evidence_rows) == len(source_keys)
                else "FAIL"
            ),
        },
        {
            "check": "DUPLICATE_FIELD_CONTEXT_KEYS",
            "value": len(duplicate_keys),
            "required": 0,
            "status": (
                "PASS" if not duplicate_keys else "FAIL"
            ),
        },
        {
            "check": "MISSING_FIELD_CONTEXT_KEYS",
            "value": len(missing_keys),
            "required": 0,
            "status": (
                "PASS" if not missing_keys else "FAIL"
            ),
        },
        {
            "check": "CODE_EVIDENCE_FAILURES",
            "value": len(failures),
            "required": 0,
            "status": (
                "PASS" if not failures else "FAIL"
            ),
        },
        {
            "check": "NORMALIZED_ALLOCATION_ROWS",
            "value": len(normalized_rows),
            "required": len(preview_rows),
            "status": (
                "PASS"
                if len(normalized_rows) == len(preview_rows)
                else "FAIL"
            ),
        },
        {
            "check": "DUPLICATE_EMPLOYEE_ASSIGNMENTS",
            "value": len(duplicate_assignment_failures),
            "required": 0,
            "status": (
                "PASS"
                if not duplicate_assignment_failures
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
            "check": "LIVE_AND_OPERATIONAL_FLAGS_ALL_NO",
            "value": all_safety_flags_no,
            "required": True,
            "status": (
                "PASS" if all_safety_flags_no else "FAIL"
            ),
        },
    ]
    write_csv(
        quality_dir
        / "code_only_division_normalization_gate.csv",
        validation_gate,
        ["check", "value", "required", "status"],
    )

    comparison_counts = Counter(
        upper(
            row.get(
                "normalized_cross_division_code_comparison"
            )
        )
        for row in normalized_rows
    )

    validation_summary = {
        "status": VALIDATION_STATUS,
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "source_field_context_keys": len(source_keys),
        "official_field_code_rows": len(evidence_rows),
        "verified_field_context_keys": len(code_lookup),
        "code_evidence_failures": len(failures),
        "normalized_allocation_rows": len(normalized_rows),
        "expected_primary_rows": sum(
            upper(row.get("scenario")) == "EXPECTED"
            for row in normalized_rows
        ),
        "conservative_backup_rows": sum(
            upper(row.get("scenario")) == "CONSERVATIVE"
            for row in normalized_rows
        ),
        "code_comparison_counts": dict(
            comparison_counts
        ),
        "duplicate_employee_assignment_failures": len(
            duplicate_assignment_failures
        ),
        "review_gate": (
            "READY_FOR_EMPLOYEE_HOME_CODE_SUPERVISOR_REVIEW"
            if final_pass
            else "OFFICIAL_FIELD_CODE_INPUT_OR_CORRECTION_REQUIRED"
        ),
        "official_field_code_input_started": any(
            canonical_code(
                row.get("official_assigned_division_code")
            )
            for row in evidence_rows
        ),
        "official_field_code_input_completed": final_pass,
        "employee_home_code_verification_completed": False,
        "operational_status": (
            "CODE_ONLY_DIVISION_COMPARISON_REVIEW_ONLY"
        ),
        "live_deployment_started": False,
        "important_interpretation": [
            (
                "A passing gate confirms official field division-code "
                "evidence and code-to-code comparison only."
            ),
            (
                "Employee home division codes remain inferred "
                "historical context and require supervisor verification."
            ),
            (
                "Different-code rows are not automatically approved "
                "cross-division movements."
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
    print("CODE-ONLY DIVISION NORMALIZATION VALIDATION FINISHED")
    print(json.dumps(validation_summary, indent=2))
    return 0


def self_test() -> int:
    test_root = Path.cwd() / "_v1304_self_test_temp"
    if test_root.exists():
        shutil.rmtree(test_root)

    preview_path = test_root / "preview.csv"
    output_root = test_root / "runs"
    test_root.mkdir(parents=True)

    preview_rows = []
    employee_number = 1

    samples = [
        ("EstateA", "Lower Context", "F1", "GRP", "GRP"),
        ("EstateA", "Upper Context", "F2", "GRP", "GRP"),
        ("EstateA", "Other Context", "F3", "OTH", "GRP"),
    ]

    for scenario in ("EXPECTED", "CONSERVATIVE"):
        for (
            estate,
            division_context,
            field,
            assigned_code,
            home_code,
        ) in samples:
            preview_rows.append({
                "allocation_date": "2026-07-24",
                "scenario": scenario,
                "estate": estate,
                "division": division_context,
                "field": field,
                "employee_key": (
                    f"{estate}|EMP-{employee_number:03d}"
                ),
                "employee_id": (
                    f"EMP-{employee_number:03d}"
                ),
                "field_crop_kg": "100",
                "plucker_capacity_kg": "20",
                "field_assigned_capacity_kg": "100",
                "field_under_kg": "0",
                "field_over_kg": "0",
                "candidate_scope": "SAME_DIVISION",
                "cross_division": "YES",
                "inferred_home_division": home_code,
                "solver_status": "OPTIMAL",
                "source_assignment_method": "CP_SAT_BASELINE",
                "operational_use_allowed": "NO",
                "live_assignment_authorized": "NO",
            })
            employee_number += 1

    write_csv(
        preview_path,
        preview_rows,
        list(preview_rows[0].keys()),
    )

    prepare_code_only_pack(
        preview_path,
        output_root,
    )

    pointer = (
        output_root
        / "LATEST_CODE_ONLY_DIVISION_NORMALIZATION_V1304_RUN.txt"
    )
    run_folder = Path(
        pointer.read_text(encoding="utf-8").strip()
    )
    evidence_path = (
        run_folder
        / "review_input"
        / "official_field_division_code_input.csv"
    )
    evidence_rows = read_csv(evidence_path)

    code_by_field = {
        "F1": "GRP",
        "F2": "GRP",
        "F3": "OTH",
    }

    for row in evidence_rows:
        row["official_assigned_division_code"] = (
            code_by_field[row["field"]]
        )
        row["source_document_name"] = (
            "Approved Field Division Code Register"
        )
        row["source_document_date"] = "2026-07-24"
        row["source_sheet_or_page"] = "Code Register"
        row["source_row_or_cell_reference"] = (
            f"EstateA-{row['field']}"
        )
        row["source_document_owner"] = "EstateA"
        row["verified_by"] = "Authorized Reviewer"
        row["verified_at"] = "2026-07-24 16:30"
        row["evidence_status"] = "VERIFIED"
        row["employee_home_code_verified"] = "NO"
        row["operational_use_allowed"] = "NO"
        row["live_assignment_authorized"] = "NO"

    write_csv(
        evidence_path,
        evidence_rows,
        list(evidence_rows[0].keys()),
    )

    validate_code_only_run(run_folder)

    validation = json.loads(
        (run_folder / "validation_summary.json").read_text(
            encoding="utf-8"
        )
    )

    if validation["code_evidence_failures"] != 0:
        raise RuntimeError(
            "Code-only evidence self-test failed."
        )
    if validation["normalized_allocation_rows"] != len(
        preview_rows
    ):
        raise RuntimeError(
            "Code-only row-count self-test failed."
        )
    if validation["code_comparison_counts"].get("NO") != 4:
        raise RuntimeError(
            "Code comparison self-test failed."
        )
    if validation["code_comparison_counts"].get("YES") != 2:
        raise RuntimeError(
            "Different-code comparison self-test failed."
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
    parser.add_argument("--preview-path")
    parser.add_argument("--source-run", default="")
    parser.add_argument("--validate-run")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    if args.validate_run:
        return validate_code_only_run(
            Path(args.validate_run).resolve()
        )

    if not args.output_root:
        raise SystemExit("--output-root is required.")

    if args.preview_path:
        preview_path = Path(
            args.preview_path
        ).resolve()
        source_run = args.source_run
    else:
        if not args.project_root:
            raise SystemExit(
                "--project-root is required when "
                "--preview-path is omitted."
            )
        preview_path, source_run = (
            discover_source_preview(
                Path(args.project_root).resolve()
            )
        )

    return prepare_code_only_pack(
        preview_path,
        Path(args.output_root).resolve(),
        source_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
