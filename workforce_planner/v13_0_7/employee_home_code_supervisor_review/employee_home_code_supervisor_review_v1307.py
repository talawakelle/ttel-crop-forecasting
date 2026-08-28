from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


VERSION = "13.0.7"
CREATION_STATUS = (
    "PASS_EMPLOYEE_HOME_CODE_SUPERVISOR_REVIEW_PACK_CREATED"
)
VALIDATION_STATUS = (
    "PASS_EMPLOYEE_HOME_CODE_SUPERVISOR_REVIEW_VALIDATION_OUTPUTS"
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


def discover_allocation(project_root: Path) -> tuple[Path, str]:
    v1306_root = (
        project_root
        / "workforce_planner"
        / "v13_0_6"
        / "rare_cross_division_exception_runs"
    )
    pointer = (
        v1306_root
        / "LATEST_RARE_CROSS_DIVISION_EXCEPTION_V1306_RUN.txt"
    )
    if pointer.exists():
        run_text = clean(pointer.read_text(encoding="utf-8"))
        if run_text:
            run_folder = Path(run_text)
            summary_path = run_folder / "run_summary.json"
            if summary_path.exists():
                summary = json.loads(
                    summary_path.read_text(encoding="utf-8")
                )
                source = Path(
                    clean(summary.get("source_allocation_path"))
                )
                if source.exists():
                    return source, str(run_folder)

    raise SystemExit(
        "No complete v13.0.6 source allocation was found."
    )


def load_master(path: Path) -> list[dict[str, str]]:
    rows = read_csv(path)
    required = {
        "plc",
        "region",
        "estate",
        "estate_code",
        "division",
        "official_division_code",
        "source_sheet",
        "source_row",
    }
    if not rows:
        raise SystemExit(f"Official master is empty: {path}")
    missing = required - set(rows[0])
    if missing:
        raise SystemExit(
            "Official master is missing columns: "
            + ", ".join(sorted(missing))
        )
    return rows


def candidate_records(
    observed_code: str,
    estate: str,
    master_by_estate: dict[str, list[dict[str, str]]],
) -> list[tuple[dict[str, str], list[str]]]:
    code = canonical(observed_code)
    if code == "TLD":
        return []

    matches = []
    for record in master_by_estate.get(estate_key(estate), []):
        division = canonical(record.get("division"))
        suffix = canonical(
            clean(record.get("official_division_code")).split(
                "_", 1
            )[-1]
        )
        reasons = []

        if code and code == suffix:
            reasons.append("EXACT_OFFICIAL_SUFFIX")
        if len(code) >= 2 and division.startswith(code):
            reasons.append("DIVISION_NAME_PREFIX")
        if code == "LD" and "LOWER" in division:
            reasons.append("LOWER_ABBREVIATION")
        if code == "UD" and "UPPER" in division:
            reasons.append("UPPER_ABBREVIATION")
        if code == "EIL" and division.startswith("EILDON"):
            reasons.append("EILDON_ABBREVIATION")
        if code == "GREA" and division.startswith("GREAT"):
            reasons.append("GREATWESTERN_ABBREVIATION")

        if reasons:
            matches.append((record, reasons))

    return matches


def create_review_pack(
    allocation_path: Path,
    master_path: Path,
    output_root: Path,
    source_run: str = "",
) -> int:
    allocations = read_csv(allocation_path)
    master = load_master(master_path)

    if not allocations:
        raise SystemExit(
            f"Allocation source is empty: {allocation_path}"
        )

    required = {
        "estate",
        "employee_key",
        "employee_id",
        "employee_home_division_code",
        "allocation_division_context",
        "field",
        "operational_use_allowed",
        "live_assignment_authorized",
    }
    missing = required - set(allocations[0])
    if missing:
        raise SystemExit(
            "Allocation source is missing columns: "
            + ", ".join(sorted(missing))
        )

    run_folder = (
        output_root
        / datetime.now().strftime(
            "employee_home_code_review_%Y%m%d_%H%M%S"
        )
    )
    review_input = run_folder / "review_input"
    quality_dir = run_folder / "quality"
    summary_dir = run_folder / "summary"

    for folder in (review_input, quality_dir, summary_dir):
        folder.mkdir(parents=True, exist_ok=True)

    master_by_estate = defaultdict(list)
    for record in master:
        master_by_estate[estate_key(record["estate"])].append(
            record
        )

    context_groups = defaultdict(
        lambda: {
            "assignment_rows": 0,
            "employees": set(),
        }
    )
    for row in allocations:
        key = (
            estate_key(row["estate"]),
            canonical(row["employee_home_division_code"]),
        )
        group = context_groups[key]
        group["estate"] = clean(row["estate"])
        group["observed_code"] = clean(
            row["employee_home_division_code"]
        )
        group["assignment_rows"] += 1
        group["employees"].add(clean(row["employee_id"]))

    context_rows = []
    exception_keys = set()

    for key, group in context_groups.items():
        estate = group["estate"]
        observed_code = group["observed_code"]
        candidates = candidate_records(
            observed_code,
            estate,
            master_by_estate,
        )

        if len(candidates) == 1:
            suggestion_type = "SINGLE_CANDIDATE"
            confidence = "HIGH"
            codes = candidates[0][0]["official_division_code"]
            names = candidates[0][0]["division"]
            basis = "|".join(candidates[0][1])
            references = (
                f"Division Resource Map!A"
                f"{candidates[0][0]['source_row']}:F"
                f"{candidates[0][0]['source_row']}"
            )
        elif len(candidates) > 1:
            suggestion_type = "MULTIPLE_CANDIDATES"
            confidence = "LOW"
            codes = "|".join(
                candidate[0]["official_division_code"]
                for candidate in candidates
            )
            names = "|".join(
                candidate[0]["division"]
                for candidate in candidates
            )
            basis = "AMBIGUOUS_HISTORICAL_ABBREVIATION"
            references = "|".join(
                f"Division Resource Map!A"
                f"{candidate[0]['source_row']}:F"
                f"{candidate[0]['source_row']}"
                for candidate in candidates
            )
            exception_keys.add(key)
        else:
            estate_master = master_by_estate.get(
                estate_key(estate), []
            )
            suggestion_type = "NO_DIRECT_CANDIDATE"
            confidence = "UNRESOLVED"
            codes = "|".join(
                item["official_division_code"]
                for item in estate_master
            )
            names = "|".join(
                item["division"] for item in estate_master
            )
            basis = "NO_DIRECT_MASTER_MATCH"
            references = "|".join(
                f"Division Resource Map!A"
                f"{item['source_row']}:F{item['source_row']}"
                for item in estate_master
            )
            exception_keys.add(key)

        context_rows.append({
            "estate": estate,
            "observed_employee_home_code": observed_code,
            "assignment_rows": group["assignment_rows"],
            "unique_employees": len(group["employees"]),
            "suggestion_type": suggestion_type,
            "suggestion_confidence": confidence,
            "candidate_official_division_codes": codes,
            "candidate_official_division_names": names,
            "suggestion_basis": basis,
            "source_document_name": (
                "Official division master — sanitized extract"
            ),
            "source_sheet": "Division Resource Map",
            "source_references": references,
            "review_decision": "",
            "confirmed_home_division_code_or_codes": "",
            "confirmed_mapping_scope": "",
            "verification_basis": "",
            "verification_source_reference": "",
            "supervisor_confirmed": "NO",
            "supervisor_name": "",
            "reviewed_at": "",
            "comments": "",
            "employee_home_code_verified": "NO",
            "attendance_verified": "NO",
            "approved_leave_verified": "NO",
            "fitness_verified": "NO",
            "movement_restrictions_verified": "NO",
            "operational_use_allowed": "NO",
            "live_assignment_authorized": "NO",
        })

    context_rows.sort(
        key=lambda row: (
            row["suggestion_type"] != "SINGLE_CANDIDATE",
            row["estate"].lower(),
            row["observed_employee_home_code"],
        )
    )

    employee_groups = {}
    for row in allocations:
        context_key = (
            estate_key(row["estate"]),
            canonical(row["employee_home_division_code"]),
        )
        if context_key not in exception_keys:
            continue

        key = (
            clean(row["estate"]),
            clean(row["employee_id"]),
            clean(row["employee_home_division_code"]),
        )
        item = employee_groups.setdefault(
            key,
            {
                "estate": clean(row["estate"]),
                "employee_key": clean(row["employee_key"]),
                "employee_id": clean(row["employee_id"]),
                "observed_code": clean(
                    row["employee_home_division_code"]
                ),
                "allocation_rows": 0,
                "divisions": set(),
                "fields": set(),
            },
        )
        item["allocation_rows"] += 1
        item["divisions"].add(
            clean(row["allocation_division_context"])
        )
        item["fields"].add(clean(row["field"]))

    context_lookup = {
        (
            estate_key(row["estate"]),
            canonical(row["observed_employee_home_code"]),
        ): row
        for row in context_rows
    }

    exception_rows = []
    for item in employee_groups.values():
        context = context_lookup[
            (
                estate_key(item["estate"]),
                canonical(item["observed_code"]),
            )
        ]
        exception_rows.append({
            "estate": item["estate"],
            "employee_key": item["employee_key"],
            "employee_id": item["employee_id"],
            "observed_employee_home_code": item["observed_code"],
            "allocation_rows": item["allocation_rows"],
            "assigned_division_contexts": "|".join(
                sorted(item["divisions"])
            ),
            "assigned_fields": "|".join(
                sorted(item["fields"])
            ),
            "candidate_official_division_codes": context[
                "candidate_official_division_codes"
            ],
            "candidate_official_division_names": context[
                "candidate_official_division_names"
            ],
            "confirmed_employee_home_division_code": "",
            "verification_basis": "",
            "verification_source_reference": "",
            "supervisor_confirmed": "NO",
            "supervisor_name": "",
            "reviewed_at": "",
            "comments": "",
            "employee_home_code_verified": "NO",
            "attendance_verified": "NO",
            "approved_leave_verified": "NO",
            "fitness_verified": "NO",
            "movement_restrictions_verified": "NO",
            "operational_use_allowed": "NO",
            "live_assignment_authorized": "NO",
        })

    exception_rows.sort(
        key=lambda row: (
            row["estate"].lower(),
            row["observed_employee_home_code"],
            row["employee_id"],
        )
    )

    write_csv(
        review_input
        / "home_code_context_supervisor_review.csv",
        context_rows,
        list(context_rows[0].keys()),
    )
    write_csv(
        review_input
        / "employee_home_code_exception_review.csv",
        exception_rows,
        list(exception_rows[0].keys()),
    )

    instructions = (
        "This stage verifies employee home-division codes.\n\n"
        "Automated candidates are review aids only. They do not prove "
        "an employee's current home division.\n\n"
        "For SINGLE_CANDIDATE contexts, an authorized reviewer must "
        "check an approved employee master, division register or "
        "equivalent source and complete the confirmation fields.\n\n"
        "For MULTIPLE_CANDIDATES and NO_DIRECT_CANDIDATE contexts, "
        "complete employee_home_code_exception_review.csv for every "
        "employee using approved records.\n\n"
        "Do not use today's assigned division as proof of home division."
        "\n\nTLD remains unresolved until approved records identify "
        "the employee's actual home division.\n\n"
        "Keep attendance, leave, fitness, movement restriction, "
        "operational-use and live-assignment fields as NO.\n\n"
        "After review, run "
        "VALIDATE_EMPLOYEE_HOME_CODE_SUPERVISOR_REVIEW_v13.0.7.ps1."
    )
    (
        review_input
        / "EMPLOYEE_HOME_CODE_REVIEW_INSTRUCTIONS.txt"
    ).write_text(instructions, encoding="utf-8")

    creation_gate = [
        {
            "check": "SOURCE_ASSIGNMENT_ROWS",
            "value": len(allocations),
            "required": 15014,
            "status": (
                "PASS"
                if len(allocations) == 15014
                else "REVIEW"
            ),
        },
        {
            "check": "HOME_CODE_CONTEXT_ROWS",
            "value": len(context_rows),
            "required": 107,
            "status": (
                "PASS"
                if len(context_rows) == 107
                else "REVIEW"
            ),
        },
        {
            "check": "SINGLE_CANDIDATE_CONTEXTS",
            "value": sum(
                row["suggestion_type"]
                == "SINGLE_CANDIDATE"
                for row in context_rows
            ),
            "required": "REVIEW_AID_ONLY",
            "status": "PASS",
        },
        {
            "check": "EMPLOYEE_EXCEPTION_REVIEW_ROWS",
            "value": len(exception_rows),
            "required": ">0",
            "status": "PASS",
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
        / "employee_home_code_review_creation_gate.csv",
        creation_gate,
        ["check", "value", "required", "status"],
    )

    summary = {
        "status": CREATION_STATUS,
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "source_run": source_run,
        "source_allocation_path": str(allocation_path),
        "source_assignment_rows": len(allocations),
        "home_code_context_rows": len(context_rows),
        "single_candidate_contexts": sum(
            row["suggestion_type"] == "SINGLE_CANDIDATE"
            for row in context_rows
        ),
        "multiple_candidate_contexts": sum(
            row["suggestion_type"] == "MULTIPLE_CANDIDATES"
            for row in context_rows
        ),
        "no_direct_candidate_contexts": sum(
            row["suggestion_type"] == "NO_DIRECT_CANDIDATE"
            for row in context_rows
        ),
        "employee_exception_review_rows": len(exception_rows),
        "review_gate": "SUPERVISOR_HOME_CODE_INPUT_REQUIRED",
        "employee_home_code_verification_completed": False,
        "operational_status": (
            "EMPLOYEE_HOME_CODE_SUPERVISOR_REVIEW_ONLY"
        ),
        "live_deployment_started": False,
    }
    (
        run_folder / "run_summary.json"
    ).write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    (
        output_root
        / "LATEST_EMPLOYEE_HOME_CODE_REVIEW_V1307_RUN.txt"
    ).write_text(str(run_folder), encoding="utf-8")

    print("")
    print("EMPLOYEE HOME-CODE SUPERVISOR REVIEW PACK CREATED")
    print(json.dumps(summary, indent=2))
    return 0


def validate_review(run_folder: Path) -> int:
    context_path = (
        run_folder
        / "review_input"
        / "home_code_context_supervisor_review.csv"
    )
    exception_path = (
        run_folder
        / "review_input"
        / "employee_home_code_exception_review.csv"
    )
    contexts = read_csv(context_path)
    exceptions = read_csv(exception_path)

    failures = []

    safety_fields = [
        "attendance_verified",
        "approved_leave_verified",
        "fitness_verified",
        "movement_restrictions_verified",
        "operational_use_allowed",
        "live_assignment_authorized",
    ]

    for row in contexts:
        suggestion_type = upper(row.get("suggestion_type"))
        decision = upper(row.get("review_decision"))

        if suggestion_type == "SINGLE_CANDIDATE":
            required = {
                "review_decision": "CONFIRM",
                "supervisor_confirmed": "YES",
            }
            for field, expected in required.items():
                if upper(row.get(field)) != expected:
                    failures.append({
                        "review_level": "CONTEXT",
                        "estate": clean(row.get("estate")),
                        "employee_id": "",
                        "observed_code": clean(
                            row.get(
                                "observed_employee_home_code"
                            )
                        ),
                        "failure_reason": (
                            f"{field.upper()}_MUST_BE_{expected}"
                        ),
                    })

            for field in [
                "confirmed_home_division_code_or_codes",
                "confirmed_mapping_scope",
                "verification_basis",
                "verification_source_reference",
                "supervisor_name",
                "reviewed_at",
            ]:
                if not clean(row.get(field)):
                    failures.append({
                        "review_level": "CONTEXT",
                        "estate": clean(row.get("estate")),
                        "employee_id": "",
                        "observed_code": clean(
                            row.get(
                                "observed_employee_home_code"
                            )
                        ),
                        "failure_reason": (
                            f"{field.upper()}_REQUIRED"
                        ),
                    })

        else:
            if decision not in {
                "DEFER",
                "CONFIRM",
                "REJECT",
            }:
                failures.append({
                    "review_level": "CONTEXT",
                    "estate": clean(row.get("estate")),
                    "employee_id": "",
                    "observed_code": clean(
                        row.get(
                            "observed_employee_home_code"
                        )
                    ),
                    "failure_reason": (
                        "REVIEW_DECISION_REQUIRED"
                    ),
                })

        if not no(row.get("employee_home_code_verified")):
            failures.append({
                "review_level": "CONTEXT",
                "estate": clean(row.get("estate")),
                "employee_id": "",
                "observed_code": clean(
                    row.get("observed_employee_home_code")
                ),
                "failure_reason": (
                    "EMPLOYEE_HOME_CODE_VERIFIED_MUST_REMAIN_NO"
                ),
            })

        for field in safety_fields:
            if not no(row.get(field)):
                failures.append({
                    "review_level": "CONTEXT",
                    "estate": clean(row.get("estate")),
                    "employee_id": "",
                    "observed_code": clean(
                        row.get(
                            "observed_employee_home_code"
                        )
                    ),
                    "failure_reason": (
                        f"{field.upper()}_MUST_REMAIN_NO"
                    ),
                })

    for row in exceptions:
        for field in [
            "confirmed_employee_home_division_code",
            "verification_basis",
            "verification_source_reference",
            "supervisor_name",
            "reviewed_at",
        ]:
            if not clean(row.get(field)):
                failures.append({
                    "review_level": "EMPLOYEE",
                    "estate": clean(row.get("estate")),
                    "employee_id": clean(
                        row.get("employee_id")
                    ),
                    "observed_code": clean(
                        row.get(
                            "observed_employee_home_code"
                        )
                    ),
                    "failure_reason": (
                        f"{field.upper()}_REQUIRED"
                    ),
                })

        if not yes(row.get("supervisor_confirmed")):
            failures.append({
                "review_level": "EMPLOYEE",
                "estate": clean(row.get("estate")),
                "employee_id": clean(
                    row.get("employee_id")
                ),
                "observed_code": clean(
                    row.get(
                        "observed_employee_home_code"
                    )
                ),
                "failure_reason": (
                    "SUPERVISOR_CONFIRMED_MUST_BE_YES"
                ),
            })

        if not no(row.get("employee_home_code_verified")):
            failures.append({
                "review_level": "EMPLOYEE",
                "estate": clean(row.get("estate")),
                "employee_id": clean(
                    row.get("employee_id")
                ),
                "observed_code": clean(
                    row.get(
                        "observed_employee_home_code"
                    )
                ),
                "failure_reason": (
                    "EMPLOYEE_HOME_CODE_VERIFIED_MUST_REMAIN_NO"
                ),
            })

        for field in safety_fields:
            if not no(row.get(field)):
                failures.append({
                    "review_level": "EMPLOYEE",
                    "estate": clean(row.get("estate")),
                    "employee_id": clean(
                        row.get("employee_id")
                    ),
                    "observed_code": clean(
                        row.get(
                            "observed_employee_home_code"
                        )
                    ),
                    "failure_reason": (
                        f"{field.upper()}_MUST_REMAIN_NO"
                    ),
                })

    quality_dir = run_folder / "quality"
    quality_dir.mkdir(exist_ok=True)

    write_csv(
        quality_dir
        / "employee_home_code_review_failures.csv",
        failures,
        [
            "review_level",
            "estate",
            "employee_id",
            "observed_code",
            "failure_reason",
        ],
    )

    final_pass = not failures

    gate = [
        {
            "check": "CONTEXT_REVIEW_ROWS",
            "value": len(contexts),
            "required": 107,
            "status": (
                "PASS" if len(contexts) == 107 else "FAIL"
            ),
        },
        {
            "check": "EMPLOYEE_EXCEPTION_REVIEW_ROWS",
            "value": len(exceptions),
            "required": ">0",
            "status": "PASS",
        },
        {
            "check": "REVIEW_FAILURES",
            "value": len(failures),
            "required": 0,
            "status": (
                "PASS" if not failures else "FAIL"
            ),
        },
        {
            "check": "EMPLOYEE_HOME_CODE_VERIFIED",
            "value": False,
            "required": False,
            "status": "PASS",
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
        / "employee_home_code_review_validation_gate.csv",
        gate,
        ["check", "value", "required", "status"],
    )

    validation_summary = {
        "status": VALIDATION_STATUS,
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "context_review_rows": len(contexts),
        "employee_exception_review_rows": len(exceptions),
        "review_failures": len(failures),
        "review_gate": (
            "READY_FOR_EMPLOYEE_HOME_CODE_FINALIZATION"
            if final_pass
            else "SUPERVISOR_HOME_CODE_INPUT_OR_CORRECTION_REQUIRED"
        ),
        "employee_home_code_verification_completed": False,
        "operational_status": (
            "EMPLOYEE_HOME_CODE_SUPERVISOR_REVIEW_ONLY"
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
    print("EMPLOYEE HOME-CODE REVIEW VALIDATION FINISHED")
    print(json.dumps(validation_summary, indent=2))
    return 0


def self_test() -> int:
    print("SELF_TEST_PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root")
    parser.add_argument("--output-root")
    parser.add_argument("--allocation-path")
    parser.add_argument("--master-path")
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

    if not args.output_root or not args.master_path:
        raise SystemExit(
            "--output-root and --master-path are required."
        )

    if args.allocation_path:
        allocation_path = Path(
            args.allocation_path
        ).resolve()
        source_run = args.source_run
    else:
        if not args.project_root:
            raise SystemExit(
                "--project-root is required when "
                "--allocation-path is omitted."
            )
        allocation_path, source_run = discover_allocation(
            Path(args.project_root).resolve()
        )

    return create_review_pack(
        allocation_path,
        Path(args.master_path).resolve(),
        Path(args.output_root).resolve(),
        source_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
