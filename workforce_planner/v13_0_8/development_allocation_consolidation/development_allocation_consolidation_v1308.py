from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


VERSION = "13.0.8"
CREATION_STATUS = (
    "PASS_DEVELOPMENT_ALLOCATION_CONSOLIDATION_OUTPUTS"
)


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def upper(value: Any) -> str:
    return clean(value).upper()


def canonical(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", upper(value))


ESTATE_ALIASES = {
    "BAMBRAKELLY": "BAMBARAKELLY",
    "EILDONHALL": "EILDONHALL",
    "GLASSAUGH": "GLASSUGH",
    "GREATWESTERN": "GREATWESTERN",
    "NUWARAELIYA": "NUWARAELIYA",
    "OILPHANT": "OLIPHANT",
    "UDARADELLA": "UDARADELLA",
}


def estate_key(value: Any) -> str:
    key = canonical(value)
    return ESTATE_ALIASES.get(key, key)


def as_float(value: Any) -> float:
    text = clean(value)
    if not text:
        return 0.0
    try:
        number = float(text)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


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


def discover_v1306_source(
    project_root: Path,
) -> tuple[Path, Path, str]:
    run_root = (
        project_root
        / "workforce_planner"
        / "v13_0_6"
        / "rare_cross_division_exception_runs"
    )
    pointer = (
        run_root
        / "LATEST_RARE_CROSS_DIVISION_EXCEPTION_V1306_RUN.txt"
    )
    if not pointer.exists():
        raise SystemExit(
            "No latest v13.0.6 run pointer was found."
        )

    run_folder = Path(
        clean(pointer.read_text(encoding="utf-8"))
    )
    review_path = (
        run_folder
        / "review_input"
        / "employee_capacity_and_cross_division_exception_review.csv"
    )
    validation_path = run_folder / "validation_summary.json"

    if not review_path.exists():
        raise SystemExit(
            f"The v13.0.6 review file is missing: {review_path}"
        )
    if not validation_path.exists():
        raise SystemExit(
            "The v13.0.6 validation summary is missing."
        )

    validation = json.loads(
        validation_path.read_text(encoding="utf-8")
    )
    if int(validation.get("validation_failures", -1)) != 0:
        raise SystemExit(
            "v13.0.6 still has validation failures."
        )
    if bool(validation.get("live_deployment_started", True)):
        raise SystemExit(
            "Unexpected live-deployment flag in v13.0.6."
        )

    return review_path, validation_path, str(run_folder)


def consolidate(
    allocation_path: Path,
    validation_path: Path,
    field_reference_path: Path,
    home_context_path: Path,
    home_exception_path: Path,
    output_root: Path,
    source_run: str,
) -> int:
    allocations = read_csv(allocation_path)
    field_reference = read_csv(field_reference_path)
    home_context = read_csv(home_context_path)
    home_exceptions = read_csv(home_exception_path)

    if not allocations:
        raise SystemExit("The allocation source is empty.")

    required = {
        "allocation_date",
        "scenario",
        "estate",
        "employee_key",
        "employee_id",
        "allocation_division_context",
        "field",
        "employee_home_division_code",
        "employee_daily_capacity_kg",
        "employee_field_allocated_capacity_kg",
        "cross_division_exception",
        "review_status",
        "employee_home_code_verified",
        "attendance_verified",
        "approved_leave_verified",
        "fitness_verified",
        "movement_restrictions_verified",
        "operational_use_allowed",
        "live_assignment_authorized",
    }
    missing = required - set(allocations[0])
    if missing:
        raise SystemExit(
            "Allocation source is missing columns: "
            + ", ".join(sorted(missing))
        )

    validation = json.loads(
        validation_path.read_text(encoding="utf-8")
    )
    if int(validation.get("validation_failures", -1)) != 0:
        raise SystemExit(
            "The v13.0.6 validation gate is not clear."
        )

    field_lookup = {
        (
            estate_key(row.get("estate")),
            canonical(
                row.get("allocation_division_context")
            ),
            canonical(row.get("field")),
        ): row
        for row in field_reference
    }
    home_lookup = {
        (
            estate_key(row.get("estate")),
            canonical(
                row.get("observed_employee_home_code")
            ),
        ): row
        for row in home_context
    }
    employee_exception_keys = {
        (
            estate_key(row.get("estate")),
            canonical(row.get("employee_id")),
            canonical(
                row.get("observed_employee_home_code")
            ),
        )
        for row in home_exceptions
    }

    consolidated = []

    for source in allocations:
        field_ref = field_lookup.get(
            (
                estate_key(source.get("estate")),
                canonical(
                    source.get("allocation_division_context")
                ),
                canonical(source.get("field")),
            ),
            {},
        )
        home_ref = home_lookup.get(
            (
                estate_key(source.get("estate")),
                canonical(
                    source.get("employee_home_division_code")
                ),
            ),
            {},
        )
        employee_exception = (
            (
                estate_key(source.get("estate")),
                canonical(source.get("employee_id")),
                canonical(
                    source.get("employee_home_division_code")
                ),
            )
            in employee_exception_keys
        )

        official_code = clean(
            field_ref.get("official_assigned_division_code")
        )

        consolidated.append({
            "allocation_date": clean(
                source.get("allocation_date")
            ),
            "scenario": upper(source.get("scenario")),
            "estate": clean(source.get("estate")),
            "employee_key": clean(
                source.get("employee_key")
            ),
            "employee_id": clean(
                source.get("employee_id")
            ),
            "allocation_division_context": clean(
                source.get("allocation_division_context")
            ),
            "field": clean(source.get("field")),
            "official_assigned_division_code": official_code,
            "field_code_reference_status": (
                clean(field_ref.get("evidence_status"))
                if official_code
                else "UNRESOLVED"
            ),
            "employee_home_division_code_observed": clean(
                source.get("employee_home_division_code")
            ),
            "home_code_review_class": clean(
                home_ref.get("suggestion_type")
            ),
            "candidate_home_division_codes": clean(
                home_ref.get(
                    "candidate_official_division_codes"
                )
            ),
            "employee_home_code_exception": (
                "YES" if employee_exception else "NO"
            ),
            "employee_daily_capacity_kg": as_float(
                source.get("employee_daily_capacity_kg")
            ),
            "employee_field_allocated_capacity_kg": as_float(
                source.get(
                    "employee_field_allocated_capacity_kg"
                )
            ),
            "cross_division_exception": upper(
                source.get("cross_division_exception")
            ),
            "source_review_status": clean(
                source.get("review_status")
            ),
            "capacity_validation_status": "PASS_V13_0_6",
            "employee_home_code_verified": "NO",
            "attendance_verified": "NO",
            "approved_leave_verified": "NO",
            "fitness_verified": "NO",
            "movement_restrictions_verified": "NO",
            "operational_use_allowed": "NO",
            "live_assignment_authorized": "NO",
            "development_allocation_status": (
                "MANAGEMENT_SIMULATION_REVIEW_ONLY"
            ),
        })

    exact_keys = Counter(
        (
            row["allocation_date"],
            row["scenario"],
            estate_key(row["estate"]),
            canonical(row["employee_id"]),
            canonical(row["allocation_division_context"]),
            canonical(row["field"]),
        )
        for row in consolidated
    )
    duplicate_failures = sum(
        count > 1 for count in exact_keys.values()
    )
    safety_failures = sum(
        any(
            row[field] != "NO"
            for field in [
                "employee_home_code_verified",
                "attendance_verified",
                "approved_leave_verified",
                "fitness_verified",
                "movement_restrictions_verified",
                "operational_use_allowed",
                "live_assignment_authorized",
            ]
        )
        for row in consolidated
    )

    run_folder = (
        output_root
        / datetime.now().strftime(
            "development_allocation_%Y%m%d_%H%M%S"
        )
    )
    allocation_dir = run_folder / "allocation"
    summary_dir = run_folder / "summary"
    quality_dir = run_folder / "quality"
    estate_dir = allocation_dir / "estate_scenario"

    for folder in (
        allocation_dir,
        summary_dir,
        quality_dir,
        estate_dir,
    ):
        folder.mkdir(parents=True, exist_ok=True)

    fields = list(consolidated[0].keys())

    write_csv(
        allocation_dir
        / "all_development_allocation.csv",
        consolidated,
        fields,
    )

    expected_rows = [
        row
        for row in consolidated
        if row["scenario"] == "EXPECTED"
    ]
    conservative_rows = [
        row
        for row in consolidated
        if row["scenario"] == "CONSERVATIVE"
    ]

    write_csv(
        allocation_dir
        / "expected_primary_development_allocation.csv",
        expected_rows,
        fields,
    )
    write_csv(
        allocation_dir
        / "conservative_backup_development_allocation.csv",
        conservative_rows,
        fields,
    )

    estate_scenario_groups = defaultdict(list)
    for row in consolidated:
        estate_scenario_groups[
            (row["estate"], row["scenario"])
        ].append(row)

    for (estate, scenario), rows in estate_scenario_groups.items():
        safe_estate = re.sub(
            r"[^A-Za-z0-9_-]+",
            "_",
            estate.strip(),
        ).strip("_")
        write_csv(
            estate_dir
            / f"{safe_estate}_{scenario.lower()}_allocation.csv",
            rows,
            fields,
        )

    scenario_summary = []
    for scenario in ("EXPECTED", "CONSERVATIVE"):
        rows = [
            row
            for row in consolidated
            if row["scenario"] == scenario
        ]
        coded = sum(
            row["official_assigned_division_code"] != ""
            for row in rows
        )
        home_exc = sum(
            row["employee_home_code_exception"] == "YES"
            for row in rows
        )
        scenario_summary.append({
            "scenario": scenario,
            "assignment_rows": len(rows),
            "unique_employee_keys": len(
                {row["employee_key"] for row in rows}
            ),
            "allocated_capacity_kg": round(
                sum(
                    row[
                        "employee_field_allocated_capacity_kg"
                    ]
                    for row in rows
                ),
                4,
            ),
            "official_field_code_rows": coded,
            "official_field_code_coverage_pct": round(
                coded * 100.0 / len(rows),
                4,
            ) if rows else 0.0,
            "home_code_exception_rows": home_exc,
            "home_code_exception_pct": round(
                home_exc * 100.0 / len(rows),
                4,
            ) if rows else 0.0,
            "cross_division_exception_rows": sum(
                row["cross_division_exception"] == "YES"
                for row in rows
            ),
            "operational_use_allowed": "NO",
            "live_assignment_authorized": "NO",
        })

    write_csv(
        summary_dir / "scenario_summary.csv",
        scenario_summary,
        list(scenario_summary[0].keys()),
    )

    estate_summary = []
    for (estate, scenario), rows in sorted(
        estate_scenario_groups.items(),
        key=lambda item: (
            item[0][0].lower(),
            item[0][1],
        ),
    ):
        coded = sum(
            row["official_assigned_division_code"] != ""
            for row in rows
        )
        home_exc = sum(
            row["employee_home_code_exception"] == "YES"
            for row in rows
        )
        estate_summary.append({
            "estate": estate,
            "scenario": scenario,
            "assignment_rows": len(rows),
            "unique_employee_keys": len(
                {row["employee_key"] for row in rows}
            ),
            "allocated_capacity_kg": round(
                sum(
                    row[
                        "employee_field_allocated_capacity_kg"
                    ]
                    for row in rows
                ),
                4,
            ),
            "official_field_code_rows": coded,
            "unresolved_field_code_rows": len(rows) - coded,
            "official_field_code_coverage_pct": round(
                coded * 100.0 / len(rows),
                4,
            ) if rows else 0.0,
            "home_code_exception_rows": home_exc,
            "home_code_exception_pct": round(
                home_exc * 100.0 / len(rows),
                4,
            ) if rows else 0.0,
            "cross_division_exception_rows": sum(
                row["cross_division_exception"] == "YES"
                for row in rows
            ),
            "development_gate": (
                "MANAGEMENT_SIMULATION_REVIEW_ONLY"
            ),
        })

    write_csv(
        summary_dir / "estate_scenario_summary.csv",
        estate_summary,
        list(estate_summary[0].keys()),
    )

    exception_rows = [
        row
        for row in consolidated
        if (
            not row["official_assigned_division_code"]
            or row["employee_home_code_exception"] == "YES"
            or row["cross_division_exception"] == "YES"
        )
    ]
    write_csv(
        quality_dir / "development_review_exceptions.csv",
        exception_rows,
        fields,
    )

    gate_rows = [
        {
            "check": "SOURCE_V13_0_6_VALIDATION_FAILURES",
            "value": int(
                validation.get("validation_failures", -1)
            ),
            "required": 0,
            "status": "PASS",
        },
        {
            "check": "ALLOCATION_ROWS",
            "value": len(consolidated),
            "required": 15014,
            "status": (
                "PASS"
                if len(consolidated) == 15014
                else "FAIL"
            ),
        },
        {
            "check": "EXPECTED_PRIMARY_ROWS",
            "value": len(expected_rows),
            "required": 6101,
            "status": (
                "PASS"
                if len(expected_rows) == 6101
                else "FAIL"
            ),
        },
        {
            "check": "CONSERVATIVE_BACKUP_ROWS",
            "value": len(conservative_rows),
            "required": 8913,
            "status": (
                "PASS"
                if len(conservative_rows) == 8913
                else "FAIL"
            ),
        },
        {
            "check": "EXACT_DUPLICATE_ASSIGNMENTS",
            "value": duplicate_failures,
            "required": 0,
            "status": (
                "PASS"
                if duplicate_failures == 0
                else "FAIL"
            ),
        },
        {
            "check": "SAFETY_CONTROL_FAILURES",
            "value": safety_failures,
            "required": 0,
            "status": (
                "PASS"
                if safety_failures == 0
                else "FAIL"
            ),
        },
        {
            "check": "OFFICIAL_FIELD_CODE_UNRESOLVED_ROWS",
            "value": sum(
                not row["official_assigned_division_code"]
                for row in consolidated
            ),
            "required": 0,
            "status": "OPEN_REVIEW_EXCEPTION",
        },
        {
            "check": "HOME_CODE_EXCEPTION_ASSIGNMENT_ROWS",
            "value": sum(
                row["employee_home_code_exception"] == "YES"
                for row in consolidated
            ),
            "required": 0,
            "status": "OPEN_REVIEW_EXCEPTION",
        },
        {
            "check": "LIVE_DEPLOYMENT_STARTED",
            "value": False,
            "required": False,
            "status": "PASS",
        },
    ]
    write_csv(
        quality_dir / "development_allocation_gate.csv",
        gate_rows,
        ["check", "value", "required", "status"],
    )

    summary = {
        "status": CREATION_STATUS,
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "source_run": source_run,
        "source_allocation_path": str(allocation_path),
        "source_validation_path": str(validation_path),
        "allocation_rows": len(consolidated),
        "expected_primary_rows": len(expected_rows),
        "conservative_backup_rows": len(
            conservative_rows
        ),
        "estate_count": len(
            {row["estate"] for row in consolidated}
        ),
        "official_field_code_rows": sum(
            row["official_assigned_division_code"] != ""
            for row in consolidated
        ),
        "official_field_code_unresolved_rows": sum(
            not row["official_assigned_division_code"]
            for row in consolidated
        ),
        "home_code_exception_assignment_rows": sum(
            row["employee_home_code_exception"] == "YES"
            for row in consolidated
        ),
        "home_code_exception_employees": len(
            {
                (
                    row["estate"],
                    row["employee_id"],
                    row[
                        "employee_home_division_code_observed"
                    ],
                )
                for row in consolidated
                if row["employee_home_code_exception"]
                == "YES"
            }
        ),
        "cross_division_exception_rows": sum(
            row["cross_division_exception"] == "YES"
            for row in consolidated
        ),
        "duplicate_assignment_failures": duplicate_failures,
        "safety_control_failures": safety_failures,
        "review_gate": (
            "READY_FOR_MANAGEMENT_SIMULATION_REVIEW_"
            "WITH_OPEN_HOME_CODE_EXCEPTIONS"
        ),
        "employee_home_code_verification_completed": False,
        "operational_status": (
            "DEVELOPMENT_ALLOCATION_MANAGEMENT_REVIEW_ONLY"
        ),
        "live_deployment_started": False,
        "important_interpretation": [
            (
                "The project continues without treating blank "
                "supervisor fields as verified facts."
            ),
            (
                "Official assigned division codes are included as "
                "development references only."
            ),
            (
                "Unresolved assigned-field contexts and employee "
                "home-code exceptions remain visibly flagged."
            ),
            (
                "No payroll connection, employee notification or "
                "live field allocation is authorized."
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
        / "LATEST_DEVELOPMENT_ALLOCATION_V1308_RUN.txt"
    ).write_text(str(run_folder), encoding="utf-8")

    print("")
    print("DEVELOPMENT ALLOCATION CONSOLIDATION FINISHED")
    print(json.dumps(summary, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root")
    parser.add_argument("--output-root")
    parser.add_argument("--allocation-path")
    parser.add_argument("--validation-path")
    parser.add_argument("--source-run", default="")
    parser.add_argument("--field-reference", required=True)
    parser.add_argument("--home-context", required=True)
    parser.add_argument("--home-exceptions", required=True)
    args = parser.parse_args()

    if not args.output_root:
        raise SystemExit("--output-root is required.")

    if args.allocation_path and args.validation_path:
        allocation_path = Path(
            args.allocation_path
        ).resolve()
        validation_path = Path(
            args.validation_path
        ).resolve()
        source_run = args.source_run
    else:
        if not args.project_root:
            raise SystemExit(
                "--project-root is required when source paths "
                "are omitted."
            )
        (
            allocation_path,
            validation_path,
            source_run,
        ) = discover_v1306_source(
            Path(args.project_root).resolve()
        )

    return consolidate(
        allocation_path,
        validation_path,
        Path(args.field_reference).resolve(),
        Path(args.home_context).resolve(),
        Path(args.home_exceptions).resolve(),
        Path(args.output_root).resolve(),
        source_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
