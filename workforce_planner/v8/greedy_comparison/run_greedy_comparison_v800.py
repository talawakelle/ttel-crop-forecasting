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


VERSION = "8.0.0"
OPERATIONAL_STATUS = "DEVELOPMENT_SIMULATION_ONLY"


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def norm(value: Any) -> str:
    return "".join(ch for ch in clean(value).lower() if ch.isalnum())


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(clean(value).replace(",", ""))
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def parse_int(value: Any, default: int = 0) -> int:
    return int(round(parse_float(value, float(default))))


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


def field_key(row: dict[str, Any]) -> tuple[str, str]:
    return (norm(row.get("division")), clean(row.get("field")))


def field_uid(division: str, field: str) -> str:
    return f"{division}::{field}"


def scope_penalty(scope: str) -> float:
    return {
        "EXACT_FIELD_HISTORY": 0.0,
        "SAME_DIVISION_CAPACITY": 2.0,
        "ESTATE_WIDE_CAPACITY_FALLBACK": 8.0,
    }.get(clean(scope), 10.0)


def candidate_utility(
    productivity: float,
    remaining: float,
    cross_division: str,
    scope: str,
) -> tuple[float, float, float]:
    useful = min(productivity, max(0.0, remaining))
    over = max(0.0, productivity - remaining)
    penalty = (
        over * 0.20
        + (2.0 if clean(cross_division).upper() == "YES" else 0.0)
        + scope_penalty(scope)
    )
    return (useful - penalty, useful, -over)


def run_greedy_estate(
    scenario: str,
    estate_name: str,
    candidate_rows: list[dict[str, str]],
    demand_rows: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    fields: dict[tuple[str, str], dict[str, Any]] = {}
    for row in demand_rows:
        division = clean(row.get("division")) or "UNKNOWN"
        field = clean(row.get("field"))
        key = (norm(division), field)

        if scenario == "EXPECTED":
            target = max(0.0, parse_float(row.get("central_crop_kg")))
            reference = max(0, parse_int(row.get("expected_plucker_assignments")))
        else:
            target = max(
                0.0, parse_float(row.get("upper_conservative_crop_kg"))
            )
            reference = max(
                0, parse_int(row.get("recommended_plucker_assignments"))
            )

        fields[key] = {
            "date": clean(row.get("date")),
            "estate": clean(row.get("estate")),
            "division": division,
            "field": field,
            "field_uid": field_uid(division, field),
            "target_crop_kg": target,
            "reference_assignment_demand": reference,
        }

    candidates_by_field: defaultdict[
        tuple[str, str], list[dict[str, Any]]
    ] = defaultdict(list)
    employee_ids: set[str] = set()

    for row in candidate_rows:
        key = field_key(row)
        if key not in fields:
            continue
        employee_id = clean(row.get("employee_id"))
        if not employee_id:
            continue
        employee_ids.add(employee_id)
        candidates_by_field[key].append({
            "employee_id": employee_id,
            "expected_productivity_kg": max(
                0.1, parse_float(row.get("expected_productivity_kg"), 0.1)
            ),
            "candidate_scope": clean(row.get("candidate_scope")),
            "cross_division": clean(row.get("cross_division")).upper(),
            "inferred_home_division": clean(
                row.get("inferred_home_division")
            ),
        })

    assigned_employee_ids: set[str] = set()
    assigned_by_field: defaultdict[
        tuple[str, str], list[dict[str, Any]]
    ] = defaultdict(list)
    remaining = {
        key: info["target_crop_kg"]
        for key, info in fields.items()
    }

    # Budgeted dynamic greedy:
    # repeatedly prioritise the field with the largest relative shortage,
    # then choose the unassigned employee with the best useful-capacity fit.
    max_steps = max(1, len(employee_ids))
    for _ in range(max_steps):
        open_fields = [
            key for key, value in remaining.items()
            if value > 0.5
            and any(
                candidate["employee_id"] not in assigned_employee_ids
                for candidate in candidates_by_field.get(key, [])
            )
        ]
        if not open_fields:
            break

        def field_priority(key: tuple[str, str]) -> tuple[float, float]:
            target = max(fields[key]["target_crop_kg"], 1.0)
            return (remaining[key] / target, remaining[key])

        selected_field = max(open_fields, key=field_priority)
        selected_candidate = None
        selected_utility = None

        for candidate in candidates_by_field[selected_field]:
            if candidate["employee_id"] in assigned_employee_ids:
                continue
            utility = candidate_utility(
                productivity=candidate["expected_productivity_kg"],
                remaining=remaining[selected_field],
                cross_division=candidate["cross_division"],
                scope=candidate["candidate_scope"],
            )
            tie_break = (
                utility,
                candidate["expected_productivity_kg"],
                -scope_penalty(candidate["candidate_scope"]),
                candidate["employee_id"],
            )
            if selected_utility is None or tie_break > selected_utility:
                selected_utility = tie_break
                selected_candidate = candidate

        if selected_candidate is None:
            remaining[selected_field] = max(remaining[selected_field], 0.5001)
            continue

        assigned_employee_ids.add(selected_candidate["employee_id"])
        assigned_by_field[selected_field].append(selected_candidate)
        remaining[selected_field] = max(
            0.0,
            remaining[selected_field]
            - selected_candidate["expected_productivity_kg"],
        )

    assignment_rows: list[dict[str, Any]] = []
    field_rows: list[dict[str, Any]] = []

    for key, info in fields.items():
        assigned = assigned_by_field.get(key, [])
        capacity = sum(
            row["expected_productivity_kg"] for row in assigned
        )
        under = max(0.0, info["target_crop_kg"] - capacity)
        over = max(0.0, capacity - info["target_crop_kg"])
        coverage = (
            max(
                0.0,
                min(
                    100.0,
                    (info["target_crop_kg"] - under)
                    / info["target_crop_kg"]
                    * 100.0,
                ),
            )
            if info["target_crop_kg"] > 0
            else 100.0
        )
        field_status = (
            "COVERAGE_95_PLUS"
            if coverage >= 95.0
            else "PARTIAL_COVERAGE"
            if assigned
            else "UNCOVERED"
        )

        field_rows.append({
            "date": info["date"],
            "method": "GREEDY",
            "scenario": scenario,
            "estate": estate_name,
            "division": info["division"],
            "field": info["field"],
            "field_uid": info["field_uid"],
            "target_crop_kg": round(info["target_crop_kg"], 4),
            "reference_assignment_demand": (
                info["reference_assignment_demand"]
            ),
            "assigned_employee_count": len(assigned),
            "assigned_capacity_kg": round(capacity, 4),
            "under_kg": round(under, 4),
            "over_kg": round(over, 4),
            "coverage_pct": round(coverage, 2),
            "field_status": field_status,
            "operational_status": OPERATIONAL_STATUS,
        })

        for candidate in assigned:
            assignment_rows.append({
                "date": info["date"],
                "method": "GREEDY",
                "scenario": scenario,
                "estate": estate_name,
                "division": info["division"],
                "field": info["field"],
                "field_uid": info["field_uid"],
                "target_crop_kg": round(info["target_crop_kg"], 4),
                "employee_id": candidate["employee_id"],
                "expected_productivity_kg": (
                    candidate["expected_productivity_kg"]
                ),
                "candidate_scope": candidate["candidate_scope"],
                "cross_division": candidate["cross_division"],
                "inferred_home_division": (
                    candidate["inferred_home_division"]
                ),
                "field_assigned_employee_count": len(assigned),
                "field_assigned_capacity_kg": round(capacity, 4),
                "field_under_kg": round(under, 4),
                "field_over_kg": round(over, 4),
                "operational_use_allowed": "NO",
            })

    duplicate_assignments = max(
        0, len(assignment_rows) - len({
            row["employee_id"] for row in assignment_rows
        })
    )
    total_target = sum(row["target_crop_kg"] for row in field_rows)
    total_under = sum(row["under_kg"] for row in field_rows)
    total_over = sum(row["over_kg"] for row in field_rows)
    effective_coverage = (
        (total_target - total_under) / total_target * 100.0
        if total_target > 0 else 100.0
    )
    cross_assignments = sum(
        1 for row in assignment_rows
        if row["cross_division"] == "YES"
    )

    estate_summary = {
        "method": "GREEDY",
        "scenario": scenario,
        "estate": estate_name,
        "employees_assigned": len(assigned_employee_ids),
        "fields": len(field_rows),
        "fields_coverage_95_plus": sum(
            1 for row in field_rows if row["coverage_pct"] >= 95.0
        ),
        "uncovered_fields": sum(
            1 for row in field_rows
            if row["assigned_employee_count"] == 0
        ),
        "total_target_crop_kg": round(total_target, 4),
        "total_under_kg": round(total_under, 4),
        "total_over_kg": round(total_over, 4),
        "effective_coverage_pct": round(effective_coverage, 2),
        "cross_division_assignments": cross_assignments,
        "duplicate_employee_assignments": duplicate_assignments,
        "operational_status": OPERATIONAL_STATUS,
    }
    return assignment_rows, field_rows, estate_summary


def convert_cp_sat_estate_rows(
    cp_rows: list[dict[str, str]],
    assignment_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    cross_counts: defaultdict[tuple[str, str], int] = defaultdict(int)
    for row in assignment_rows:
        if clean(row.get("cross_division")).upper() == "YES":
            cross_counts[
                (clean(row.get("scenario")), norm(row.get("estate")))
            ] += 1

    converted = []
    for row in cp_rows:
        scenario = clean(row.get("scenario"))
        estate = clean(row.get("estate"))
        converted.append({
            "method": "CP_SAT",
            "scenario": scenario,
            "estate": estate,
            "employees_assigned": parse_int(row.get("employees_assigned")),
            "fields": parse_int(row.get("fields")),
            "fields_coverage_95_plus": parse_int(
                row.get("fields_coverage_95_plus")
            ),
            "uncovered_fields": parse_int(row.get("uncovered_fields")),
            "total_target_crop_kg": parse_float(
                row.get("total_target_crop_kg")
            ),
            "total_under_kg": parse_float(row.get("total_under_kg")),
            "total_over_kg": parse_float(row.get("total_over_kg")),
            "effective_coverage_pct": parse_float(
                row.get("effective_coverage_pct")
            ),
            "cross_division_assignments": cross_counts[
                (scenario, norm(estate))
            ],
            "duplicate_employee_assignments": parse_int(
                row.get("duplicate_employee_assignments")
            ),
            "operational_status": OPERATIONAL_STATUS,
        })
    return converted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capacity-run", required=True)
    parser.add_argument("--planning-run", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()

    capacity_run = Path(args.capacity_run).resolve()
    planning_run = Path(args.planning_run).resolve()
    output_root = Path(args.output_root).resolve()

    candidate_path = (
        capacity_run
        / "inputs"
        / "expanded_employee_field_candidate_matrix.csv"
    )
    cp_assignment_path = (
        capacity_run
        / "assignments"
        / "cp_sat_capacity_matched_assignments.csv"
    )
    cp_estate_path = (
        capacity_run
        / "quality"
        / "cp_sat_capacity_estate_results.csv"
    )
    demand_path = (
        planning_run
        / "planning"
        / "field_required_plucker_assignments.csv"
    )

    for path in (
        candidate_path,
        cp_assignment_path,
        cp_estate_path,
        demand_path,
    ):
        if not path.exists():
            raise SystemExit(f"Missing required input: {path}")

    candidates = read_csv(candidate_path)
    cp_assignments = read_csv(cp_assignment_path)
    cp_estates = read_csv(cp_estate_path)
    demand = read_csv(demand_path)

    planning_dates = sorted({
        clean(row.get("date")) for row in demand if clean(row.get("date"))
    })
    if not planning_dates:
        raise SystemExit("No planning date found.")
    planning_date = planning_dates[0]

    active_demand = [
        row for row in demand
        if clean(row.get("date")) == planning_date
        and parse_int(row.get("recommended_plucker_assignments")) > 0
    ]
    active_candidates = [
        row for row in candidates
        if clean(row.get("date")) == planning_date
    ]

    demand_by_estate: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    candidates_by_estate: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    estate_display: dict[str, str] = {}

    for row in active_demand:
        key = norm(row.get("estate"))
        demand_by_estate[key].append(row)
        estate_display[key] = clean(row.get("estate"))
    for row in active_candidates:
        key = norm(row.get("estate"))
        candidates_by_estate[key].append(row)

    if len(demand_by_estate) != 33:
        raise SystemExit(
            f"Expected 33 estates but found {len(demand_by_estate)}."
        )

    scenarios = ["EXPECTED", "CONSERVATIVE"]
    run_folder = output_root / datetime.now().strftime(
        "greedy_comparison_%Y%m%d_%H%M%S"
    )
    assignment_dir = run_folder / "assignments"
    quality_dir = run_folder / "quality"
    assignment_dir.mkdir(parents=True, exist_ok=True)
    quality_dir.mkdir(parents=True, exist_ok=True)

    all_greedy_assignments: list[dict[str, Any]] = []
    all_greedy_fields: list[dict[str, Any]] = []
    all_greedy_estates: list[dict[str, Any]] = []

    started = time.time()
    print(f"Greedy comparison run: {run_folder}")
    print(f"Planning date: {planning_date}")
    print("Method: budgeted dynamic greedy")
    print("Field identity: estate + division + field")
    print("Each employee can be assigned to at most one field per scenario.")
    print("No RL training will run.")

    for scenario in scenarios:
        print("")
        print(f"SCENARIO: {scenario}")
        for index, estate_key in enumerate(
            sorted(demand_by_estate), start=1
        ):
            estate = estate_display[estate_key]
            print(f"[{index}/33] Greedy {estate}", flush=True)
            assignments, fields, summary = run_greedy_estate(
                scenario=scenario,
                estate_name=estate,
                candidate_rows=candidates_by_estate[estate_key],
                demand_rows=demand_by_estate[estate_key],
            )
            all_greedy_assignments.extend(assignments)
            all_greedy_fields.extend(fields)
            all_greedy_estates.append(summary)

    cp_method_rows = convert_cp_sat_estate_rows(
        cp_estates, cp_assignments
    )
    all_method_rows = cp_method_rows + all_greedy_estates

    comparison_rows: list[dict[str, Any]] = []
    cp_lookup = {
        (row["scenario"], norm(row["estate"])): row
        for row in cp_method_rows
    }
    greedy_lookup = {
        (row["scenario"], norm(row["estate"])): row
        for row in all_greedy_estates
    }

    for scenario in scenarios:
        for estate_key in sorted(demand_by_estate):
            estate = estate_display[estate_key]
            cp = cp_lookup[(scenario, estate_key)]
            greedy = greedy_lookup[(scenario, estate_key)]

            cp_noninferior = (
                cp["total_under_kg"] <= greedy["total_under_kg"] + 0.5
            )
            cp_better_under = (
                cp["total_under_kg"] < greedy["total_under_kg"] - 0.5
            )
            cp_better_over = (
                cp["total_over_kg"] < greedy["total_over_kg"] - 0.5
            )

            if cp_better_under:
                winner = "CP_SAT"
                reason = "LOWER_UNCOVERED_CROP"
            elif not cp_noninferior:
                winner = "GREEDY"
                reason = "LOWER_UNCOVERED_CROP"
            elif cp_better_over:
                winner = "CP_SAT"
                reason = "SIMILAR_COVERAGE_LOWER_EXCESS_CAPACITY"
            elif (
                cp["employees_assigned"]
                < greedy["employees_assigned"]
            ):
                winner = "CP_SAT"
                reason = "SIMILAR_COVERAGE_FEWER_EMPLOYEES"
            elif (
                greedy["employees_assigned"]
                < cp["employees_assigned"]
            ):
                winner = "GREEDY"
                reason = "SIMILAR_COVERAGE_FEWER_EMPLOYEES"
            else:
                winner = "TIE"
                reason = "MATERIAL_RESULTS_EQUIVALENT"

            comparison_rows.append({
                "scenario": scenario,
                "estate": estate,
                "cp_sat_under_kg": round(cp["total_under_kg"], 4),
                "greedy_under_kg": round(
                    greedy["total_under_kg"], 4
                ),
                "cp_sat_over_kg": round(cp["total_over_kg"], 4),
                "greedy_over_kg": round(
                    greedy["total_over_kg"], 4
                ),
                "cp_sat_employees": cp["employees_assigned"],
                "greedy_employees": greedy["employees_assigned"],
                "cp_sat_cross_division": (
                    cp["cross_division_assignments"]
                ),
                "greedy_cross_division": (
                    greedy["cross_division_assignments"]
                ),
                "cp_sat_noninferior_on_under_crop": (
                    "YES" if cp_noninferior else "NO"
                ),
                "winner": winner,
                "winner_reason": reason,
                "operational_status": OPERATIONAL_STATUS,
            })

    write_csv(
        assignment_dir / "greedy_employee_field_assignments.csv",
        all_greedy_assignments,
        [
            "date", "method", "scenario", "estate", "division",
            "field", "field_uid", "target_crop_kg", "employee_id",
            "expected_productivity_kg", "candidate_scope",
            "cross_division", "inferred_home_division",
            "field_assigned_employee_count",
            "field_assigned_capacity_kg", "field_under_kg",
            "field_over_kg", "operational_use_allowed",
        ],
    )
    write_csv(
        quality_dir / "greedy_field_results.csv",
        all_greedy_fields,
        [
            "date", "method", "scenario", "estate", "division",
            "field", "field_uid", "target_crop_kg",
            "reference_assignment_demand",
            "assigned_employee_count", "assigned_capacity_kg",
            "under_kg", "over_kg", "coverage_pct",
            "field_status", "operational_status",
        ],
    )
    write_csv(
        quality_dir / "method_estate_results.csv",
        all_method_rows,
        [
            "method", "scenario", "estate", "employees_assigned",
            "fields", "fields_coverage_95_plus",
            "uncovered_fields", "total_target_crop_kg",
            "total_under_kg", "total_over_kg",
            "effective_coverage_pct", "cross_division_assignments",
            "duplicate_employee_assignments",
            "operational_status",
        ],
    )
    write_csv(
        quality_dir / "cp_sat_vs_greedy_comparison.csv",
        comparison_rows,
        [
            "scenario", "estate", "cp_sat_under_kg",
            "greedy_under_kg", "cp_sat_over_kg",
            "greedy_over_kg", "cp_sat_employees",
            "greedy_employees", "cp_sat_cross_division",
            "greedy_cross_division",
            "cp_sat_noninferior_on_under_crop",
            "winner", "winner_reason", "operational_status",
        ],
    )

    expected_comparisons = 66
    actual_comparisons = len(comparison_rows)
    cp_noninferior_count = sum(
        1 for row in comparison_rows
        if row["cp_sat_noninferior_on_under_crop"] == "YES"
    )
    cp_noninferior_rate = (
        cp_noninferior_count / actual_comparisons * 100.0
        if actual_comparisons else 0.0
    )
    greedy_duplicate_failures = sum(
        int(row["duplicate_employee_assignments"])
        for row in all_greedy_estates
    )
    greedy_field_rows_expected = len(active_demand) * 2
    greedy_field_identity_failures = abs(
        greedy_field_rows_expected - len(all_greedy_fields)
    )
    uncovered_expected = sum(
        int(row["uncovered_fields"])
        for row in all_greedy_estates
        if row["scenario"] == "EXPECTED"
    )

    if (
        actual_comparisons == expected_comparisons
        and greedy_duplicate_failures == 0
        and greedy_field_identity_failures == 0
        and cp_noninferior_rate >= 80.0
        and uncovered_expected == 0
    ):
        rl_baseline_gate = "READY_FOR_RL_ENVIRONMENT_DESIGN"
    else:
        rl_baseline_gate = "NOT_READY_BASELINE_REVIEW_REQUIRED"

    summary = {
        "status": (
            "PASS_CP_SAT_GREEDY_COMPARISON_OUTPUTS"
            if actual_comparisons == expected_comparisons
            and greedy_duplicate_failures == 0
            and greedy_field_identity_failures == 0
            else "PASS_WITH_CP_SAT_GREEDY_COMPARISON_WARNINGS"
        ),
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "capacity_run": str(capacity_run),
        "planning_run": str(planning_run),
        "planning_date": planning_date,
        "comparison_rows_expected": expected_comparisons,
        "comparison_rows_actual": actual_comparisons,
        "greedy_assignment_rows": len(all_greedy_assignments),
        "greedy_field_rows_expected": greedy_field_rows_expected,
        "greedy_field_rows_actual": len(all_greedy_fields),
        "greedy_field_identity_failures": (
            greedy_field_identity_failures
        ),
        "greedy_duplicate_employee_assignment_failures": (
            greedy_duplicate_failures
        ),
        "greedy_expected_uncovered_fields": uncovered_expected,
        "cp_sat_noninferior_estate_scenarios": (
            cp_noninferior_count
        ),
        "cp_sat_noninferiority_rate_pct": round(
            cp_noninferior_rate, 2
        ),
        "minimum_noninferiority_gate_pct": 80.0,
        "rl_baseline_gate": rl_baseline_gate,
        "operational_status": OPERATIONAL_STATUS,
        "rl_started": False,
        "duration_minutes": round(
            (time.time() - started) / 60.0, 2
        ),
        "important_interpretation": [
            "The greedy method is a deterministic baseline, not a live allocator.",
            "CP-SAT is compared against greedy across 33 estates and two scenarios.",
            "The 80 percent noninferiority gate mirrors the Clarendon-style safety comparison.",
            "Passing this gate permits RL environment design only; it does not approve RL deployment.",
            "RL training has not started.",
        ],
    }

    (run_folder / "run_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    (run_folder / "README.txt").write_text(
        "\n".join([
            "TTE CP-SAT VS GREEDY COMPARISON v8.0.0",
            "",
            f"Planning date: {planning_date}",
            f"CP-SAT noninferiority rate: {cp_noninferior_rate:.2f}%",
            f"RL baseline gate: {rl_baseline_gate}",
            "",
            "This is development simulation only.",
            "RL training has not started.",
        ]) + "\n",
        encoding="utf-8",
    )

    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "LATEST_GREEDY_COMPARISON_RUN.txt").write_text(
        str(run_folder), encoding="utf-8"
    )

    print("")
    print("CP-SAT VS GREEDY COMPARISON FINISHED")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
