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


VERSION = "13.0.2"
CREATION_STATUS = (
    "PASS_DIVISION_IDENTITY_NORMALIZATION_REVIEW_PACK_CREATED"
)
VALIDATION_STATUS = (
    "PASS_DIVISION_IDENTITY_NORMALIZATION_VALIDATION_OUTPUTS"
)


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def upper(value: Any) -> str:
    return clean(value).upper()


def yes(value: Any) -> bool:
    return upper(value) == "YES"


def no(value: Any) -> bool:
    return upper(value) == "NO"


def canonical(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", upper(value))


def tokens(value: Any) -> list[str]:
    return re.findall(r"[A-Z0-9]+", upper(value))


def initials(value: Any) -> str:
    return "".join(token[0] for token in tokens(value) if token)


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


def required_headers() -> set[str]:
    return {
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
        "cross_division",
        "inferred_home_division",
        "operational_use_allowed",
        "live_assignment_authorized",
    }


def validate_source_headers(
    rows: list[dict[str, str]],
    source_path: Path,
) -> None:
    if not rows:
        raise SystemExit(f"Source allocation is empty: {source_path}")

    headers = {
        clean(header)
        for header in rows[0].keys()
    }
    missing = sorted(required_headers() - headers)
    if missing:
        raise SystemExit(
            "The source allocation is missing required columns: "
            + ", ".join(missing)
        )


def discover_source_allocation(project_root: Path) -> Path:
    run_root = (
        project_root
        / "workforce_planner"
        / "v13_0_1"
        / "named_plucker_allocation_runs"
    )
    pointer = (
        run_root
        / "LATEST_NAMED_PLUCKER_ALLOCATION_V1301_RUN.txt"
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
                        "named_plucker_allocation_kg_repair_"
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

        source_path = (
            run_folder
            / "allocation"
            / "named_plucker_allocation_simulation.csv"
        )
        if source_path.exists():
            return source_path

    raise SystemExit(
        "No v13.0.1 named_plucker_allocation_simulation.csv "
        "was found. Run v13.0.1 first."
    )


def score_division_candidate(
    home_code: str,
    assigned_division: str,
) -> tuple[int, str]:
    code = canonical(home_code)
    name = canonical(assigned_division)
    display_name = upper(assigned_division)

    if not code or not name:
        return 0, "NO_MATCH"

    if code == name:
        return 100, "EXACT_CANONICAL_MATCH"

    if len(code) >= 2 and name.startswith(code):
        return 95, "CODE_PREFIX_MATCH"

    if len(code) >= 2 and code == initials(assigned_division):
        return 92, "DIVISION_INITIALS_MATCH"

    if (
        code in {"LD", "LOW", "LOWER", "LO"}
        and "LOWER" in display_name
    ):
        return 94, "LOWER_DIVISION_ALIAS"

    if (
        code in {"UD", "UP", "UPPER", "U"}
        and "UPPER" in display_name
    ):
        return 94, "UPPER_DIVISION_ALIAS"

    if (
        code.endswith("LO")
        and "LOWER" in display_name
        and name.startswith(code[:-2])
    ):
        return 96, "PREFIX_LOWER_ALIAS"

    if (
        code.endswith("UP")
        and "UPPER" in display_name
        and name.startswith(code[:-2])
    ):
        return 96, "PREFIX_UPPER_ALIAS"

    if (
        len(code) == 2
        and code.endswith("D")
        and name.startswith(code[0])
    ):
        return 75, "FIRST_LETTER_DIVISION_ALIAS"

    if len(code) >= 3 and name[:3] == code[:3]:
        return 90, "THREE_CHARACTER_PREFIX_MATCH"

    return 0, "NO_MATCH"


def suggest_mapping(
    estate: str,
    home_code: str,
    assigned_divisions: list[str],
    raw_no_evidence: Counter[str],
) -> tuple[str, str, str]:
    evidence = [
        division
        for division, count in raw_no_evidence.items()
        if count > 0
    ]
    if len(evidence) == 1:
        return (
            evidence[0],
            "SOURCE_RAW_CROSS_DIVISION_NO_EVIDENCE",
            "HIGH",
        )

    if len(assigned_divisions) == 1:
        return (
            assigned_divisions[0],
            "ONLY_ASSIGNED_DIVISION_IN_ESTATE",
            "HIGH",
        )

    ranked = sorted(
        [
            (
                *score_division_candidate(
                    home_code,
                    division,
                ),
                division,
            )
            for division in assigned_divisions
        ],
        key=lambda item: (item[0], item[2]),
        reverse=True,
    )

    if not ranked or ranked[0][0] <= 0:
        return "", "NO_UNIQUE_SUGGESTION", "LOW"

    top_score = ranked[0][0]
    top_rows = [
        row
        for row in ranked
        if row[0] == top_score
    ]

    if len(top_rows) != 1:
        return "", "AMBIGUOUS_SUGGESTION", "LOW"

    score, method, division = top_rows[0]
    confidence = (
        "HIGH"
        if score >= 90
        else "MEDIUM"
        if score >= 70
        else "LOW"
    )
    return division, method, confidence


def mapping_key(
    estate: Any,
    home_code: Any,
) -> tuple[str, str]:
    return canonical(estate), canonical(home_code)


def allocation_employee_key(
    row: dict[str, Any],
) -> tuple[str, str, str, str]:
    return (
        upper(row.get("allocation_date")),
        upper(row.get("scenario")),
        canonical(row.get("estate")),
        canonical(row.get("employee_id")),
    )


def prepare_review_pack(
    source_path: Path,
    output_root: Path,
) -> int:
    source_rows = read_csv(source_path)
    validate_source_headers(source_rows, source_path)

    run_folder = (
        output_root
        / datetime.now().strftime(
            "division_identity_normalization_%Y%m%d_%H%M%S"
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

    estate_divisions: dict[str, set[str]] = defaultdict(set)
    code_counts: Counter[tuple[str, str]] = Counter()
    raw_yes_counts: Counter[tuple[str, str]] = Counter()
    raw_no_counts: Counter[tuple[str, str]] = Counter()
    raw_no_evidence: dict[
        tuple[str, str],
        Counter[str],
    ] = defaultdict(Counter)

    for row in source_rows:
        estate = clean(row.get("estate"))
        division = clean(row.get("division"))
        home_code = clean(row.get("inferred_home_division"))
        key = mapping_key(estate, home_code)

        if estate and division:
            estate_divisions[estate].add(division)

        code_counts[key] += 1

        if yes(row.get("cross_division")):
            raw_yes_counts[key] += 1
        elif no(row.get("cross_division")):
            raw_no_counts[key] += 1
            raw_no_evidence[key][division] += 1

    mapping_rows: list[dict[str, Any]] = []
    suggestion_lookup: dict[
        tuple[str, str],
        tuple[str, str, str],
    ] = {}

    estate_display_by_key = {
        canonical(estate): estate
        for estate in estate_divisions
    }

    all_keys = sorted(
        code_counts,
        key=lambda key: (
            estate_display_by_key.get(key[0], key[0]).lower(),
            key[1],
        ),
    )

    for key in all_keys:
        estate_key, home_code_key = key
        estate = estate_display_by_key.get(
            estate_key,
            estate_key,
        )

        source_home_codes = sorted(
            {
                clean(row.get("inferred_home_division"))
                for row in source_rows
                if mapping_key(
                    row.get("estate"),
                    row.get("inferred_home_division"),
                )
                == key
            }
        )
        home_code = (
            source_home_codes[0]
            if source_home_codes
            else home_code_key
        )

        divisions = sorted(
            estate_divisions.get(estate, set()),
            key=str.lower,
        )
        suggestion = suggest_mapping(
            estate,
            home_code,
            divisions,
            raw_no_evidence[key],
        )
        suggestion_lookup[key] = suggestion

        suggested_name, method, confidence = suggestion

        mapping_rows.append({
            "estate": estate,
            "home_division_code": home_code,
            "available_assigned_divisions": "|".join(divisions),
            "suggested_division_name": suggested_name,
            "suggestion_method": method,
            "suggestion_confidence": confidence,
            "allocation_rows_for_code": code_counts[key],
            "raw_cross_division_yes_rows": raw_yes_counts[key],
            "raw_cross_division_no_rows": raw_no_counts[key],
            "confirmed_division_name": "",
            "manager_confirmed": "NO",
            "reviewer_name": "",
            "reviewed_at": "",
            "comments": "",
            "live_assignment_authorized": "NO",
        })

    mapping_fields = list(mapping_rows[0].keys())
    mapping_path = (
        review_input
        / "division_identity_mapping_review.csv"
    )
    write_csv(mapping_path, mapping_rows, mapping_fields)

    preview_rows: list[dict[str, Any]] = []
    preview_counts = Counter()

    for source in source_rows:
        key = mapping_key(
            source.get("estate"),
            source.get("inferred_home_division"),
        )
        suggested_name, method, confidence = (
            suggestion_lookup.get(
                key,
                ("", "NO_UNIQUE_SUGGESTION", "LOW"),
            )
        )

        if not suggested_name:
            suggested_cross = "UNKNOWN"
        elif canonical(suggested_name) == canonical(
            source.get("division")
        ):
            suggested_cross = "NO"
        else:
            suggested_cross = "YES"

        preview_counts[suggested_cross] += 1

        row = dict(source)
        row.update({
            "suggested_home_division_name": suggested_name,
            "division_suggestion_method": method,
            "division_suggestion_confidence": confidence,
            "suggested_cross_division": suggested_cross,
            "division_mapping_confirmed": "NO",
            "division_mapping_status": (
                "PENDING_MANAGER_CONFIRMATION"
            ),
            "operational_use_allowed": "NO",
            "live_assignment_authorized": "NO",
        })
        preview_rows.append(row)

    preview_path = (
        allocation_dir
        / "suggested_division_normalization_preview.csv"
    )
    write_csv(
        preview_path,
        preview_rows,
        list(preview_rows[0].keys()),
    )

    raw_cross_counts = Counter(
        upper(row.get("cross_division"))
        for row in source_rows
    )
    raw_audit_rows = [
        {
            "indicator": "RAW_CROSS_DIVISION_YES_ROWS",
            "value": raw_cross_counts.get("YES", 0),
        },
        {
            "indicator": "RAW_CROSS_DIVISION_NO_ROWS",
            "value": raw_cross_counts.get("NO", 0),
        },
        {
            "indicator": "SUGGESTED_CROSS_DIVISION_YES_ROWS",
            "value": preview_counts.get("YES", 0),
        },
        {
            "indicator": "SUGGESTED_CROSS_DIVISION_NO_ROWS",
            "value": preview_counts.get("NO", 0),
        },
        {
            "indicator": "SUGGESTED_CROSS_DIVISION_UNKNOWN_ROWS",
            "value": preview_counts.get("UNKNOWN", 0),
        },
    ]
    write_csv(
        quality_dir / "raw_and_suggested_division_audit.csv",
        raw_audit_rows,
        ["indicator", "value"],
    )

    estate_mapping_summary = []
    rows_by_estate = defaultdict(list)
    for row in mapping_rows:
        rows_by_estate[row["estate"]].append(row)

    for estate in sorted(rows_by_estate, key=str.lower):
        estate_rows = rows_by_estate[estate]
        estate_mapping_summary.append({
            "estate": estate,
            "mapping_rows": len(estate_rows),
            "high_confidence_suggestions": sum(
                row["suggestion_confidence"] == "HIGH"
                for row in estate_rows
            ),
            "medium_confidence_suggestions": sum(
                row["suggestion_confidence"] == "MEDIUM"
                for row in estate_rows
            ),
            "low_or_ambiguous_suggestions": sum(
                row["suggestion_confidence"] == "LOW"
                for row in estate_rows
            ),
            "manager_confirmed_rows": 0,
            "mapping_status": "CONFIRMATION_REQUIRED",
        })

    write_csv(
        summary_dir / "estate_division_mapping_summary.csv",
        estate_mapping_summary,
        list(estate_mapping_summary[0].keys()),
    )

    creation_gate = [
        {
            "check": "SOURCE_ALLOCATION_ROWS",
            "value": len(source_rows),
            "required": 15014,
            "status": (
                "PASS"
                if len(source_rows) == 15014
                else "FAIL"
            ),
        },
        {
            "check": "SOURCE_ESTATES",
            "value": len(estate_divisions),
            "required": 33,
            "status": (
                "PASS"
                if len(estate_divisions) == 33
                else "FAIL"
            ),
        },
        {
            "check": "DIVISION_MAPPING_REVIEW_ROWS",
            "value": len(mapping_rows),
            "required": ">0",
            "status": (
                "PASS" if mapping_rows else "FAIL"
            ),
        },
        {
            "check": "DUPLICATE_MAPPING_KEYS",
            "value": (
                len(mapping_rows)
                - len(
                    {
                        mapping_key(
                            row["estate"],
                            row["home_division_code"],
                        )
                        for row in mapping_rows
                    }
                )
            ),
            "required": 0,
            "status": "PASS",
        },
        {
            "check": "MANAGER_CONFIRMATION_COMPLETE",
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
        quality_dir
        / "division_normalization_review_pack_gate.csv",
        creation_gate,
        ["check", "value", "required", "status"],
    )

    summary = {
        "status": CREATION_STATUS,
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "source_allocation_path": str(source_path),
        "source_allocation_rows": len(source_rows),
        "estate_count": len(estate_divisions),
        "mapping_review_rows": len(mapping_rows),
        "high_confidence_suggestions": sum(
            row["suggestion_confidence"] == "HIGH"
            for row in mapping_rows
        ),
        "medium_confidence_suggestions": sum(
            row["suggestion_confidence"] == "MEDIUM"
            for row in mapping_rows
        ),
        "ambiguous_or_low_suggestions": sum(
            row["suggestion_confidence"] == "LOW"
            for row in mapping_rows
        ),
        "raw_cross_division_counts": dict(raw_cross_counts),
        "suggested_cross_division_preview_counts": dict(
            preview_counts
        ),
        "review_gate": "DIVISION_MAPPING_CONFIRMATION_REQUIRED",
        "manager_review_started": False,
        "manager_review_completed": False,
        "operational_status": (
            "DIVISION_MAPPING_REVIEW_ONLY"
        ),
        "live_deployment_started": False,
        "important_interpretation": [
            (
                "The source cross_division indicator compares full "
                "division names with short home-division codes and "
                "must not be used operationally until normalized."
            ),
            (
                "Suggested mappings are pre-review suggestions only; "
                "they are not manager confirmations."
            ),
            (
                "Every estate-home-code mapping must be confirmed by "
                "an authorized estate reviewer."
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
        / "LATEST_DIVISION_IDENTITY_NORMALIZATION_V1302_RUN.txt"
    ).write_text(str(run_folder), encoding="utf-8")

    instructions = (
        "Complete division_identity_mapping_review.csv.\n"
        "For each row, review the suggested division, enter the "
        "confirmed full division name, set manager_confirmed to YES, "
        "and enter reviewer_name and reviewed_at.\n"
        "Do not change live_assignment_authorized from NO.\n"
        "After review, run VALIDATE_DIVISION_IDENTITY_NORMALIZATION_"
        "v13.0.2.ps1.\n"
    )
    (
        review_input / "REVIEW_INSTRUCTIONS.txt"
    ).write_text(instructions, encoding="utf-8")

    print("")
    print("DIVISION IDENTITY NORMALIZATION REVIEW PACK CREATED")
    print(json.dumps(summary, indent=2))
    return 0


def validate_mapping_run(run_folder: Path) -> int:
    source_summary_path = run_folder / "run_summary.json"
    if not source_summary_path.exists():
        raise SystemExit(
            f"Missing run_summary.json: {run_folder}"
        )

    source_summary = json.loads(
        source_summary_path.read_text(encoding="utf-8")
    )
    source_path = Path(source_summary["source_allocation_path"])
    mapping_path = (
        run_folder
        / "review_input"
        / "division_identity_mapping_review.csv"
    )

    if not source_path.exists():
        raise SystemExit(
            f"Source allocation no longer exists: {source_path}"
        )
    if not mapping_path.exists():
        raise SystemExit(
            f"Mapping review file is missing: {mapping_path}"
        )

    source_rows = read_csv(source_path)
    mapping_rows = read_csv(mapping_path)
    validate_source_headers(source_rows, source_path)

    source_keys = {
        mapping_key(
            row.get("estate"),
            row.get("inferred_home_division"),
        )
        for row in source_rows
    }

    mapping_counts = Counter(
        mapping_key(
            row.get("estate"),
            row.get("home_division_code"),
        )
        for row in mapping_rows
    )
    mapping_keys = set(mapping_counts)

    duplicate_keys = {
        key
        for key, count in mapping_counts.items()
        if count > 1
    }
    missing_keys = source_keys - mapping_keys
    extra_keys = mapping_keys - source_keys

    allowed_divisions_by_estate: dict[str, dict[str, str]] = (
        defaultdict(dict)
    )
    for row in source_rows:
        estate_key = canonical(row.get("estate"))
        division = clean(row.get("division"))
        allowed_divisions_by_estate[estate_key][
            canonical(division)
        ] = division

    failures: list[dict[str, Any]] = []
    confirmed_lookup: dict[
        tuple[str, str],
        dict[str, str],
    ] = {}

    for row in mapping_rows:
        key = mapping_key(
            row.get("estate"),
            row.get("home_division_code"),
        )
        estate_key = key[0]
        confirmed_name = clean(
            row.get("confirmed_division_name")
        )
        reasons: list[str] = []

        if key in duplicate_keys:
            reasons.append("DUPLICATE_MAPPING_KEY")

        if not yes(row.get("manager_confirmed")):
            reasons.append("MANAGER_CONFIRMATION_REQUIRED")

        if not confirmed_name:
            reasons.append("CONFIRMED_DIVISION_NAME_REQUIRED")
        elif canonical(confirmed_name) not in (
            allowed_divisions_by_estate.get(
                estate_key,
                {},
            )
        ):
            reasons.append(
                "CONFIRMED_DIVISION_NOT_FOUND_IN_ESTATE"
            )

        if not clean(row.get("reviewer_name")):
            reasons.append("REVIEWER_NAME_REQUIRED")

        if not clean(row.get("reviewed_at")):
            reasons.append("REVIEWED_AT_REQUIRED")

        if not no(row.get("live_assignment_authorized")):
            reasons.append(
                "LIVE_ASSIGNMENT_AUTHORIZED_MUST_REMAIN_NO"
            )

        if reasons:
            failures.append({
                "estate": row.get("estate", ""),
                "home_division_code": row.get(
                    "home_division_code",
                    "",
                ),
                "confirmed_division_name": confirmed_name,
                "failure_reasons": "|".join(reasons),
            })
        else:
            canonical_name = canonical(confirmed_name)
            confirmed_lookup[key] = {
                "confirmed_division_name": (
                    allowed_divisions_by_estate[
                        estate_key
                    ][canonical_name]
                ),
                "reviewer_name": clean(
                    row.get("reviewer_name")
                ),
                "reviewed_at": clean(row.get("reviewed_at")),
                "comments": clean(row.get("comments")),
            }

    for key in sorted(missing_keys):
        failures.append({
            "estate": key[0],
            "home_division_code": key[1],
            "confirmed_division_name": "",
            "failure_reasons": "MISSING_MAPPING_KEY",
        })

    for key in sorted(extra_keys):
        failures.append({
            "estate": key[0],
            "home_division_code": key[1],
            "confirmed_division_name": "",
            "failure_reasons": "EXTRA_MAPPING_KEY",
        })

    quality_dir = run_folder / "quality"
    allocation_dir = run_folder / "allocation"
    summary_dir = run_folder / "summary"
    quality_dir.mkdir(exist_ok=True)
    allocation_dir.mkdir(exist_ok=True)
    summary_dir.mkdir(exist_ok=True)

    write_csv(
        quality_dir
        / "division_mapping_validation_failures.csv",
        failures,
        [
            "estate",
            "home_division_code",
            "confirmed_division_name",
            "failure_reasons",
        ],
    )

    normalized_rows: list[dict[str, Any]] = []
    duplicate_assignment_failures: list[dict[str, Any]] = []

    review_complete = (
        not failures
        and not duplicate_keys
        and not missing_keys
        and not extra_keys
        and len(confirmed_lookup) == len(source_keys)
    )

    if review_complete:
        for source in source_rows:
            key = mapping_key(
                source.get("estate"),
                source.get("inferred_home_division"),
            )
            mapping = confirmed_lookup[key]
            normalized_home = mapping[
                "confirmed_division_name"
            ]
            normalized_cross = (
                "NO"
                if canonical(normalized_home)
                == canonical(source.get("division"))
                else "YES"
            )

            row = dict(source)
            row.update({
                "normalized_home_division": normalized_home,
                "normalized_cross_division": normalized_cross,
                "division_mapping_confirmed": "YES",
                "division_mapping_reviewer": mapping[
                    "reviewer_name"
                ],
                "division_mapping_reviewed_at": mapping[
                    "reviewed_at"
                ],
                "division_mapping_comments": mapping["comments"],
                "actual_supervisor_verified": "NO",
                "attendance_verified": "NO",
                "approved_leave_verified": "NO",
                "fitness_verified": "NO",
                "movement_restrictions_verified": "NO",
                "operational_use_allowed": "NO",
                "live_assignment_authorized": "NO",
                "allocation_status": (
                    "NORMALIZED_SIMULATION_ALLOCATION_FOR_REVIEW"
                ),
            })
            normalized_rows.append(row)

        assignment_counts = Counter(
            allocation_employee_key(row)
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

        normalized_fields = list(normalized_rows[0].keys())
        write_csv(
            allocation_dir
            / "expected_primary_named_plucker_allocation.csv",
            expected_rows,
            normalized_fields,
        )
        write_csv(
            allocation_dir
            / "conservative_backup_named_plucker_allocation.csv",
            conservative_rows,
            normalized_fields,
        )
        write_csv(
            allocation_dir
            / "all_normalized_named_plucker_allocations.csv",
            normalized_rows,
            normalized_fields,
        )

        movement_groups: dict[
            tuple[str, str],
            Counter[str],
        ] = defaultdict(Counter)

        for row in normalized_rows:
            group_key = (
                clean(row.get("estate")),
                upper(row.get("scenario")),
            )
            movement_groups[group_key][
                upper(row.get("normalized_cross_division"))
            ] += 1

        movement_summary = []
        for key in sorted(
            movement_groups,
            key=lambda value: (
                value[0].lower(),
                value[1],
            ),
        ):
            counts = movement_groups[key]
            total = counts["YES"] + counts["NO"]
            movement_summary.append({
                "estate": key[0],
                "scenario": key[1],
                "assignment_rows": total,
                "same_division_rows": counts["NO"],
                "cross_division_rows": counts["YES"],
                "cross_division_rate_pct": (
                    round(
                        100.0 * counts["YES"] / total,
                        2,
                    )
                    if total
                    else 0.0
                ),
                "operational_use_allowed": "NO",
                "live_assignment_authorized": "NO",
            })

        write_csv(
            summary_dir
            / "estate_scenario_normalized_movement_summary.csv",
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
        for row in mapping_rows
    ) and all(
        no(row.get("live_assignment_authorized"))
        for row in normalized_rows
    )

    final_pass = (
        review_complete
        and not duplicate_assignment_failures
        and len(normalized_rows) == len(source_rows)
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
            "check": "MAPPING_REVIEW_ROWS",
            "value": len(mapping_rows),
            "required": len(source_keys),
            "status": (
                "PASS"
                if len(mapping_rows) == len(source_keys)
                else "FAIL"
            ),
        },
        {
            "check": "DUPLICATE_MAPPING_KEYS",
            "value": len(duplicate_keys),
            "required": 0,
            "status": (
                "PASS" if not duplicate_keys else "FAIL"
            ),
        },
        {
            "check": "MISSING_MAPPING_KEYS",
            "value": len(missing_keys),
            "required": 0,
            "status": (
                "PASS" if not missing_keys else "FAIL"
            ),
        },
        {
            "check": "EXTRA_MAPPING_KEYS",
            "value": len(extra_keys),
            "required": 0,
            "status": (
                "PASS" if not extra_keys else "FAIL"
            ),
        },
        {
            "check": "MAPPING_VALIDATION_FAILURES",
            "value": len(failures),
            "required": 0,
            "status": (
                "PASS" if not failures else "FAIL"
            ),
        },
        {
            "check": "NORMALIZED_ALLOCATION_ROWS",
            "value": len(normalized_rows),
            "required": len(source_rows),
            "status": (
                "PASS"
                if len(normalized_rows) == len(source_rows)
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
            "check": "LIVE_ASSIGNMENT_FLAGS_ALL_NO",
            "value": all_live_flags_no,
            "required": True,
            "status": (
                "PASS" if all_live_flags_no else "FAIL"
            ),
        },
    ]
    write_csv(
        quality_dir / "division_normalization_gate.csv",
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
        "source_allocation_rows": len(source_rows),
        "mapping_review_rows": len(mapping_rows),
        "source_mapping_keys": len(source_keys),
        "confirmed_mapping_rows": len(confirmed_lookup),
        "mapping_validation_failures": len(failures),
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
            else "DIVISION_MAPPING_INPUT_OR_CORRECTION_REQUIRED"
        ),
        "manager_review_started": any(
            yes(row.get("manager_confirmed"))
            for row in mapping_rows
        ),
        "manager_review_completed": final_pass,
        "operational_status": (
            "NORMALIZED_ALLOCATION_REVIEW_ONLY"
        ),
        "live_deployment_started": False,
        "important_interpretation": [
            (
                "A passing mapping gate confirms division identity "
                "normalization only."
            ),
            (
                "It does not verify attendance, leave, fitness, "
                "movement permission or live employee availability."
            ),
            (
                "The EXPECTED file is the primary review scenario and "
                "the CONSERVATIVE file is the backup review scenario."
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
    print("DIVISION IDENTITY NORMALIZATION VALIDATION FINISHED")
    print(json.dumps(validation_summary, indent=2))
    return 0


def self_test() -> int:
    test_root = Path.cwd() / "_v1302_self_test_temp"
    if test_root.exists():
        shutil.rmtree(test_root)

    source_path = test_root / "source.csv"
    output_root = test_root / "runs"
    source_path.parent.mkdir(parents=True)

    rows = []
    estates = [
        ("EstateA", ["Lower", "Upper"], ["LD", "UD"]),
        ("EstateB", ["Alpha", "Beta"], ["AD", "BD"]),
    ]
    employee_number = 1

    for estate, divisions, codes in estates:
        for scenario in ("EXPECTED", "CONSERVATIVE"):
            for division, code in zip(divisions, codes):
                rows.append({
                    "allocation_date": "2026-07-24",
                    "scenario": scenario,
                    "estate": estate,
                    "division": division,
                    "field": f"{division}-F1",
                    "employee_key": (
                        f"{estate}|EMP-{employee_number:03d}"
                    ),
                    "employee_id": f"EMP-{employee_number:03d}",
                    "field_crop_kg": "100",
                    "plucker_capacity_kg": "20",
                    "field_assigned_capacity_kg": "100",
                    "field_under_kg": "0",
                    "field_over_kg": "0",
                    "candidate_scope": "SAME_DIVISION",
                    "cross_division": "YES",
                    "inferred_home_division": code,
                    "solver_status": "OPTIMAL",
                    "source_assignment_method": "CP_SAT_BASELINE",
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
                })
                employee_number += 1

    write_csv(source_path, rows, list(rows[0].keys()))
    prepare_review_pack(source_path, output_root)

    pointer = (
        output_root
        / "LATEST_DIVISION_IDENTITY_NORMALIZATION_V1302_RUN.txt"
    )
    run_folder = Path(
        pointer.read_text(encoding="utf-8").strip()
    )
    mapping_path = (
        run_folder
        / "review_input"
        / "division_identity_mapping_review.csv"
    )
    mapping_rows = read_csv(mapping_path)

    for row in mapping_rows:
        row["confirmed_division_name"] = row[
            "suggested_division_name"
        ]
        row["manager_confirmed"] = "YES"
        row["reviewer_name"] = "SELF TEST"
        row["reviewed_at"] = "2026-07-24 15:30"
        row["live_assignment_authorized"] = "NO"

    write_csv(
        mapping_path,
        mapping_rows,
        list(mapping_rows[0].keys()),
    )
    validate_mapping_run(run_folder)

    validation = json.loads(
        (run_folder / "validation_summary.json").read_text(
            encoding="utf-8"
        )
    )

    if validation["mapping_validation_failures"] != 0:
        raise RuntimeError("Mapping self-test failed.")
    if validation["normalized_allocation_rows"] != len(rows):
        raise RuntimeError(
            "Normalized row-count self-test failed."
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
    parser.add_argument("--source-allocation")
    parser.add_argument("--validate-run")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    if args.validate_run:
        return validate_mapping_run(
            Path(args.validate_run).resolve()
        )

    if not args.output_root:
        raise SystemExit("--output-root is required.")

    if args.source_allocation:
        source_path = Path(
            args.source_allocation
        ).resolve()
    else:
        if not args.project_root:
            raise SystemExit(
                "--project-root is required when "
                "--source-allocation is omitted."
            )
        source_path = discover_source_allocation(
            Path(args.project_root).resolve()
        )

    return prepare_review_pack(
        source_path,
        Path(args.output_root).resolve(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
