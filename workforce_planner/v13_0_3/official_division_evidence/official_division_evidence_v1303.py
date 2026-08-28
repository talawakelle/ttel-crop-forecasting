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


VERSION = "13.0.3"
CREATION_STATUS = (
    "PASS_OFFICIAL_DIVISION_EVIDENCE_PACK_CREATED"
)
VALIDATION_STATUS = (
    "PASS_OFFICIAL_DIVISION_EVIDENCE_VALIDATION_OUTPUTS"
)


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def upper(value: Any) -> str:
    return clean(value).upper()


def canonical(value: Any) -> str:
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


def mapping_key(
    estate: Any,
    home_code: Any,
) -> tuple[str, str]:
    return canonical(estate), canonical(home_code)


def division_key(value: Any) -> str:
    return canonical(value)


def discover_v1302_run(project_root: Path) -> Path:
    run_root = (
        project_root
        / "workforce_planner"
        / "v13_0_2"
        / "division_identity_normalization_runs"
    )
    pointer = (
        run_root
        / "LATEST_DIVISION_IDENTITY_NORMALIZATION_V1302_RUN.txt"
    )

    candidate_runs: list[Path] = []

    if pointer.exists():
        pointer_text = clean(pointer.read_text(encoding="utf-8"))
        if pointer_text:
            candidate_runs.append(Path(pointer_text))

    if run_root.exists():
        candidate_runs.extend(
            sorted(
                [
                    path
                    for path in run_root.iterdir()
                    if path.is_dir()
                    and path.name.startswith(
                        "division_identity_normalization_"
                    )
                ],
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        )

    checked: set[str] = set()
    for run_folder in candidate_runs:
        key = str(run_folder).lower()
        if key in checked:
            continue
        checked.add(key)

        mapping_path = (
            run_folder
            / "review_input"
            / "division_identity_mapping_review.csv"
        )
        preview_path = (
            run_folder
            / "allocation"
            / "suggested_division_normalization_preview.csv"
        )
        summary_path = run_folder / "run_summary.json"

        if (
            mapping_path.exists()
            and preview_path.exists()
            and summary_path.exists()
        ):
            return run_folder

    raise SystemExit(
        "No complete v13.0.2 division-normalization run was found. "
        "Run v13.0.2 first."
    )


def validate_mapping_headers(
    rows: list[dict[str, str]],
    path: Path,
) -> None:
    required = {
        "estate",
        "home_division_code",
        "available_assigned_divisions",
        "suggested_division_name",
        "suggestion_confidence",
        "allocation_rows_for_code",
    }
    if not rows:
        raise SystemExit(f"Mapping review is empty: {path}")
    headers = {clean(item) for item in rows[0].keys()}
    missing = sorted(required - headers)
    if missing:
        raise SystemExit(
            "Mapping review is missing required columns: "
            + ", ".join(missing)
        )


def validate_preview_headers(
    rows: list[dict[str, str]],
    path: Path,
) -> None:
    required = {
        "allocation_date",
        "scenario",
        "estate",
        "division",
        "field",
        "employee_id",
        "inferred_home_division",
        "field_crop_kg",
        "plucker_capacity_kg",
        "field_assigned_capacity_kg",
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


def prepare_evidence_pack(
    mapping_path: Path,
    preview_path: Path,
    output_root: Path,
    source_v1302_run: Path | None = None,
) -> int:
    mapping_rows = read_csv(mapping_path)
    preview_rows = read_csv(preview_path)

    validate_mapping_headers(mapping_rows, mapping_path)
    validate_preview_headers(preview_rows, preview_path)

    run_folder = (
        output_root
        / datetime.now().strftime(
            "official_division_evidence_%Y%m%d_%H%M%S"
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

    preview_divisions: dict[
        tuple[str, str],
        set[str],
    ] = defaultdict(set)

    for row in preview_rows:
        key = mapping_key(
            row.get("estate"),
            row.get("inferred_home_division"),
        )
        division = clean(row.get("division"))
        if division:
            preview_divisions[key].add(division)

    evidence_rows: list[dict[str, Any]] = []
    priority_rows: list[dict[str, Any]] = []
    mapping_keys: set[tuple[str, str]] = set()

    for mapping in mapping_rows:
        estate = clean(mapping.get("estate"))
        code = clean(mapping.get("home_division_code"))
        key = mapping_key(estate, code)
        mapping_keys.add(key)

        candidates = [
            item.strip()
            for item in clean(
                mapping.get("available_assigned_divisions")
            ).split("|")
            if item.strip()
        ]

        if not candidates:
            candidates = sorted(
                preview_divisions.get(key, set()),
                key=str.lower,
            )

        suggestion = clean(
            mapping.get("suggested_division_name")
        )
        confidence = clean(
            mapping.get("suggestion_confidence")
        )
        is_priority = (
            not suggestion
            or upper(confidence) == "LOW"
        )

        for candidate in candidates:
            row = {
                "estate": estate,
                "home_division_code": code,
                "candidate_division_name": candidate,
                "current_system_suggestion": (
                    "YES"
                    if division_key(candidate)
                    == division_key(suggestion)
                    and suggestion
                    else "NO"
                ),
                "suggestion_confidence": confidence,
                "allocation_rows_for_code": clean(
                    mapping.get("allocation_rows_for_code")
                ),
                "include_as_valid_mapping": "",
                "mapping_scope": "",
                "source_document_name": "",
                "source_document_date": "",
                "source_sheet_or_page": "",
                "source_row_or_cell_reference": "",
                "source_document_owner": "",
                "approved_by": "",
                "approved_at": "",
                "evidence_status": "PENDING",
                "comments": "",
                "operational_use_allowed": "NO",
                "live_assignment_authorized": "NO",
            }
            evidence_rows.append(row)

            if is_priority:
                priority_rows.append(dict(row))

    evidence_fields = list(evidence_rows[0].keys())

    evidence_path = (
        review_input
        / "official_division_code_evidence_input.csv"
    )
    write_csv(
        evidence_path,
        evidence_rows,
        evidence_fields,
    )

    priority_path = (
        review_input
        / "priority_unresolved_division_evidence.csv"
    )
    write_csv(
        priority_path,
        priority_rows,
        evidence_fields,
    )

    source_register_rows = [
        {
            "source_document_name": "",
            "document_type": "",
            "document_owner": "",
            "document_date": "",
            "effective_from": "",
            "effective_to": "",
            "approval_reference": "",
            "file_location_or_link": "",
            "checked_by": "",
            "checked_at": "",
            "status": "PENDING",
            "comments": "",
            "live_assignment_authorized": "NO",
        }
    ]
    write_csv(
        review_input / "official_source_document_register.csv",
        source_register_rows,
        list(source_register_rows[0].keys()),
    )

    priority_keys = {
        mapping_key(
            row.get("estate"),
            row.get("home_division_code"),
        )
        for row in priority_rows
    }

    estate_summary_rows: list[dict[str, Any]] = []
    by_estate_keys: dict[str, set[tuple[str, str]]] = (
        defaultdict(set)
    )
    by_estate_candidates: Counter[str] = Counter()
    by_estate_priority: dict[str, set[tuple[str, str]]] = (
        defaultdict(set)
    )

    for row in evidence_rows:
        estate = clean(row.get("estate"))
        key = mapping_key(
            row.get("estate"),
            row.get("home_division_code"),
        )
        by_estate_keys[estate].add(key)
        by_estate_candidates[estate] += 1
        if key in priority_keys:
            by_estate_priority[estate].add(key)

    for estate in sorted(by_estate_keys, key=str.lower):
        estate_summary_rows.append({
            "estate": estate,
            "division_code_keys": len(
                by_estate_keys[estate]
            ),
            "candidate_evidence_rows": (
                by_estate_candidates[estate]
            ),
            "priority_unresolved_keys": len(
                by_estate_priority[estate]
            ),
            "verified_valid_mapping_rows": 0,
            "evidence_status": "SOURCE_DOCUMENT_INPUT_REQUIRED",
            "live_assignment_authorized": "NO",
        })

    write_csv(
        summary_dir / "estate_evidence_intake_summary.csv",
        estate_summary_rows,
        list(estate_summary_rows[0].keys()),
    )

    creation_gate = [
        {
            "check": "SOURCE_MAPPING_KEYS",
            "value": len(mapping_keys),
            "required": 107,
            "status": (
                "PASS"
                if len(mapping_keys) == 107
                else "FAIL"
            ),
        },
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
            "check": "EVIDENCE_CANDIDATE_ROWS",
            "value": len(evidence_rows),
            "required": ">0",
            "status": (
                "PASS" if evidence_rows else "FAIL"
            ),
        },
        {
            "check": "PRIORITY_UNRESOLVED_KEYS",
            "value": len(priority_keys),
            "required": 4,
            "status": (
                "PASS"
                if len(priority_keys) == 4
                else "REVIEW"
            ),
        },
        {
            "check": "OFFICIAL_EVIDENCE_COMPLETE",
            "value": False,
            "required": True,
            "status": "INPUT_REQUIRED",
        },
        {
            "check": "LIVE_DEPLOYMENT_STARTED",
            "value": False,
            "required": False,
            "status": "PASS",
        },
    ]
    write_csv(
        quality_dir / "official_evidence_pack_gate.csv",
        creation_gate,
        ["check", "value", "required", "status"],
    )

    instructions = (
        "Use only official source documents such as the approved "
        "division master, cost-centre master, employee home-division "
        "register, HR master, or an estate-manager-approved register.\n\n"
        "For every candidate row in "
        "official_division_code_evidence_input.csv:\n"
        "1. Enter YES or NO in include_as_valid_mapping.\n"
        "2. If YES, enter SINGLE_DIVISION or DIVISION_GROUP in "
        "mapping_scope.\n"
        "3. If YES, complete every source-document and approval field.\n"
        "4. Set evidence_status to VERIFIED only when the document "
        "supports the mapping.\n"
        "5. Keep operational_use_allowed and "
        "live_assignment_authorized as NO.\n\n"
        "One estate/code may have several YES rows when the code is an "
        "official division group, for example Lower and Upper.\n\n"
        "The priority file contains the four currently unresolved code "
        "groups. It is a working view only; enter final evidence in "
        "official_division_code_evidence_input.csv.\n\n"
        "After completing the official evidence file, run "
        "VALIDATE_OFFICIAL_DIVISION_EVIDENCE_v13.0.3.ps1.\n"
    )
    (
        review_input / "OFFICIAL_EVIDENCE_INSTRUCTIONS.txt"
    ).write_text(instructions, encoding="utf-8")

    summary = {
        "status": CREATION_STATUS,
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "source_v13_0_2_run": (
            str(source_v1302_run)
            if source_v1302_run is not None
            else ""
        ),
        "source_mapping_path": str(mapping_path),
        "source_preview_path": str(preview_path),
        "source_mapping_keys": len(mapping_keys),
        "source_allocation_rows": len(preview_rows),
        "evidence_candidate_rows": len(evidence_rows),
        "priority_unresolved_keys": len(priority_keys),
        "estate_count": len(by_estate_keys),
        "review_gate": "OFFICIAL_SOURCE_DOCUMENT_INPUT_REQUIRED",
        "official_evidence_started": False,
        "official_evidence_completed": False,
        "operational_status": "OFFICIAL_EVIDENCE_COLLECTION_ONLY",
        "live_deployment_started": False,
        "important_interpretation": [
            (
                "Generated suggestions and allocation history are not "
                "official evidence of division-code ownership."
            ),
            (
                "A division code may map to more than one full division "
                "only when an official source document proves a group "
                "mapping."
            ),
            (
                "No mapping will be validated from system suggestions "
                "alone."
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
        / "LATEST_OFFICIAL_DIVISION_EVIDENCE_V1303_RUN.txt"
    ).write_text(str(run_folder), encoding="utf-8")

    print("")
    print("OFFICIAL DIVISION EVIDENCE PACK CREATED")
    print(json.dumps(summary, indent=2))
    return 0


def validate_evidence_run(run_folder: Path) -> int:
    summary_path = run_folder / "run_summary.json"
    if not summary_path.exists():
        raise SystemExit(
            f"Missing run_summary.json: {run_folder}"
        )

    creation = json.loads(
        summary_path.read_text(encoding="utf-8")
    )
    evidence_path = (
        run_folder
        / "review_input"
        / "official_division_code_evidence_input.csv"
    )
    preview_path = Path(creation["source_preview_path"])

    if not evidence_path.exists():
        raise SystemExit(
            f"Evidence input is missing: {evidence_path}"
        )
    if not preview_path.exists():
        raise SystemExit(
            f"Source allocation preview is missing: {preview_path}"
        )

    evidence_rows = read_csv(evidence_path)
    preview_rows = read_csv(preview_path)

    validate_preview_headers(preview_rows, preview_path)

    source_candidates: dict[
        tuple[str, str],
        dict[str, str],
    ] = defaultdict(dict)

    for preview in preview_rows:
        key = mapping_key(
            preview.get("estate"),
            preview.get("inferred_home_division"),
        )
        division = clean(preview.get("division"))
        if division:
            source_candidates[key][
                division_key(division)
            ] = division

    source_keys = set(source_candidates)
    evidence_key_counts = Counter(
        (
            *mapping_key(
                row.get("estate"),
                row.get("home_division_code"),
            ),
            division_key(
                row.get("candidate_division_name")
            ),
        )
        for row in evidence_rows
    )

    duplicate_candidate_rows = {
        key: count
        for key, count in evidence_key_counts.items()
        if count > 1
    }

    failures: list[dict[str, Any]] = []
    valid_mappings: dict[
        tuple[str, str],
        set[str],
    ] = defaultdict(set)
    valid_display: dict[
        tuple[str, str],
        dict[str, str],
    ] = defaultdict(dict)

    rows_by_key: dict[
        tuple[str, str],
        list[dict[str, str]],
    ] = defaultdict(list)

    for row in evidence_rows:
        key = mapping_key(
            row.get("estate"),
            row.get("home_division_code"),
        )
        rows_by_key[key].append(row)

        decision = upper(
            row.get("include_as_valid_mapping")
        )
        candidate = clean(
            row.get("candidate_division_name")
        )
        candidate_key = division_key(candidate)
        reasons: list[str] = []

        if (
            (
                key[0],
                key[1],
                candidate_key,
            )
            in duplicate_candidate_rows
        ):
            reasons.append("DUPLICATE_EVIDENCE_CANDIDATE_ROW")

        if key not in source_keys:
            reasons.append("UNKNOWN_ESTATE_CODE_KEY")

        if (
            candidate_key
            not in source_candidates.get(key, {})
        ):
            reasons.append(
                "CANDIDATE_DIVISION_NOT_IN_SOURCE_ALLOCATION"
            )

        if decision not in {"YES", "NO"}:
            reasons.append("YES_OR_NO_DECISION_REQUIRED")

        if not no(row.get("operational_use_allowed")):
            reasons.append(
                "OPERATIONAL_USE_ALLOWED_MUST_REMAIN_NO"
            )

        if not no(row.get("live_assignment_authorized")):
            reasons.append(
                "LIVE_ASSIGNMENT_AUTHORIZED_MUST_REMAIN_NO"
            )

        if decision == "YES":
            if upper(row.get("mapping_scope")) not in {
                "SINGLE_DIVISION",
                "DIVISION_GROUP",
            }:
                reasons.append(
                    "MAPPING_SCOPE_REQUIRED_FOR_YES"
                )

            required_fields = [
                "source_document_name",
                "source_document_date",
                "source_sheet_or_page",
                "source_row_or_cell_reference",
                "source_document_owner",
                "approved_by",
                "approved_at",
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

        if reasons:
            failures.append({
                "estate": clean(row.get("estate")),
                "home_division_code": clean(
                    row.get("home_division_code")
                ),
                "candidate_division_name": candidate,
                "include_as_valid_mapping": decision,
                "failure_reasons": "|".join(reasons),
            })
        elif decision == "YES":
            valid_mappings[key].add(candidate_key)
            valid_display[key][candidate_key] = (
                source_candidates[key][candidate_key]
            )

    missing_key_decisions = [
        key
        for key in sorted(source_keys)
        if key not in rows_by_key
    ]

    for key in missing_key_decisions:
        failures.append({
            "estate": key[0],
            "home_division_code": key[1],
            "candidate_division_name": "",
            "include_as_valid_mapping": "",
            "failure_reasons": "MISSING_EVIDENCE_KEY",
        })

    keys_without_valid_mapping = [
        key
        for key in sorted(source_keys)
        if not valid_mappings.get(key)
    ]

    for key in keys_without_valid_mapping:
        failures.append({
            "estate": key[0],
            "home_division_code": key[1],
            "candidate_division_name": "",
            "include_as_valid_mapping": "",
            "failure_reasons": (
                "AT_LEAST_ONE_VERIFIED_VALID_DIVISION_REQUIRED"
            ),
        })

    quality_dir = run_folder / "quality"
    allocation_dir = run_folder / "allocation"
    summary_dir = run_folder / "summary"
    quality_dir.mkdir(exist_ok=True)
    allocation_dir.mkdir(exist_ok=True)
    summary_dir.mkdir(exist_ok=True)

    write_csv(
        quality_dir
        / "official_division_evidence_failures.csv",
        failures,
        [
            "estate",
            "home_division_code",
            "candidate_division_name",
            "include_as_valid_mapping",
            "failure_reasons",
        ],
    )

    normalized_rows: list[dict[str, Any]] = []
    duplicate_assignment_failures: list[dict[str, Any]] = []

    evidence_complete = (
        not failures
        and not duplicate_candidate_rows
        and len(valid_mappings) == len(source_keys)
    )

    if evidence_complete:
        for preview in preview_rows:
            key = mapping_key(
                preview.get("estate"),
                preview.get("inferred_home_division"),
            )
            assigned_key = division_key(
                preview.get("division")
            )
            normalized_cross = (
                "NO"
                if assigned_key in valid_mappings[key]
                else "YES"
            )

            valid_names = sorted(
                valid_display[key].values(),
                key=str.lower,
            )

            row = dict(preview)
            row.update({
                "official_valid_home_divisions": "|".join(
                    valid_names
                ),
                "official_mapping_scope": (
                    "DIVISION_GROUP"
                    if len(valid_names) > 1
                    else "SINGLE_DIVISION"
                ),
                "normalized_cross_division": (
                    normalized_cross
                ),
                "official_division_evidence_verified": "YES",
                "actual_supervisor_verified": "NO",
                "attendance_verified": "NO",
                "approved_leave_verified": "NO",
                "fitness_verified": "NO",
                "movement_restrictions_verified": "NO",
                "operational_use_allowed": "NO",
                "live_assignment_authorized": "NO",
                "allocation_status": (
                    "OFFICIAL_DIVISION_NORMALIZED_"
                    "SIMULATION_FOR_REVIEW"
                ),
            })
            normalized_rows.append(row)

        assignment_counts = Counter(
            (
                upper(row.get("allocation_date")),
                upper(row.get("scenario")),
                canonical(row.get("estate")),
                canonical(row.get("employee_id")),
            )
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

        normalized_fields = list(
            normalized_rows[0].keys()
        )

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
            / "expected_primary_officially_normalized_allocation.csv",
            expected_rows,
            normalized_fields,
        )
        write_csv(
            allocation_dir
            / "conservative_backup_officially_normalized_allocation.csv",
            conservative_rows,
            normalized_fields,
        )
        write_csv(
            allocation_dir
            / "all_officially_normalized_allocations.csv",
            normalized_rows,
            normalized_fields,
        )

        movement_counts: dict[
            tuple[str, str],
            Counter[str],
        ] = defaultdict(Counter)

        for row in normalized_rows:
            group = (
                clean(row.get("estate")),
                upper(row.get("scenario")),
            )
            movement_counts[group][
                upper(row.get("normalized_cross_division"))
            ] += 1

        movement_summary = []
        for group in sorted(
            movement_counts,
            key=lambda item: (
                item[0].lower(),
                item[1],
            ),
        ):
            counts = movement_counts[group]
            total = counts["YES"] + counts["NO"]
            movement_summary.append({
                "estate": group[0],
                "scenario": group[1],
                "assignment_rows": total,
                "same_division_rows": counts["NO"],
                "cross_division_rows": counts["YES"],
                "cross_division_rate_pct": (
                    round(
                        counts["YES"] * 100.0 / total,
                        2,
                    )
                    if total
                    else 0.0
                ),
                "live_assignment_authorized": "NO",
            })

        write_csv(
            summary_dir
            / "official_normalized_movement_summary.csv",
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

    all_live_flags_no = all(
        no(row.get("live_assignment_authorized"))
        and no(row.get("operational_use_allowed"))
        for row in evidence_rows
    ) and all(
        no(row.get("live_assignment_authorized"))
        and no(row.get("operational_use_allowed"))
        for row in normalized_rows
    )

    final_pass = (
        evidence_complete
        and len(normalized_rows) == len(preview_rows)
        and not duplicate_assignment_failures
        and all_live_flags_no
    )

    validation_gate = [
        {
            "check": "SOURCE_MAPPING_KEYS",
            "value": len(source_keys),
            "required": len(source_keys),
            "status": "PASS",
        },
        {
            "check": "OFFICIAL_EVIDENCE_ROWS",
            "value": len(evidence_rows),
            "required": ">0",
            "status": (
                "PASS" if evidence_rows else "FAIL"
            ),
        },
        {
            "check": "DUPLICATE_EVIDENCE_CANDIDATE_ROWS",
            "value": len(duplicate_candidate_rows),
            "required": 0,
            "status": (
                "PASS"
                if not duplicate_candidate_rows
                else "FAIL"
            ),
        },
        {
            "check": "OFFICIAL_EVIDENCE_FAILURES",
            "value": len(failures),
            "required": 0,
            "status": (
                "PASS" if not failures else "FAIL"
            ),
        },
        {
            "check": "MAPPING_KEYS_WITH_VALID_EVIDENCE",
            "value": len(valid_mappings),
            "required": len(source_keys),
            "status": (
                "PASS"
                if len(valid_mappings) == len(source_keys)
                else "FAIL"
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
            "check": "LIVE_AND_OPERATIONAL_FLAGS_ALL_NO",
            "value": all_live_flags_no,
            "required": True,
            "status": (
                "PASS" if all_live_flags_no else "FAIL"
            ),
        },
    ]
    write_csv(
        quality_dir
        / "official_division_evidence_gate.csv",
        validation_gate,
        ["check", "value", "required", "status"],
    )

    normalized_counts = Counter(
        upper(row.get("normalized_cross_division"))
        for row in normalized_rows
    )

    validation_summary = {
        "status": VALIDATION_STATUS,
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "source_mapping_keys": len(source_keys),
        "official_evidence_rows": len(evidence_rows),
        "verified_valid_mapping_keys": len(valid_mappings),
        "official_evidence_failures": len(failures),
        "normalized_allocation_rows": len(normalized_rows),
        "expected_primary_rows": sum(
            upper(row.get("scenario")) == "EXPECTED"
            for row in normalized_rows
        ),
        "conservative_backup_rows": sum(
            upper(row.get("scenario")) == "CONSERVATIVE"
            for row in normalized_rows
        ),
        "normalized_cross_division_counts": dict(
            normalized_counts
        ),
        "duplicate_employee_assignment_failures": len(
            duplicate_assignment_failures
        ),
        "review_gate": (
            "READY_FOR_SUPERVISOR_EXPECTED_ALLOCATION_REVIEW"
            if final_pass
            else "OFFICIAL_EVIDENCE_INPUT_OR_CORRECTION_REQUIRED"
        ),
        "official_evidence_started": any(
            upper(row.get("include_as_valid_mapping"))
            in {"YES", "NO"}
            for row in evidence_rows
        ),
        "official_evidence_completed": final_pass,
        "operational_status": (
            "OFFICIAL_DIVISION_NORMALIZED_REVIEW_ONLY"
        ),
        "live_deployment_started": False,
        "important_interpretation": [
            (
                "A passing gate confirms official division-code "
                "evidence completeness and normalization only."
            ),
            (
                "It does not verify current attendance, leave, fitness, "
                "movement permission or employee availability."
            ),
            (
                "The EXPECTED output is the primary review scenario and "
                "the CONSERVATIVE output is the backup review scenario."
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
    print("OFFICIAL DIVISION EVIDENCE VALIDATION FINISHED")
    print(json.dumps(validation_summary, indent=2))
    return 0


def self_test() -> int:
    test_root = Path.cwd() / "_v1303_self_test_temp"
    if test_root.exists():
        shutil.rmtree(test_root)

    mapping_path = test_root / "mapping.csv"
    preview_path = test_root / "preview.csv"
    output_root = test_root / "runs"
    test_root.mkdir(parents=True)

    mapping_rows = [
        {
            "estate": "EstateA",
            "home_division_code": "GRP",
            "available_assigned_divisions": (
                "Lower Division|Upper Division|Other Division"
            ),
            "suggested_division_name": "",
            "suggestion_method": "AMBIGUOUS_SUGGESTION",
            "suggestion_confidence": "LOW",
            "allocation_rows_for_code": "4",
            "raw_cross_division_yes_rows": "4",
            "raw_cross_division_no_rows": "0",
            "confirmed_division_name": "",
            "manager_confirmed": "NO",
            "reviewer_name": "",
            "reviewed_at": "",
            "comments": "",
            "live_assignment_authorized": "NO",
        }
    ]

    preview_rows = []
    employee = 1
    for scenario in ("EXPECTED", "CONSERVATIVE"):
        for division in (
            "Lower Division",
            "Upper Division",
            "Other Division",
        ):
            preview_rows.append({
                "allocation_date": "2026-07-24",
                "scenario": scenario,
                "estate": "EstateA",
                "division": division,
                "field": f"{division}-F1",
                "employee_key": (
                    f"EstateA|EMP-{employee:03d}"
                ),
                "employee_id": f"EMP-{employee:03d}",
                "field_crop_kg": "100",
                "plucker_capacity_kg": "20",
                "field_assigned_capacity_kg": "100",
                "field_under_kg": "0",
                "field_over_kg": "0",
                "candidate_scope": "SAME_DIVISION",
                "cross_division": "YES",
                "inferred_home_division": "GRP",
                "solver_status": "OPTIMAL",
                "source_assignment_method": "CP_SAT_BASELINE",
                "operational_use_allowed": "NO",
                "live_assignment_authorized": "NO",
            })
            employee += 1

    write_csv(
        mapping_path,
        mapping_rows,
        list(mapping_rows[0].keys()),
    )
    write_csv(
        preview_path,
        preview_rows,
        list(preview_rows[0].keys()),
    )

    prepare_evidence_pack(
        mapping_path,
        preview_path,
        output_root,
    )

    pointer = (
        output_root
        / "LATEST_OFFICIAL_DIVISION_EVIDENCE_V1303_RUN.txt"
    )
    run_folder = Path(
        pointer.read_text(encoding="utf-8").strip()
    )
    evidence_path = (
        run_folder
        / "review_input"
        / "official_division_code_evidence_input.csv"
    )
    evidence_rows = read_csv(evidence_path)

    for row in evidence_rows:
        candidate = clean(row["candidate_division_name"])
        row["include_as_valid_mapping"] = (
            "YES"
            if candidate in {
                "Lower Division",
                "Upper Division",
            }
            else "NO"
        )
        if row["include_as_valid_mapping"] == "YES":
            row["mapping_scope"] = "DIVISION_GROUP"
            row["source_document_name"] = (
                "Approved Division Master"
            )
            row["source_document_date"] = "2026-07-24"
            row["source_sheet_or_page"] = "Division Master"
            row["source_row_or_cell_reference"] = (
                f"EstateA-GRP-{candidate}"
            )
            row["source_document_owner"] = "EstateA"
            row["approved_by"] = "Authorized Reviewer"
            row["approved_at"] = "2026-07-24 16:00"
            row["evidence_status"] = "VERIFIED"
        else:
            row["evidence_status"] = "REJECTED"

        row["operational_use_allowed"] = "NO"
        row["live_assignment_authorized"] = "NO"

    write_csv(
        evidence_path,
        evidence_rows,
        list(evidence_rows[0].keys()),
    )

    validate_evidence_run(run_folder)

    validation = json.loads(
        (run_folder / "validation_summary.json").read_text(
            encoding="utf-8"
        )
    )

    if validation["official_evidence_failures"] != 0:
        raise RuntimeError("Official evidence self-test failed.")
    if validation["normalized_allocation_rows"] != len(
        preview_rows
    ):
        raise RuntimeError(
            "Normalized allocation row-count self-test failed."
        )
    if validation["normalized_cross_division_counts"].get(
        "NO"
    ) != 4:
        raise RuntimeError(
            "One-to-many group normalization self-test failed."
        )
    if validation["live_deployment_started"] is not False:
        raise RuntimeError("Live-control self-test failed.")

    shutil.rmtree(test_root)
    print("SELF_TEST_PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root")
    parser.add_argument("--output-root")
    parser.add_argument("--source-v1302-run")
    parser.add_argument("--mapping-path")
    parser.add_argument("--preview-path")
    parser.add_argument("--validate-run")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    if args.validate_run:
        return validate_evidence_run(
            Path(args.validate_run).resolve()
        )

    if not args.output_root:
        raise SystemExit("--output-root is required.")

    source_v1302_run: Path | None = None

    if args.mapping_path and args.preview_path:
        mapping_path = Path(args.mapping_path).resolve()
        preview_path = Path(args.preview_path).resolve()
        if args.source_v1302_run:
            source_v1302_run = Path(
                args.source_v1302_run
            ).resolve()
    else:
        if not args.project_root:
            raise SystemExit(
                "--project-root is required when source files "
                "are not supplied."
            )
        source_v1302_run = discover_v1302_run(
            Path(args.project_root).resolve()
        )
        mapping_path = (
            source_v1302_run
            / "review_input"
            / "division_identity_mapping_review.csv"
        )
        preview_path = (
            source_v1302_run
            / "allocation"
            / "suggested_division_normalization_preview.csv"
        )

    return prepare_evidence_pack(
        mapping_path,
        preview_path,
        Path(args.output_root).resolve(),
        source_v1302_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
