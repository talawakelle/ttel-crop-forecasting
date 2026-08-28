from __future__ import annotations

import argparse
import csv
import json
import math
import os
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


VERSION = "7.0.0"
OPERATIONAL_STATUS = "DEVELOPMENT_SIMULATION_ONLY"


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


def scope_penalty(scope: str) -> int:
    return {
        "EXACT_FIELD_HISTORY": 0,
        "SAME_DIVISION_FALLBACK": 2,
        "HOME_DIVISION_GENERAL_FALLBACK": 4,
        "ESTATE_WIDE_FALLBACK": 8,
        "FIELD_COVERAGE_GUARANTEE_FALLBACK": 12,
    }.get(clean(scope).upper(), 10)


def validate_inputs(
    candidate_rows: list[dict[str, str]],
    demand_rows: list[dict[str, str]],
) -> dict[str, Any]:
    required_candidate_columns = {
        "date", "estate", "division", "field", "employee_id",
        "expected_productivity_kg", "candidate_scope", "cross_division",
    }
    required_demand_columns = {
        "date", "estate", "division", "field", "central_crop_kg",
        "upper_conservative_crop_kg", "expected_plucker_assignments",
        "recommended_plucker_assignments",
    }

    if not candidate_rows:
        raise RuntimeError("Candidate matrix is empty.")
    if not demand_rows:
        raise RuntimeError("Field demand file is empty.")

    missing_candidate = required_candidate_columns - set(candidate_rows[0])
    missing_demand = required_demand_columns - set(demand_rows[0])
    if missing_candidate:
        raise RuntimeError(
            f"Candidate matrix missing columns: {sorted(missing_candidate)}"
        )
    if missing_demand:
        raise RuntimeError(
            f"Field demand file missing columns: {sorted(missing_demand)}"
        )

    dates = sorted(
        {
            clean(row.get("date"))
            for row in demand_rows
            if clean(row.get("date"))
        }
    )
    if not dates:
        raise RuntimeError("No planning date was found.")

    planning_date = dates[0]
    active_demand = [
        row for row in demand_rows
        if clean(row.get("date")) == planning_date
        and parse_int(row.get("recommended_plucker_assignments")) > 0
    ]
    active_candidates = [
        row for row in candidate_rows
        if clean(row.get("date")) == planning_date
    ]

    demand_fields = {
        (
            estate_key(row.get("estate", "")),
            clean(row.get("field")),
        )
        for row in active_demand
    }
    candidate_fields = {
        (
            estate_key(row.get("estate", "")),
            clean(row.get("field")),
        )
        for row in active_candidates
    }

    missing_fields = sorted(demand_fields - candidate_fields)
    duplicate_edges = 0
    edge_seen: set[tuple[str, str, str]] = set()
    for row in active_candidates:
        edge = (
            estate_key(row.get("estate", "")),
            clean(row.get("employee_id")),
            clean(row.get("field")),
        )
        if edge in edge_seen:
            duplicate_edges += 1
        edge_seen.add(edge)

    estates = sorted(
        {
            estate_key(row.get("estate", ""))
            for row in active_demand
        }
    )

    return {
        "planning_date": planning_date,
        "active_field_rows": len(active_demand),
        "candidate_rows": len(active_candidates),
        "estates": len(estates),
        "missing_candidate_fields": len(missing_fields),
        "duplicate_candidate_edges": duplicate_edges,
    }


def solve_estate(
    cp_model,
    scenario: str,
    estate_name: str,
    demand_rows: list[dict[str, str]],
    candidate_rows: list[dict[str, str]],
    time_limit_seconds: float,
    workers: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    model = cp_model.CpModel()

    field_info: dict[str, dict[str, Any]] = {}
    for row in demand_rows:
        field_id = clean(row.get("field"))
        if scenario == "EXPECTED":
            target_crop = parse_float(row.get("central_crop_kg"))
            demand_limit = max(
                1, parse_int(row.get("expected_plucker_assignments"))
            )
        else:
            target_crop = parse_float(row.get("upper_conservative_crop_kg"))
            demand_limit = max(
                1, parse_int(row.get("recommended_plucker_assignments"))
            )

        field_info[field_id] = {
            "date": clean(row.get("date")),
            "estate": clean(row.get("estate")),
            "division": clean(row.get("division")),
            "field": field_id,
            "target_crop_kg": max(0.0, target_crop),
            "assignment_limit": demand_limit,
            "central_crop_kg": parse_float(row.get("central_crop_kg")),
            "upper_crop_kg": parse_float(
                row.get("upper_conservative_crop_kg")
            ),
            "expected_demand": parse_int(
                row.get("expected_plucker_assignments")
            ),
            "recommended_demand": parse_int(
                row.get("recommended_plucker_assignments")
            ),
        }

    edges: list[dict[str, Any]] = []
    edge_seen: set[tuple[str, str]] = set()
    for row in candidate_rows:
        employee_id = clean(row.get("employee_id"))
        field_id = clean(row.get("field"))
        if field_id not in field_info or not employee_id:
            continue
        edge_key = (employee_id, field_id)
        if edge_key in edge_seen:
            continue
        edge_seen.add(edge_key)

        productivity_kg = max(
            0.1, parse_float(row.get("expected_productivity_kg"), 0.1)
        )
        edges.append({
            "employee_id": employee_id,
            "field": field_id,
            "division": clean(row.get("division")),
            "inferred_home_division": clean(
                row.get("inferred_home_division")
            ),
            "candidate_scope": clean(row.get("candidate_scope")),
            "cross_division": clean(row.get("cross_division")).upper(),
            "expected_productivity_kg": productivity_kg,
            "candidate_score": parse_float(row.get("candidate_score")),
            "experience_count": parse_int(row.get("experience_count")),
            "last_experience_date": clean(
                row.get("last_experience_date")
            ),
        })

    if not edges:
        return [], [], {
            "estate": estate_name,
            "scenario": scenario,
            "solver_status": "NO_CANDIDATE_EDGES",
            "objective_value": "",
            "best_bound": "",
            "wall_time_seconds": 0.0,
            "employees_assigned": 0,
            "fields": len(field_info),
            "fields_fully_covered": 0,
            "total_target_crop_kg": round(
                sum(item["target_crop_kg"] for item in field_info.values()), 4
            ),
            "total_assigned_capacity_kg": 0.0,
            "total_under_kg": round(
                sum(item["target_crop_kg"] for item in field_info.values()), 4
            ),
            "total_over_kg": 0.0,
            "duplicate_employee_assignments": 0,
            "operational_status": OPERATIONAL_STATUS,
        }

    x = [
        model.NewBoolVar(f"x_{index}")
        for index in range(len(edges))
    ]

    employee_edges: defaultdict[str, list[int]] = defaultdict(list)
    field_edges: defaultdict[str, list[int]] = defaultdict(list)
    for index, edge in enumerate(edges):
        employee_edges[edge["employee_id"]].append(index)
        field_edges[edge["field"]].append(index)

    for indexes in employee_edges.values():
        model.Add(sum(x[index] for index in indexes) <= 1)

    scale = 10
    under_vars: dict[str, Any] = {}
    over_vars: dict[str, Any] = {}
    objective_terms: list[Any] = []

    for field_id, info in field_info.items():
        indexes = field_edges.get(field_id, [])
        model.Add(sum(x[index] for index in indexes) <= info["assignment_limit"])

        target_scaled = int(round(info["target_crop_kg"] * scale))
        max_capacity = sum(
            int(round(edges[index]["expected_productivity_kg"] * scale))
            for index in indexes
        )
        upper_slack = max(target_scaled, max_capacity, 1)

        under = model.NewIntVar(0, upper_slack, f"under_{field_id}")
        over = model.NewIntVar(0, upper_slack, f"over_{field_id}")
        under_vars[field_id] = under
        over_vars[field_id] = over

        capacity_expr = sum(
            int(round(edges[index]["expected_productivity_kg"] * scale))
            * x[index]
            for index in indexes
        )
        model.Add(capacity_expr + under - over == target_scaled)

        # Lexicographic-style weighting:
        # 1. minimize crop left uncovered
        # 2. minimize excess capacity
        # 3. prefer fewer employees for the same crop match
        objective_terms.append(100_000 * under)
        objective_terms.append(1_000 * over)

    for index, edge in enumerate(edges):
        employee_penalty = 10
        cross_penalty = 20 if edge["cross_division"] == "YES" else 0
        fallback_penalty = scope_penalty(edge["candidate_scope"])
        objective_terms.append(
            (employee_penalty + cross_penalty + fallback_penalty) * x[index]
        )

    model.Minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(1.0, time_limit_seconds)
    solver.parameters.num_search_workers = max(1, workers)
    solver.parameters.log_search_progress = False
    solver.parameters.random_seed = 20260723

    status_code = solver.Solve(model)
    status_name = solver.StatusName(status_code)

    assignment_rows: list[dict[str, Any]] = []
    field_rows: list[dict[str, Any]] = []
    employee_assignment_count: defaultdict[str, int] = defaultdict(int)

    assigned_edges_by_field: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    if status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for index, edge in enumerate(edges):
            if solver.Value(x[index]) == 1:
                assigned_edges_by_field[edge["field"]].append(edge)
                employee_assignment_count[edge["employee_id"]] += 1

    for field_id, info in field_info.items():
        assigned_edges = assigned_edges_by_field.get(field_id, [])
        assigned_capacity = sum(
            edge["expected_productivity_kg"] for edge in assigned_edges
        )
        under_kg = max(0.0, info["target_crop_kg"] - assigned_capacity)
        over_kg = max(0.0, assigned_capacity - info["target_crop_kg"])
        coverage_pct = (
            min(100.0, assigned_capacity / info["target_crop_kg"] * 100.0)
            if info["target_crop_kg"] > 0 else 100.0
        )
        field_status = (
            "FULLY_COVERED"
            if under_kg <= 0.5
            else "PARTIALLY_COVERED"
            if assigned_capacity > 0
            else "UNCOVERED"
        )

        field_rows.append({
            "date": info["date"],
            "scenario": scenario,
            "estate": estate_name,
            "division": info["division"],
            "field": field_id,
            "target_crop_kg": round(info["target_crop_kg"], 4),
            "assignment_limit": info["assignment_limit"],
            "assigned_employee_count": len(assigned_edges),
            "assigned_capacity_kg": round(assigned_capacity, 4),
            "under_kg": round(under_kg, 4),
            "over_kg": round(over_kg, 4),
            "coverage_pct": round(coverage_pct, 2),
            "field_status": field_status,
            "solver_status": status_name,
            "operational_status": OPERATIONAL_STATUS,
        })

        for edge in assigned_edges:
            assignment_rows.append({
                "date": info["date"],
                "scenario": scenario,
                "estate": estate_name,
                "division": info["division"],
                "field": field_id,
                "target_crop_kg": round(info["target_crop_kg"], 4),
                "employee_id": edge["employee_id"],
                "expected_productivity_kg": round(
                    edge["expected_productivity_kg"], 4
                ),
                "candidate_scope": edge["candidate_scope"],
                "cross_division": edge["cross_division"],
                "inferred_home_division": edge["inferred_home_division"],
                "experience_count": edge["experience_count"],
                "last_experience_date": edge["last_experience_date"],
                "field_assigned_employee_count": len(assigned_edges),
                "field_assigned_capacity_kg": round(assigned_capacity, 4),
                "field_under_kg": round(under_kg, 4),
                "field_over_kg": round(over_kg, 4),
                "solver_status": status_name,
                "operational_use_allowed": "NO",
            })

    duplicate_assignments = sum(
        count - 1 for count in employee_assignment_count.values() if count > 1
    )
    total_target = sum(row["target_crop_kg"] for row in field_rows)
    total_capacity = sum(row["assigned_capacity_kg"] for row in field_rows)
    total_under = sum(row["under_kg"] for row in field_rows)
    total_over = sum(row["over_kg"] for row in field_rows)
    fields_fully_covered = sum(
        1 for row in field_rows if row["field_status"] == "FULLY_COVERED"
    )

    estate_result = {
        "estate": estate_name,
        "scenario": scenario,
        "solver_status": status_name,
        "objective_value": (
            round(solver.ObjectiveValue(), 4)
            if status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE)
            else ""
        ),
        "best_bound": (
            round(solver.BestObjectiveBound(), 4)
            if status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE)
            else ""
        ),
        "wall_time_seconds": round(solver.WallTime(), 3),
        "employees_assigned": len(employee_assignment_count),
        "fields": len(field_rows),
        "fields_fully_covered": fields_fully_covered,
        "total_target_crop_kg": round(total_target, 4),
        "total_assigned_capacity_kg": round(total_capacity, 4),
        "total_under_kg": round(total_under, 4),
        "total_over_kg": round(total_over, 4),
        "coverage_pct": round(
            min(100.0, total_capacity / total_target * 100.0)
            if total_target > 0 else 100.0,
            2,
        ),
        "duplicate_employee_assignments": duplicate_assignments,
        "operational_status": OPERATIONAL_STATUS,
    }
    return assignment_rows, field_rows, estate_result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run estate-wise CP-SAT development allocation."
    )
    parser.add_argument("--scenario-run", required=True)
    parser.add_argument("--planning-run", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument(
        "--scenarios",
        choices=["EXPECTED", "CONSERVATIVE", "BOTH"],
        default="BOTH",
    )
    parser.add_argument("--time-limit-seconds", type=float, default=30.0)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()

    scenario_run = Path(args.scenario_run).resolve()
    planning_run = Path(args.planning_run).resolve()
    output_root = Path(args.output_root).resolve()

    candidate_path = (
        scenario_run
        / "candidates"
        / "all_employee_active_field_candidate_matrix.csv"
    )
    demand_path = (
        planning_run
        / "planning"
        / "field_required_plucker_assignments.csv"
    )

    for path in (candidate_path, demand_path):
        if not path.exists():
            raise SystemExit(f"Missing required input: {path}")

    candidate_rows = read_csv(candidate_path)
    demand_rows = read_csv(demand_path)
    preflight = validate_inputs(candidate_rows, demand_rows)

    if preflight["missing_candidate_fields"] > 0:
        raise SystemExit(
            f"Candidate coverage missing for "
            f"{preflight['missing_candidate_fields']} active fields."
        )
    if preflight["estates"] != 33:
        raise SystemExit(
            f"Expected 33 estates but found {preflight['estates']}."
        )

    if args.preflight_only:
        print(json.dumps({
            "status": "PASS_CP_SAT_PREFLIGHT",
            "package_version": VERSION,
            **preflight,
            "cp_sat_started": False,
            "rl_started": False,
        }, indent=2))
        return 0

    try:
        from ortools.sat.python import cp_model
    except ImportError as exc:
        raise SystemExit(
            "OR-Tools is not installed. Run: py -m pip install ortools"
        ) from exc

    planning_date = preflight["planning_date"]
    active_demand = [
        row for row in demand_rows
        if clean(row.get("date")) == planning_date
        and parse_int(row.get("recommended_plucker_assignments")) > 0
    ]
    active_candidates = [
        row for row in candidate_rows
        if clean(row.get("date")) == planning_date
    ]

    demand_by_estate: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    candidate_by_estate: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    estate_display: dict[str, str] = {}

    for row in active_demand:
        key = estate_key(row.get("estate", ""))
        demand_by_estate[key].append(row)
        estate_display[key] = clean(row.get("estate"))
    for row in active_candidates:
        key = estate_key(row.get("estate", ""))
        candidate_by_estate[key].append(row)

    scenarios = (
        ["EXPECTED", "CONSERVATIVE"]
        if args.scenarios == "BOTH"
        else [args.scenarios]
    )

    run_folder = output_root / datetime.now().strftime(
        "cp_sat_development_%Y%m%d_%H%M%S"
    )
    assignments_dir = run_folder / "assignments"
    quality_dir = run_folder / "quality"
    assignments_dir.mkdir(parents=True, exist_ok=True)
    quality_dir.mkdir(parents=True, exist_ok=True)

    all_assignment_rows: list[dict[str, Any]] = []
    all_field_rows: list[dict[str, Any]] = []
    all_estate_rows: list[dict[str, Any]] = []

    started = time.time()
    print(f"CP-SAT development run: {run_folder}")
    print(f"Planning date: {planning_date}")
    print(f"Scenarios: {', '.join(scenarios)}")
    print("Each employee can be assigned to at most one field per scenario.")
    print("No live allocation or RL training will run.")

    for scenario in scenarios:
        print("")
        print(f"SCENARIO: {scenario}")
        for index, key in enumerate(sorted(demand_by_estate), start=1):
            estate_name = estate_display[key]
            print(
                f"[{index}/33] Solving {estate_name}",
                flush=True,
            )
            assignment_rows, field_rows, estate_row = solve_estate(
                cp_model=cp_model,
                scenario=scenario,
                estate_name=estate_name,
                demand_rows=demand_by_estate[key],
                candidate_rows=candidate_by_estate.get(key, []),
                time_limit_seconds=args.time_limit_seconds,
                workers=args.workers,
            )
            all_assignment_rows.extend(assignment_rows)
            all_field_rows.extend(field_rows)
            all_estate_rows.append(estate_row)

    write_csv(
        assignments_dir / "cp_sat_employee_field_assignments.csv",
        all_assignment_rows,
        [
            "date", "scenario", "estate", "division", "field",
            "target_crop_kg", "employee_id", "expected_productivity_kg",
            "candidate_scope", "cross_division",
            "inferred_home_division", "experience_count",
            "last_experience_date", "field_assigned_employee_count",
            "field_assigned_capacity_kg", "field_under_kg",
            "field_over_kg", "solver_status",
            "operational_use_allowed",
        ],
    )
    write_csv(
        quality_dir / "cp_sat_field_results.csv",
        all_field_rows,
        [
            "date", "scenario", "estate", "division", "field",
            "target_crop_kg", "assignment_limit",
            "assigned_employee_count", "assigned_capacity_kg",
            "under_kg", "over_kg", "coverage_pct", "field_status",
            "solver_status", "operational_status",
        ],
    )
    write_csv(
        quality_dir / "cp_sat_estate_results.csv",
        all_estate_rows,
        [
            "estate", "scenario", "solver_status", "objective_value",
            "best_bound", "wall_time_seconds", "employees_assigned",
            "fields", "fields_fully_covered", "total_target_crop_kg",
            "total_assigned_capacity_kg", "total_under_kg",
            "total_over_kg", "coverage_pct",
            "duplicate_employee_assignments", "operational_status",
        ],
    )

    solver_failures = sum(
        1 for row in all_estate_rows
        if row["solver_status"] not in {"OPTIMAL", "FEASIBLE"}
    )
    duplicate_failures = sum(
        int(row["duplicate_employee_assignments"])
        for row in all_estate_rows
    )
    field_reconciliation_failures = sum(
        1 for row in all_field_rows
        if abs(
            row["assigned_capacity_kg"]
            + row["under_kg"]
            - row["over_kg"]
            - row["target_crop_kg"]
        ) > 0.15
    )

    summary = {
        "status": (
            "PASS_CP_SAT_DEVELOPMENT_OUTPUTS"
            if solver_failures == 0
            and duplicate_failures == 0
            and field_reconciliation_failures == 0
            else "PASS_WITH_CP_SAT_DEVELOPMENT_WARNINGS"
        ),
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "scenario_run": str(scenario_run),
        "planning_run": str(planning_run),
        "planning_date": planning_date,
        "scenarios": scenarios,
        "estates_solved": len(all_estate_rows),
        "assignment_rows": len(all_assignment_rows),
        "field_result_rows": len(all_field_rows),
        "solver_failures": solver_failures,
        "duplicate_employee_assignment_failures": duplicate_failures,
        "field_reconciliation_failures": field_reconciliation_failures,
        "operational_status": OPERATIONAL_STATUS,
        "live_allocator_changed": False,
        "rl_started": False,
        "duration_minutes": round((time.time() - started) / 60.0, 2),
        "important_interpretation": [
            "The optimizer matches employee picking capacity to field crop across the whole estate.",
            "It minimizes uncovered crop first, then excess capacity.",
            "For equally good crop matches, fewer employees are preferred.",
            "Exact-field and same-division candidates are preferred over cross-division fallbacks.",
            "Each employee is assigned to at most one field per scenario.",
            "These are development simulations based on provisional all-employee availability assumptions.",
        ],
    }

    (run_folder / "run_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    (run_folder / "README.txt").write_text(
        "\n".join([
            "TTE CP-SAT DEVELOPMENT ALLOCATION v7.0.0",
            "",
            f"Planning date: {planning_date}",
            f"Scenarios: {', '.join(scenarios)}",
            "",
            "This is development simulation only.",
            "No assignment may be used operationally without management confirmation.",
            "RL training has not started.",
        ]) + "\n",
        encoding="utf-8",
    )
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "LATEST_CP_SAT_DEVELOPMENT_RUN.txt").write_text(
        str(run_folder), encoding="utf-8"
    )

    print("")
    print("CP-SAT DEVELOPMENT ALLOCATION FINISHED")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
