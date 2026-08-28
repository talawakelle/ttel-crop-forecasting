from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


VERSION = "6.1.0"
SCENARIO_STATUS = "DEVELOPMENT_SIMULATION_ONLY"


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def estate_key(value: str) -> str:
    return "".join(ch for ch in clean(value).lower() if ch.isalnum())


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(clean(value).replace(",", ""))
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def first_planning_date(rows: list[dict[str, str]]) -> str:
    values = sorted({clean(row.get("date")) for row in rows if clean(row.get("date"))})
    if not values:
        raise RuntimeError("No planning dates found.")
    return values[0]


def productivity_value(row: dict[str, str]) -> float:
    recent = parse_float(row.get("recent_ewma_kg"))
    mean = parse_float(row.get("historical_mean_kg"))
    if recent > 0 and mean > 0:
        return 0.70 * recent + 0.30 * mean
    return max(recent, mean, 1.0)


def candidate_score(
    productivity: float,
    observation_count: int,
    scope_weight: float,
    demand: int,
) -> float:
    experience_weight = 1.0 + min(3.0, math.log1p(max(0, observation_count)) / 3.0)
    demand_penalty = 1.0 / (1.0 + max(0, demand) / 1000.0)
    return productivity * experience_weight * scope_weight * demand_penalty


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--employee-run", required=True)
    parser.add_argument("--planning-run", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--exact-field-limit", type=int, default=3)
    parser.add_argument("--same-division-limit", type=int, default=2)
    parser.add_argument("--estate-fallback-limit", type=int, default=2)
    args = parser.parse_args()

    employee_run = Path(args.employee_run).resolve()
    planning_run = Path(args.planning_run).resolve()
    output_root = Path(args.output_root).resolve()

    master_path = employee_run / "registers" / "employee_master.csv"
    experience_path = employee_run / "registers" / "employee_field_experience.csv"
    demand_path = planning_run / "planning" / "field_required_plucker_assignments.csv"

    for path in (master_path, experience_path, demand_path):
        if not path.exists():
            raise SystemExit(f"Missing required input: {path}")

    run_folder = output_root / datetime.now().strftime(
        "all_employee_scenario_%Y%m%d_%H%M%S"
    )
    registers_dir = run_folder / "registers"
    candidates_dir = run_folder / "candidates"
    quality_dir = run_folder / "quality"
    for folder in (registers_dir, candidates_dir, quality_dir):
        folder.mkdir(parents=True, exist_ok=True)

    started = time.time()

    employees = read_csv(master_path)
    experiences = read_csv(experience_path)
    demand_all = read_csv(demand_path)
    planning_date = first_planning_date(demand_all)
    demand_rows = [
        row for row in demand_all
        if clean(row.get("date")) == planning_date
        and int(parse_float(row.get("recommended_plucker_assignments"))) > 0
    ]

    if not employees:
        raise SystemExit("Employee master is empty.")
    if not demand_rows:
        raise SystemExit("No active field demand rows found.")

    print(f"All-employee scenario run: {run_folder}")
    print(f"Employees loaded: {len(employees)}")
    print(f"Planning date: {planning_date}")
    print("Every employee is included in the development scenario.")
    print("Official availability and constraint templates are not changed.")
    print("No CP-SAT allocation or RL policy will run.")

    employee_lookup: dict[tuple[str, str], dict[str, str]] = {}
    employees_by_estate: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    estate_display: dict[str, str] = {}

    for row in employees:
        key = estate_key(row.get("estate", ""))
        employee_id = clean(row.get("employee_id"))
        if not key or not employee_id:
            continue
        employee_lookup[(key, employee_id)] = row
        employees_by_estate[key].append(row)
        estate_display[key] = clean(row.get("estate"))

    active_fields_by_estate: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    active_field_lookup: dict[tuple[str, str], dict[str, Any]] = {}

    for row in demand_rows:
        key = estate_key(row.get("estate", ""))
        field_id = clean(row.get("field"))
        division = clean(row.get("division")) or "UNKNOWN"
        expected = int(parse_float(row.get("expected_plucker_assignments")))
        recommended = int(parse_float(row.get("recommended_plucker_assignments")))
        item = {
            "date": planning_date,
            "estate": clean(row.get("estate")),
            "estate_key": key,
            "division": division,
            "field": field_id,
            "expected_demand": expected,
            "recommended_demand": recommended,
            "central_crop_kg": parse_float(row.get("central_crop_kg")),
            "upper_crop_kg": parse_float(row.get("upper_conservative_crop_kg")),
        }
        active_fields_by_estate[key].append(item)
        active_field_lookup[(key, field_id)] = item

    experience_by_employee: defaultdict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in experiences:
        key = estate_key(row.get("estate", ""))
        employee_id = clean(row.get("employee_id"))
        if (key, employee_id) in employee_lookup:
            experience_by_employee[(key, employee_id)].append(row)

    roster_rows: list[dict[str, Any]] = []
    candidate_map: dict[tuple[str, str, str], dict[str, Any]] = {}
    represented_employees: defaultdict[str, set[str]] = defaultdict(set)
    employee_best_productivity: dict[tuple[str, str], float] = {}

    for estate_index, key in enumerate(sorted(employees_by_estate), start=1):
        estate_name = estate_display[key]
        estate_fields = active_fields_by_estate.get(key, [])
        if not estate_fields:
            raise RuntimeError(f"No active fields for estate {estate_name}")

        fields_by_division: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for field in estate_fields:
            fields_by_division[field["division"]].append(field)

        print(
            f"[{estate_index}/{len(employees_by_estate)}] "
            f"Building {estate_name}: {len(employees_by_estate[key])} employees",
            flush=True,
        )

        for employee in employees_by_estate[key]:
            employee_id = clean(employee.get("employee_id"))
            home_division = clean(employee.get("inferred_home_division")) or "UNKNOWN"
            history = experience_by_employee.get((key, employee_id), [])

            roster_rows.append({
                "date": planning_date,
                "estate": estate_name,
                "employee_id": employee_id,
                "inferred_home_division": home_division,
                "activity_class": clean(employee.get("activity_class")),
                "last_observed_date": clean(employee.get("last_observed_date")),
                "observation_count": clean(employee.get("observation_count")),
                "historical_mean_kg": clean(employee.get("historical_mean_kg")),
                "recent_ewma_kg": clean(employee.get("recent_ewma_kg")),
                "scenario_availability": "AVAILABLE_BY_USER_REQUEST_FOR_SIMULATION",
                "scenario_leave_status": "ASSUMED_NONE_FOR_SIMULATION",
                "scenario_medical_status": "UNVERIFIED",
                "scenario_cross_division_status": "ALLOWED_WITHIN_ESTATE_WITH_PENALTY",
                "max_daily_assignments": 1,
                "supervisor_confirmed": "NO",
                "operational_use_allowed": "NO",
                "scenario_status": SCENARIO_STATUS,
            })

            exact_candidates: list[tuple[float, dict[str, str], dict[str, Any]]] = []
            historical_divisions: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
            best_emp_productivity = max(
                parse_float(employee.get("recent_ewma_kg")),
                parse_float(employee.get("historical_mean_kg")),
                1.0,
            )

            for exp in history:
                field_id = clean(exp.get("field_id"))
                division = clean(exp.get("field_division")) or "UNKNOWN"
                historical_divisions[division].append(exp)
                active = active_field_lookup.get((key, field_id))
                if not active:
                    continue
                productivity = productivity_value(exp)
                best_emp_productivity = max(best_emp_productivity, productivity)
                count = int(parse_float(exp.get("observation_count")))
                score = candidate_score(
                    productivity, count, 1.00, active["recommended_demand"]
                )
                exact_candidates.append((score, exp, active))

            employee_best_productivity[(key, employee_id)] = best_emp_productivity

            exact_candidates.sort(key=lambda item: item[0], reverse=True)
            selected_fields: set[str] = set()

            for score, exp, active in exact_candidates[: max(0, args.exact_field_limit)]:
                field_id = active["field"]
                selected_fields.add(field_id)
                candidate_map[(key, employee_id, field_id)] = {
                    "date": planning_date,
                    "estate": estate_name,
                    "division": active["division"],
                    "field": field_id,
                    "expected_field_demand": active["expected_demand"],
                    "recommended_field_demand": active["recommended_demand"],
                    "employee_id": employee_id,
                    "inferred_home_division": home_division,
                    "candidate_scope": "EXACT_FIELD_HISTORY",
                    "cross_division": (
                        "NO" if home_division == active["division"] else "YES"
                    ),
                    "experience_count": int(parse_float(exp.get("observation_count"))),
                    "last_experience_date": clean(exp.get("last_observed_date")),
                    "expected_productivity_kg": round(productivity_value(exp), 4),
                    "candidate_score": round(score, 6),
                    "scenario_eligibility": "ELIGIBLE_FOR_DEVELOPMENT_SIMULATION",
                    "operational_use_allowed": "NO",
                }

            same_division_options = [
                field for field in fields_by_division.get(home_division, [])
                if field["field"] not in selected_fields
            ]
            same_division_options.sort(
                key=lambda field: (
                    field["recommended_demand"],
                    field["field"],
                )
            )

            division_history_rows = historical_divisions.get(home_division, [])
            if division_history_rows:
                division_productivity = sum(
                    productivity_value(row) for row in division_history_rows
                ) / len(division_history_rows)
                division_count = sum(
                    int(parse_float(row.get("observation_count")))
                    for row in division_history_rows
                )
            else:
                division_productivity = best_emp_productivity
                division_count = int(parse_float(employee.get("observation_count")))

            for active in same_division_options[: max(0, args.same_division_limit)]:
                field_id = active["field"]
                selected_fields.add(field_id)
                score = candidate_score(
                    division_productivity,
                    division_count,
                    0.82,
                    active["recommended_demand"],
                )
                candidate_map[(key, employee_id, field_id)] = {
                    "date": planning_date,
                    "estate": estate_name,
                    "division": active["division"],
                    "field": field_id,
                    "expected_field_demand": active["expected_demand"],
                    "recommended_field_demand": active["recommended_demand"],
                    "employee_id": employee_id,
                    "inferred_home_division": home_division,
                    "candidate_scope": "SAME_DIVISION_FALLBACK",
                    "cross_division": "NO",
                    "experience_count": division_count,
                    "last_experience_date": clean(employee.get("last_observed_date")),
                    "expected_productivity_kg": round(division_productivity, 4),
                    "candidate_score": round(score, 6),
                    "scenario_eligibility": "ELIGIBLE_FOR_DEVELOPMENT_SIMULATION",
                    "operational_use_allowed": "NO",
                }

            fallback_options = [
                field for field in estate_fields
                if field["field"] not in selected_fields
            ]
            fallback_options.sort(
                key=lambda field: (
                    field["division"] != home_division,
                    field["recommended_demand"],
                    field["field"],
                )
            )

            needed_fallback = max(
                1 if not selected_fields else 0,
                max(0, args.estate_fallback_limit),
            )
            for active in fallback_options[:needed_fallback]:
                field_id = active["field"]
                if field_id in selected_fields:
                    continue
                selected_fields.add(field_id)
                scope_weight = (
                    0.72 if active["division"] == home_division else 0.55
                )
                score = candidate_score(
                    best_emp_productivity,
                    int(parse_float(employee.get("observation_count"))),
                    scope_weight,
                    active["recommended_demand"],
                )
                candidate_map[(key, employee_id, field_id)] = {
                    "date": planning_date,
                    "estate": estate_name,
                    "division": active["division"],
                    "field": field_id,
                    "expected_field_demand": active["expected_demand"],
                    "recommended_field_demand": active["recommended_demand"],
                    "employee_id": employee_id,
                    "inferred_home_division": home_division,
                    "candidate_scope": (
                        "HOME_DIVISION_GENERAL_FALLBACK"
                        if active["division"] == home_division
                        else "ESTATE_WIDE_FALLBACK"
                    ),
                    "cross_division": (
                        "NO" if active["division"] == home_division else "YES"
                    ),
                    "experience_count": int(parse_float(employee.get("observation_count"))),
                    "last_experience_date": clean(employee.get("last_observed_date")),
                    "expected_productivity_kg": round(best_emp_productivity, 4),
                    "candidate_score": round(score, 6),
                    "scenario_eligibility": "ELIGIBLE_FOR_DEVELOPMENT_SIMULATION",
                    "operational_use_allowed": "NO",
                }

            if selected_fields:
                represented_employees[key].add(employee_id)

    # Guarantee that every active field has at least one candidate.
    candidates_by_field: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in candidate_map.values():
        candidates_by_field[(estate_key(row["estate"]), row["field"])].append(row)

    for key, estate_fields in active_fields_by_estate.items():
        estate_employees = employees_by_estate[key]
        ranked_employees = sorted(
            estate_employees,
            key=lambda row: employee_best_productivity.get(
                (key, clean(row.get("employee_id"))), 0.0
            ),
            reverse=True,
        )
        for active in estate_fields:
            field_key = (key, active["field"])
            if candidates_by_field.get(field_key):
                continue
            if not ranked_employees:
                continue
            employee = ranked_employees[0]
            employee_id = clean(employee.get("employee_id"))
            productivity = employee_best_productivity[(key, employee_id)]
            score = candidate_score(
                productivity,
                int(parse_float(employee.get("observation_count"))),
                0.45,
                active["recommended_demand"],
            )
            row = {
                "date": planning_date,
                "estate": estate_display[key],
                "division": active["division"],
                "field": active["field"],
                "expected_field_demand": active["expected_demand"],
                "recommended_field_demand": active["recommended_demand"],
                "employee_id": employee_id,
                "inferred_home_division": clean(
                    employee.get("inferred_home_division")
                ),
                "candidate_scope": "FIELD_COVERAGE_GUARANTEE_FALLBACK",
                "cross_division": "YES",
                "experience_count": int(parse_float(employee.get("observation_count"))),
                "last_experience_date": clean(employee.get("last_observed_date")),
                "expected_productivity_kg": round(productivity, 4),
                "candidate_score": round(score, 6),
                "scenario_eligibility": "ELIGIBLE_FOR_DEVELOPMENT_SIMULATION",
                "operational_use_allowed": "NO",
            }
            candidate_map[(key, employee_id, active["field"])] = row
            represented_employees[key].add(employee_id)
            candidates_by_field[field_key].append(row)

    candidate_rows = sorted(
        candidate_map.values(),
        key=lambda row: (
            row["estate"], row["division"], row["field"],
            -float(row["candidate_score"]), row["employee_id"],
        ),
    )

    field_candidate_counts: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    for row in candidate_rows:
        field_candidate_counts[
            (estate_key(row["estate"]), row["field"])
        ].add(row["employee_id"])

    inclusion_rows: list[dict[str, Any]] = []
    field_coverage_rows: list[dict[str, Any]] = []
    readiness_rows: list[dict[str, Any]] = []

    total_demand_expected: defaultdict[str, int] = defaultdict(int)
    total_demand_recommended: defaultdict[str, int] = defaultdict(int)
    total_fields: defaultdict[str, int] = defaultdict(int)
    covered_fields: defaultdict[str, int] = defaultdict(int)

    for key, fields in active_fields_by_estate.items():
        for active in fields:
            candidate_count = len(
                field_candidate_counts.get((key, active["field"]), set())
            )
            total_demand_expected[key] += active["expected_demand"]
            total_demand_recommended[key] += active["recommended_demand"]
            total_fields[key] += 1
            if candidate_count > 0:
                covered_fields[key] += 1
            field_coverage_rows.append({
                "date": planning_date,
                "estate": estate_display[key],
                "division": active["division"],
                "field": active["field"],
                "expected_demand": active["expected_demand"],
                "recommended_demand": active["recommended_demand"],
                "candidate_employees": candidate_count,
                "field_candidate_coverage": (
                    "PASS" if candidate_count > 0 else "FAIL"
                ),
                "operational_use_allowed": "NO",
            })

    for key in sorted(employees_by_estate):
        total_employee_count = len(employees_by_estate[key])
        represented_count = len(represented_employees.get(key, set()))
        skipped_count = total_employee_count - represented_count
        expected_demand = total_demand_expected[key]
        recommended_demand = total_demand_recommended[key]

        if total_employee_count >= recommended_demand:
            supply_status = "SUFFICIENT_FOR_CONSERVATIVE_SCENARIO"
        elif total_employee_count >= expected_demand:
            supply_status = "SUFFICIENT_FOR_EXPECTED_SCENARIO_ONLY"
        else:
            supply_status = "INSUFFICIENT_EVEN_FOR_EXPECTED_SCENARIO"

        ready = (
            skipped_count == 0
            and covered_fields[key] == total_fields[key]
            and total_employee_count >= expected_demand
        )

        inclusion_rows.append({
            "estate": estate_display[key],
            "total_employee_records": total_employee_count,
            "employees_represented_in_candidate_matrix": represented_count,
            "employees_skipped": skipped_count,
            "all_employee_inclusion_status": (
                "PASS" if skipped_count == 0 else "FAIL"
            ),
        })
        readiness_rows.append({
            "date": planning_date,
            "estate": estate_display[key],
            "total_employee_records": total_employee_count,
            "expected_assignment_demand": expected_demand,
            "recommended_assignment_demand": recommended_demand,
            "expected_supply_gap": max(0, expected_demand - total_employee_count),
            "conservative_supply_gap": max(
                0, recommended_demand - total_employee_count
            ),
            "unique_supply_status": supply_status,
            "active_fields": total_fields[key],
            "fields_with_candidates": covered_fields[key],
            "field_candidate_coverage_pct": round(
                covered_fields[key] / total_fields[key] * 100.0, 2
            ) if total_fields[key] else 0.0,
            "employees_skipped": skipped_count,
            "cp_sat_scenario_readiness": (
                "READY_FOR_CP_SAT_DEVELOPMENT_SIMULATION"
                if ready
                else "NOT_READY_DEVELOPMENT_INPUT_GAP"
            ),
            "operational_readiness": (
                "NOT_READY_REAL_AVAILABILITY_AND_CONSTRAINTS_UNVERIFIED"
            ),
            "cp_sat_started": "FALSE",
            "rl_started": "FALSE",
        })

    assumption_rows = [
        {
            "assumption": "ALL_EMPLOYEES_INCLUDED",
            "value": "YES",
            "interpretation": (
                "All employee master records are included in the development "
                "scenario and none are silently removed."
            ),
        },
        {
            "assumption": "AVAILABILITY",
            "value": "PROVISIONALLY_AVAILABLE_FOR_SIMULATION",
            "interpretation": (
                "This is a user-requested development assumption, not confirmed "
                "attendance."
            ),
        },
        {
            "assumption": "LEAVE",
            "value": "ASSUMED_NONE_FOR_SIMULATION",
            "interpretation": "Actual leave remains unverified.",
        },
        {
            "assumption": "MEDICAL_FITNESS",
            "value": "UNVERIFIED",
            "interpretation": (
                "The scenario does not claim that every employee is medically fit."
            ),
        },
        {
            "assumption": "MOVEMENT",
            "value": "WITHIN_ESTATE_ALLOWED_WITH_PENALTY",
            "interpretation": (
                "Exact-field and same-division history are preferred. "
                "Cross-division fallback is lower priority."
            ),
        },
        {
            "assumption": "OFFICIAL_TEMPLATES",
            "value": "UNCHANGED",
            "interpretation": (
                "The existing availability and constraint templates are not "
                "overwritten."
            ),
        },
        {
            "assumption": "OPERATIONAL_USE",
            "value": "PROHIBITED",
            "interpretation": (
                "Outputs are for development and simulation only until management "
                "confirmation is obtained."
            ),
        },
    ]

    roster_count = write_csv(
        registers_dir / "all_employee_development_scenario_roster.csv",
        roster_rows,
        [
            "date", "estate", "employee_id", "inferred_home_division",
            "activity_class", "last_observed_date", "observation_count",
            "historical_mean_kg", "recent_ewma_kg",
            "scenario_availability", "scenario_leave_status",
            "scenario_medical_status", "scenario_cross_division_status",
            "max_daily_assignments", "supervisor_confirmed",
            "operational_use_allowed", "scenario_status",
        ],
    )
    candidate_count = write_csv(
        candidates_dir / "all_employee_active_field_candidate_matrix.csv",
        candidate_rows,
        [
            "date", "estate", "division", "field",
            "expected_field_demand", "recommended_field_demand",
            "employee_id", "inferred_home_division", "candidate_scope",
            "cross_division", "experience_count", "last_experience_date",
            "expected_productivity_kg", "candidate_score",
            "scenario_eligibility", "operational_use_allowed",
        ],
    )
    write_csv(
        quality_dir / "all_employee_inclusion_gate.csv",
        inclusion_rows,
        [
            "estate", "total_employee_records",
            "employees_represented_in_candidate_matrix",
            "employees_skipped", "all_employee_inclusion_status",
        ],
    )
    write_csv(
        quality_dir / "active_field_candidate_coverage.csv",
        field_coverage_rows,
        [
            "date", "estate", "division", "field",
            "expected_demand", "recommended_demand",
            "candidate_employees", "field_candidate_coverage",
            "operational_use_allowed",
        ],
    )
    write_csv(
        quality_dir / "all_employee_cp_sat_scenario_readiness.csv",
        readiness_rows,
        [
            "date", "estate", "total_employee_records",
            "expected_assignment_demand", "recommended_assignment_demand",
            "expected_supply_gap", "conservative_supply_gap",
            "unique_supply_status", "active_fields",
            "fields_with_candidates", "field_candidate_coverage_pct",
            "employees_skipped", "cp_sat_scenario_readiness",
            "operational_readiness", "cp_sat_started", "rl_started",
        ],
    )
    write_csv(
        quality_dir / "scenario_assumption_register.csv",
        assumption_rows,
        ["assumption", "value", "interpretation"],
    )

    total_skipped = sum(int(row["employees_skipped"]) for row in inclusion_rows)
    field_failures = sum(
        1 for row in field_coverage_rows
        if row["field_candidate_coverage"] != "PASS"
    )
    ready_estates = sum(
        1 for row in readiness_rows
        if row["cp_sat_scenario_readiness"]
        == "READY_FOR_CP_SAT_DEVELOPMENT_SIMULATION"
    )
    duration = round((time.time() - started) / 60.0, 2)

    summary = {
        "status": (
            "PASS_ALL_EMPLOYEES_INCLUDED_FOR_DEVELOPMENT_SCENARIO"
            if total_skipped == 0 and field_failures == 0
            else "PASS_WITH_DEVELOPMENT_INPUT_GAPS"
        ),
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "employee_run": str(employee_run),
        "planning_run": str(planning_run),
        "planning_date": planning_date,
        "employee_records": len(employees),
        "scenario_roster_rows": roster_count,
        "candidate_matrix_rows": candidate_count,
        "active_field_rows": len(field_coverage_rows),
        "employees_skipped": total_skipped,
        "field_candidate_coverage_failures": field_failures,
        "ready_estates_for_cp_sat_development_simulation": ready_estates,
        "operational_status": SCENARIO_STATUS,
        "official_templates_changed": False,
        "cp_sat_started": False,
        "rl_started": False,
        "duration_minutes": duration,
        "important_interpretation": [
            "Every employee in employee_master.csv is included in the scenario roster.",
            "The scenario assumes provisional availability only because the user requested progress using every employee.",
            "No employee is declared genuinely available, medically fit or unrestricted.",
            "The official management-confirmation templates remain unchanged.",
            "The candidate matrix supports the next CP-SAT development simulation but is not a live allocation.",
        ],
    }

    (run_folder / "run_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    (run_folder / "README.txt").write_text(
        "\n".join([
            "TTE ALL-EMPLOYEE DEVELOPMENT SCENARIO v6.1.0",
            "",
            f"Planning date: {planning_date}",
            f"Employees included: {len(employees)}",
            "",
            "This scenario includes every employee record.",
            "It does not overwrite the official availability or constraint templates.",
            "It is not approved for real employee allocation.",
            "No CP-SAT or RL process has been started.",
        ]) + "\n",
        encoding="utf-8",
    )

    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "LATEST_ALL_EMPLOYEE_SCENARIO_RUN.txt").write_text(
        str(run_folder), encoding="utf-8"
    )

    print("")
    print("ALL-EMPLOYEE DEVELOPMENT SCENARIO FINISHED")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
