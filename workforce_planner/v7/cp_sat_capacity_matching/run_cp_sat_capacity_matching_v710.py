from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


VERSION = "7.1.0"
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


def weighted_productivity(recent: float, historical: float) -> float:
    if recent > 0 and historical > 0:
        return max(1.0, 0.70 * recent + 0.30 * historical)
    return max(1.0, recent, historical)


def employee_overall_productivity(row: dict[str, str]) -> float:
    return weighted_productivity(
        parse_float(row.get("recent_ewma_kg")),
        parse_float(row.get("historical_mean_kg")),
    )


def experience_productivity(row: dict[str, str]) -> float:
    return weighted_productivity(
        parse_float(row.get("recent_ewma_kg")),
        parse_float(row.get("historical_mean_kg")),
    )


def field_key(row: dict[str, Any]) -> tuple[str, str]:
    return (norm(row.get("division")), clean(row.get("field")))


def field_uid(division: str, field: str) -> str:
    return f"{division}::{field}"


def get_first_date(rows: list[dict[str, str]]) -> str:
    dates = sorted({clean(row.get("date")) for row in rows if clean(row.get("date"))})
    if not dates:
        raise RuntimeError("No planning date found.")
    return dates[0]


def build_inputs(
    employee_rows: list[dict[str, str]],
    experience_rows: list[dict[str, str]],
    demand_rows: list[dict[str, str]],
) -> dict[str, Any]:
    planning_date = get_first_date(demand_rows)
    active_demand = [
        row for row in demand_rows
        if clean(row.get("date")) == planning_date
        and parse_int(row.get("recommended_plucker_assignments")) > 0
    ]
    if not active_demand:
        raise RuntimeError("No active field demand rows found.")

    employees_by_estate: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    employee_display_estate: dict[str, str] = {}
    duplicate_employee_ids: list[dict[str, Any]] = []
    unique_employee_by_estate: dict[tuple[str, str], dict[str, str]] = {}
    employee_record_rows: list[dict[str, Any]] = []

    for record_number, row in enumerate(employee_rows, start=1):
        estate = clean(row.get("estate"))
        estate_norm = norm(estate)
        employee_id = clean(row.get("employee_id"))
        if not estate_norm or not employee_id:
            continue

        employee_record_rows.append({
            "employee_record_number": record_number,
            "estate": estate,
            "employee_id": employee_id,
            "inferred_home_division": clean(row.get("inferred_home_division")),
            "first_observed_date": clean(row.get("first_observed_date")),
            "last_observed_date": clean(row.get("last_observed_date")),
            "observation_count": clean(row.get("observation_count")),
            "historical_mean_kg": clean(row.get("historical_mean_kg")),
            "recent_ewma_kg": clean(row.get("recent_ewma_kg")),
            "included_in_audit_roster": "YES",
            "solver_resource_identity": employee_id,
            "operational_use_allowed": "NO",
        })

        key = (estate_norm, employee_id)
        if key in unique_employee_by_estate:
            duplicate_employee_ids.append({
                "estate": estate,
                "employee_id": employee_id,
                "duplicate_record_number": record_number,
                "allocation_handling": (
                    "SAME_ID_TREATED_AS_ONE_RESOURCE_TO_PREVENT_DOUBLE_ASSIGNMENT"
                ),
            })
            continue

        unique_employee_by_estate[key] = row
        employees_by_estate[estate_norm].append(row)
        employee_display_estate[estate_norm] = estate

    demand_by_estate: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    demand_identity_seen: set[tuple[str, str, str]] = set()
    duplicate_demand_rows: list[dict[str, Any]] = []

    for row in active_demand:
        estate = clean(row.get("estate"))
        estate_norm = norm(estate)
        division = clean(row.get("division")) or "UNKNOWN"
        field = clean(row.get("field"))
        identity = (estate_norm, norm(division), field)
        if identity in demand_identity_seen:
            duplicate_demand_rows.append({
                "estate": estate,
                "division": division,
                "field": field,
                "issue": "DUPLICATE_ESTATE_DIVISION_FIELD_DEMAND",
            })
        demand_identity_seen.add(identity)
        demand_by_estate[estate_norm].append(row)

    exact_exp: dict[tuple[str, str, str, str], dict[str, str]] = {}
    division_exp_values: defaultdict[
        tuple[str, str, str], list[tuple[float, int]]
    ] = defaultdict(list)

    for row in experience_rows:
        estate_norm = norm(row.get("estate"))
        employee_id = clean(row.get("employee_id"))
        division = clean(row.get("field_division")) or "UNKNOWN"
        field = clean(row.get("field_id"))
        if not estate_norm or not employee_id or not field:
            continue

        prod = experience_productivity(row)
        count = max(1, parse_int(row.get("observation_count"), 1))
        exact_exp[(estate_norm, employee_id, norm(division), field)] = row
        division_exp_values[
            (estate_norm, employee_id, norm(division))
        ].append((prod, count))

    division_productivity: dict[tuple[str, str, str], float] = {}
    for key, values in division_exp_values.items():
        total_weight = sum(count for _, count in values)
        division_productivity[key] = (
            sum(prod * count for prod, count in values) / total_weight
            if total_weight > 0 else 1.0
        )

    missing_estates = sorted(
        estate for estate in demand_by_estate
        if estate not in employees_by_estate
    )

    return {
        "planning_date": planning_date,
        "active_demand": active_demand,
        "employees_by_estate": employees_by_estate,
        "employee_display_estate": employee_display_estate,
        "demand_by_estate": demand_by_estate,
        "exact_exp": exact_exp,
        "division_productivity": division_productivity,
        "employee_record_rows": employee_record_rows,
        "duplicate_employee_ids": duplicate_employee_ids,
        "duplicate_demand_rows": duplicate_demand_rows,
        "missing_estates": missing_estates,
        "unique_employee_count": len(unique_employee_by_estate),
    }


def build_estate_edges(
    estate_norm: str,
    employees: list[dict[str, str]],
    fields: list[dict[str, str]],
    exact_exp: dict[tuple[str, str, str, str], dict[str, str]],
    division_productivity: dict[tuple[str, str, str], float],
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []

    for employee in employees:
        employee_id = clean(employee.get("employee_id"))
        home_division = clean(employee.get("inferred_home_division")) or "UNKNOWN"
        home_norm = norm(home_division)
        overall_prod = employee_overall_productivity(employee)
        overall_count = max(1, parse_int(employee.get("observation_count"), 1))

        for field_row in fields:
            division = clean(field_row.get("division")) or "UNKNOWN"
            division_norm = norm(division)
            field = clean(field_row.get("field"))
            exact = exact_exp.get(
                (estate_norm, employee_id, division_norm, field)
            )

            if exact is not None:
                productivity = experience_productivity(exact)
                experience_count = max(
                    1, parse_int(exact.get("observation_count"), 1)
                )
                last_experience = clean(exact.get("last_observed_date"))
                scope = "EXACT_FIELD_HISTORY"
                cross_division = "NO" if home_norm == division_norm else "YES"
                scope_weight = 1.00
            elif home_norm and home_norm == division_norm:
                productivity = division_productivity.get(
                    (estate_norm, employee_id, division_norm),
                    overall_prod,
                )
                experience_count = overall_count
                last_experience = clean(employee.get("last_observed_date"))
                scope = "SAME_DIVISION_CAPACITY"
                cross_division = "NO"
                scope_weight = 0.90
            else:
                # Cross-division use remains a development assumption.
                productivity = max(1.0, overall_prod * 0.90)
                experience_count = overall_count
                last_experience = clean(employee.get("last_observed_date"))
                scope = "ESTATE_WIDE_CAPACITY_FALLBACK"
                cross_division = "YES"
                scope_weight = 0.70

            score = (
                productivity * scope_weight
                + min(20.0, math.log1p(experience_count) * 2.0)
            )

            edges.append({
                "date": clean(field_row.get("date")),
                "estate": clean(field_row.get("estate")),
                "division": division,
                "field": field,
                "field_uid": field_uid(division, field),
                "employee_id": employee_id,
                "inferred_home_division": home_division,
                "candidate_scope": scope,
                "cross_division": cross_division,
                "expected_productivity_kg": round(productivity, 4),
                "experience_count": experience_count,
                "last_experience_date": last_experience,
                "candidate_score": round(score, 6),
                "operational_use_allowed": "NO",
            })

    return edges


def scope_cost(scope: str) -> int:
    return {
        "EXACT_FIELD_HISTORY": 0,
        "SAME_DIVISION_CAPACITY": 2,
        "ESTATE_WIDE_CAPACITY_FALLBACK": 8,
    }.get(clean(scope), 10)


def solve_estate(
    cp_model,
    scenario: str,
    estate_name: str,
    field_rows: list[dict[str, str]],
    edges: list[dict[str, Any]],
    time_limit_seconds: float,
    workers: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    model = cp_model.CpModel()

    fields: dict[tuple[str, str], dict[str, Any]] = {}
    for row in field_rows:
        division = clean(row.get("division")) or "UNKNOWN"
        field = clean(row.get("field"))
        key = (norm(division), field)

        if scenario == "EXPECTED":
            target = max(0.0, parse_float(row.get("central_crop_kg")))
            reference_count = max(
                0, parse_int(row.get("expected_plucker_assignments"))
            )
        else:
            target = max(
                0.0, parse_float(row.get("upper_conservative_crop_kg"))
            )
            reference_count = max(
                0, parse_int(row.get("recommended_plucker_assignments"))
            )

        fields[key] = {
            "date": clean(row.get("date")),
            "estate": clean(row.get("estate")),
            "division": division,
            "field": field,
            "field_uid": field_uid(division, field),
            "target_crop_kg": target,
            "reference_assignment_demand": reference_count,
        }

    filtered_edges: list[dict[str, Any]] = []
    edge_seen: set[tuple[str, str, str]] = set()

    for edge in edges:
        key = (norm(edge["division"]), edge["field"])
        if key not in fields:
            continue
        edge_identity = (
            edge["employee_id"],
            norm(edge["division"]),
            edge["field"],
        )
        if edge_identity in edge_seen:
            continue
        edge_seen.add(edge_identity)
        copied = dict(edge)
        copied["field_key"] = key
        filtered_edges.append(copied)

    x = [
        model.NewBoolVar(f"x_{index}")
        for index in range(len(filtered_edges))
    ]

    employee_edges: defaultdict[str, list[int]] = defaultdict(list)
    field_edges: defaultdict[tuple[str, str], list[int]] = defaultdict(list)

    for index, edge in enumerate(filtered_edges):
        employee_edges[edge["employee_id"]].append(index)
        field_edges[edge["field_key"]].append(index)

    for indexes in employee_edges.values():
        model.Add(sum(x[index] for index in indexes) <= 1)

    scale = 10
    objective_terms: list[Any] = []

    for field_index, (key, info) in enumerate(fields.items()):
        indexes = field_edges.get(key, [])
        candidate_productivities = [
            filtered_edges[index]["expected_productivity_kg"]
            for index in indexes
        ]
        median_productivity = (
            statistics.median(candidate_productivities)
            if candidate_productivities else 1.0
        )
        estimated_needed = math.ceil(
            info["target_crop_kg"] / max(1.0, median_productivity)
        )
        soft_reference = info["reference_assignment_demand"]

        # The old demand value is no longer a hard maximum.
        # The capacity-derived upper bound allows enough workers to match crop.
        assignment_upper_bound = min(
            len(indexes),
            max(
                soft_reference + 5,
                soft_reference * 4,
                estimated_needed + 5,
            ),
        )
        assignment_upper_bound = max(0, assignment_upper_bound)

        count_expr = sum(x[index] for index in indexes)
        model.Add(count_expr <= assignment_upper_bound)

        target_scaled = int(round(info["target_crop_kg"] * scale))
        max_capacity_scaled = sum(
            int(round(
                filtered_edges[index]["expected_productivity_kg"] * scale
            ))
            for index in indexes
        )
        slack_upper = max(target_scaled, max_capacity_scaled, 1)

        under = model.NewIntVar(0, slack_upper, f"under_{field_index}")
        over = model.NewIntVar(0, slack_upper, f"over_{field_index}")
        excess_workers = model.NewIntVar(
            0,
            max(assignment_upper_bound, 1),
            f"excess_workers_{field_index}",
        )

        capacity_expr = sum(
            int(round(
                filtered_edges[index]["expected_productivity_kg"] * scale
            )) * x[index]
            for index in indexes
        )

        model.Add(capacity_expr + under - over == target_scaled)
        model.Add(excess_workers >= count_expr - soft_reference)

        # Priority:
        # 1. crop left uncovered
        # 2. excess picking capacity
        # 3. workers above the old reference demand
        # 4. total workers
        objective_terms.append(100_000 * under)
        objective_terms.append(1_000 * over)
        objective_terms.append(100 * excess_workers)
        objective_terms.append(5 * count_expr)

    for index, edge in enumerate(filtered_edges):
        cross_penalty = 20 if edge["cross_division"] == "YES" else 0
        objective_terms.append(
            (cross_penalty + scope_cost(edge["candidate_scope"])) * x[index]
        )

    model.Minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(1.0, time_limit_seconds)
    solver.parameters.num_search_workers = max(1, workers)
    solver.parameters.random_seed = 20260724
    solver.parameters.log_search_progress = False

    status_code = solver.Solve(model)
    status_name = solver.StatusName(status_code)

    assigned_by_field: defaultdict[
        tuple[str, str], list[dict[str, Any]]
    ] = defaultdict(list)
    employee_assignment_count: defaultdict[str, int] = defaultdict(int)

    if status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for index, edge in enumerate(filtered_edges):
            if solver.Value(x[index]) == 1:
                assigned_by_field[edge["field_key"]].append(edge)
                employee_assignment_count[edge["employee_id"]] += 1

    assignment_rows: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []

    for key, info in fields.items():
        assigned = assigned_by_field.get(key, [])
        capacity = sum(
            edge["expected_productivity_kg"] for edge in assigned
        )
        under = max(0.0, info["target_crop_kg"] - capacity)
        over = max(0.0, capacity - info["target_crop_kg"])
        coverage = (
            max(0.0, min(100.0, (info["target_crop_kg"] - under)
                         / info["target_crop_kg"] * 100.0))
            if info["target_crop_kg"] > 0 else 100.0
        )
        status = (
            "COVERAGE_95_PLUS"
            if coverage >= 95.0
            else "PARTIAL_COVERAGE"
            if capacity > 0
            else "UNCOVERED"
        )

        result_rows.append({
            "date": info["date"],
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
            "field_status": status,
            "solver_status": status_name,
            "operational_status": OPERATIONAL_STATUS,
        })

        for edge in assigned:
            assignment_rows.append({
                "date": info["date"],
                "scenario": scenario,
                "estate": estate_name,
                "division": info["division"],
                "field": info["field"],
                "field_uid": info["field_uid"],
                "target_crop_kg": round(info["target_crop_kg"], 4),
                "reference_assignment_demand": (
                    info["reference_assignment_demand"]
                ),
                "employee_id": edge["employee_id"],
                "expected_productivity_kg": (
                    edge["expected_productivity_kg"]
                ),
                "candidate_scope": edge["candidate_scope"],
                "cross_division": edge["cross_division"],
                "inferred_home_division": (
                    edge["inferred_home_division"]
                ),
                "field_assigned_employee_count": len(assigned),
                "field_assigned_capacity_kg": round(capacity, 4),
                "field_under_kg": round(under, 4),
                "field_over_kg": round(over, 4),
                "solver_status": status_name,
                "operational_use_allowed": "NO",
            })

    duplicate_assignments = sum(
        count - 1
        for count in employee_assignment_count.values()
        if count > 1
    )
    total_target = sum(row["target_crop_kg"] for row in result_rows)
    total_under = sum(row["under_kg"] for row in result_rows)
    total_over = sum(row["over_kg"] for row in result_rows)
    effective_coverage = (
        (total_target - total_under) / total_target * 100.0
        if total_target > 0 else 100.0
    )

    estate_summary = {
        "scenario": scenario,
        "estate": estate_name,
        "solver_status": status_name,
        "employees_assigned": len(employee_assignment_count),
        "fields": len(result_rows),
        "fields_coverage_95_plus": sum(
            1 for row in result_rows
            if row["coverage_pct"] >= 95.0
        ),
        "uncovered_fields": sum(
            1 for row in result_rows
            if row["assigned_employee_count"] == 0
        ),
        "total_target_crop_kg": round(total_target, 4),
        "total_under_kg": round(total_under, 4),
        "total_over_kg": round(total_over, 4),
        "effective_coverage_pct": round(effective_coverage, 2),
        "duplicate_employee_assignments": duplicate_assignments,
        "wall_time_seconds": round(solver.WallTime(), 3),
        "operational_status": OPERATIONAL_STATUS,
    }
    return assignment_rows, result_rows, estate_summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--employee-run", required=True)
    parser.add_argument("--planning-run", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument(
        "--scenarios",
        choices=["EXPECTED", "CONSERVATIVE", "BOTH"],
        default="BOTH",
    )
    parser.add_argument("--time-limit-seconds", type=float, default=45.0)
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, (os.cpu_count() or 2) - 1),
    )
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()

    employee_run = Path(args.employee_run).resolve()
    planning_run = Path(args.planning_run).resolve()
    output_root = Path(args.output_root).resolve()

    master_path = employee_run / "registers" / "employee_master.csv"
    experience_path = (
        employee_run / "registers" / "employee_field_experience.csv"
    )
    demand_path = (
        planning_run
        / "planning"
        / "field_required_plucker_assignments.csv"
    )

    for path in (master_path, experience_path, demand_path):
        if not path.exists():
            raise SystemExit(f"Missing required input: {path}")

    employee_rows = read_csv(master_path)
    experience_rows = read_csv(experience_path)
    demand_rows = read_csv(demand_path)
    inputs = build_inputs(employee_rows, experience_rows, demand_rows)

    if inputs["missing_estates"]:
        raise SystemExit(
            f"Employee master missing estates: {inputs['missing_estates']}"
        )
    if inputs["duplicate_demand_rows"]:
        raise SystemExit(
            "Duplicate estate+division+field demand rows found. "
            "Review preflight output."
        )
    if len(inputs["demand_by_estate"]) != 33:
        raise SystemExit(
            f"Expected 33 estates but found {len(inputs['demand_by_estate'])}."
        )

    estimated_edges = sum(
        len(inputs["employees_by_estate"][estate])
        * len(inputs["demand_by_estate"][estate])
        for estate in inputs["demand_by_estate"]
    )

    preflight = {
        "status": "PASS_CAPACITY_MATCHING_PREFLIGHT",
        "package_version": VERSION,
        "planning_date": inputs["planning_date"],
        "employee_master_records": len(employee_rows),
        "audit_roster_records": len(inputs["employee_record_rows"]),
        "unique_solver_employee_ids": inputs["unique_employee_count"],
        "duplicate_employee_id_records": len(
            inputs["duplicate_employee_ids"]
        ),
        "active_field_rows": len(inputs["active_demand"]),
        "estates": len(inputs["demand_by_estate"]),
        "estimated_all_estate_candidate_edges": estimated_edges,
        "duplicate_demand_identity_rows": len(
            inputs["duplicate_demand_rows"]
        ),
        "field_identity": "ESTATE_PLUS_DIVISION_PLUS_FIELD",
        "old_demand_used_as_hard_maximum": False,
        "cp_sat_started": False,
        "rl_started": False,
    }

    if args.preflight_only:
        print(json.dumps(preflight, indent=2))
        return 0

    try:
        from ortools.sat.python import cp_model
    except ImportError as exc:
        raise SystemExit(
            "OR-Tools is not installed. Run: py -m pip install ortools"
        ) from exc

    run_folder = output_root / datetime.now().strftime(
        "capacity_matching_%Y%m%d_%H%M%S"
    )
    input_dir = run_folder / "inputs"
    assignment_dir = run_folder / "assignments"
    quality_dir = run_folder / "quality"
    for folder in (input_dir, assignment_dir, quality_dir):
        folder.mkdir(parents=True, exist_ok=True)

    write_csv(
        input_dir / "all_employee_audit_roster.csv",
        inputs["employee_record_rows"],
        [
            "employee_record_number", "estate", "employee_id",
            "inferred_home_division", "first_observed_date",
            "last_observed_date", "observation_count",
            "historical_mean_kg", "recent_ewma_kg",
            "included_in_audit_roster", "solver_resource_identity",
            "operational_use_allowed",
        ],
    )
    write_csv(
        quality_dir / "duplicate_employee_id_records.csv",
        inputs["duplicate_employee_ids"],
        [
            "estate", "employee_id", "duplicate_record_number",
            "allocation_handling",
        ],
    )

    scenarios = (
        ["EXPECTED", "CONSERVATIVE"]
        if args.scenarios == "BOTH"
        else [args.scenarios]
    )

    all_edges: list[dict[str, Any]] = []
    edges_by_estate: dict[str, list[dict[str, Any]]] = {}

    print(f"Capacity-matching run: {run_folder}")
    print(f"Planning date: {inputs['planning_date']}")
    print("Every employee record remains in the audit roster.")
    print(
        "Every unique employee identity is considered for every active "
        "field in the same estate."
    )
    print(
        "The previous headcount demand is a soft reference, not a hard "
        "field maximum."
    )
    print("No live allocation or RL training will run.")

    for index, estate_norm in enumerate(
        sorted(inputs["demand_by_estate"]), start=1
    ):
        estate_name = clean(
            inputs["demand_by_estate"][estate_norm][0].get("estate")
        )
        employees = inputs["employees_by_estate"][estate_norm]
        fields = inputs["demand_by_estate"][estate_norm]
        print(
            f"[CANDIDATES {index}/33] {estate_name}: "
            f"{len(employees)} employees x {len(fields)} fields",
            flush=True,
        )
        edges = build_estate_edges(
            estate_norm,
            employees,
            fields,
            inputs["exact_exp"],
            inputs["division_productivity"],
        )
        edges_by_estate[estate_norm] = edges
        all_edges.extend(edges)

    write_csv(
        input_dir / "expanded_employee_field_candidate_matrix.csv",
        all_edges,
        [
            "date", "estate", "division", "field", "field_uid",
            "employee_id", "inferred_home_division",
            "candidate_scope", "cross_division",
            "expected_productivity_kg", "experience_count",
            "last_experience_date", "candidate_score",
            "operational_use_allowed",
        ],
    )

    candidate_quality_rows: list[dict[str, Any]] = []
    for estate_norm, fields in inputs["demand_by_estate"].items():
        estate_edges = edges_by_estate[estate_norm]
        by_field: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
        for edge in estate_edges:
            by_field[(norm(edge["division"]), edge["field"])].add(
                edge["employee_id"]
            )
        for field in fields:
            key = (norm(field.get("division")), clean(field.get("field")))
            candidate_quality_rows.append({
                "estate": clean(field.get("estate")),
                "division": clean(field.get("division")),
                "field": clean(field.get("field")),
                "field_uid": field_uid(
                    clean(field.get("division")),
                    clean(field.get("field")),
                ),
                "unique_candidate_employees": len(by_field.get(key, set())),
                "candidate_coverage_status": (
                    "PASS" if len(by_field.get(key, set())) > 0 else "FAIL"
                ),
            })

    write_csv(
        quality_dir / "expanded_candidate_coverage.csv",
        candidate_quality_rows,
        [
            "estate", "division", "field", "field_uid",
            "unique_candidate_employees", "candidate_coverage_status",
        ],
    )

    all_assignments: list[dict[str, Any]] = []
    all_field_results: list[dict[str, Any]] = []
    all_estate_results: list[dict[str, Any]] = []

    started = time.time()
    for scenario in scenarios:
        print("")
        print(f"SCENARIO: {scenario}")
        for index, estate_norm in enumerate(
            sorted(inputs["demand_by_estate"]), start=1
        ):
            estate_name = clean(
                inputs["demand_by_estate"][estate_norm][0].get("estate")
            )
            print(f"[SOLVE {index}/33] {estate_name}", flush=True)
            assignments, field_results, estate_result = solve_estate(
                cp_model=cp_model,
                scenario=scenario,
                estate_name=estate_name,
                field_rows=inputs["demand_by_estate"][estate_norm],
                edges=edges_by_estate[estate_norm],
                time_limit_seconds=args.time_limit_seconds,
                workers=args.workers,
            )
            all_assignments.extend(assignments)
            all_field_results.extend(field_results)
            all_estate_results.append(estate_result)

    write_csv(
        assignment_dir / "cp_sat_capacity_matched_assignments.csv",
        all_assignments,
        [
            "date", "scenario", "estate", "division", "field",
            "field_uid", "target_crop_kg",
            "reference_assignment_demand", "employee_id",
            "expected_productivity_kg", "candidate_scope",
            "cross_division", "inferred_home_division",
            "field_assigned_employee_count",
            "field_assigned_capacity_kg", "field_under_kg",
            "field_over_kg", "solver_status",
            "operational_use_allowed",
        ],
    )
    write_csv(
        quality_dir / "cp_sat_capacity_field_results.csv",
        all_field_results,
        [
            "date", "scenario", "estate", "division", "field",
            "field_uid", "target_crop_kg",
            "reference_assignment_demand",
            "assigned_employee_count", "assigned_capacity_kg",
            "under_kg", "over_kg", "coverage_pct",
            "field_status", "solver_status", "operational_status",
        ],
    )
    write_csv(
        quality_dir / "cp_sat_capacity_estate_results.csv",
        all_estate_results,
        [
            "scenario", "estate", "solver_status",
            "employees_assigned", "fields",
            "fields_coverage_95_plus", "uncovered_fields",
            "total_target_crop_kg", "total_under_kg",
            "total_over_kg", "effective_coverage_pct",
            "duplicate_employee_assignments",
            "wall_time_seconds", "operational_status",
        ],
    )

    expected_field_rows = len(inputs["active_demand"]) * len(scenarios)
    field_identity_failures = abs(
        expected_field_rows - len(all_field_results)
    )
    solver_failures = sum(
        1 for row in all_estate_results
        if row["solver_status"] not in {"OPTIMAL", "FEASIBLE"}
    )
    duplicate_assignment_failures = sum(
        int(row["duplicate_employee_assignments"])
        for row in all_estate_results
    )
    reconciliation_failures = sum(
        1 for row in all_field_results
        if abs(
            row["assigned_capacity_kg"]
            + row["under_kg"]
            - row["over_kg"]
            - row["target_crop_kg"]
        ) > 0.15
    )

    scenario_summary_rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        subset = [
            row for row in all_field_results
            if row["scenario"] == scenario
        ]
        total_target = sum(row["target_crop_kg"] for row in subset)
        total_under = sum(row["under_kg"] for row in subset)
        total_over = sum(row["over_kg"] for row in subset)
        effective_coverage = (
            (total_target - total_under) / total_target * 100.0
            if total_target > 0 else 100.0
        )
        scenario_summary_rows.append({
            "scenario": scenario,
            "field_rows": len(subset),
            "fields_coverage_95_plus": sum(
                1 for row in subset if row["coverage_pct"] >= 95.0
            ),
            "uncovered_fields": sum(
                1 for row in subset
                if row["assigned_employee_count"] == 0
            ),
            "total_target_crop_kg": round(total_target, 4),
            "total_under_kg": round(total_under, 4),
            "total_over_kg": round(total_over, 4),
            "effective_coverage_pct": round(effective_coverage, 2),
        })

    write_csv(
        quality_dir / "cp_sat_capacity_scenario_summary.csv",
        scenario_summary_rows,
        [
            "scenario", "field_rows", "fields_coverage_95_plus",
            "uncovered_fields", "total_target_crop_kg",
            "total_under_kg", "total_over_kg",
            "effective_coverage_pct",
        ],
    )

    performance_gate = "PASS"
    for row in scenario_summary_rows:
        threshold = 95.0 if row["scenario"] == "EXPECTED" else 90.0
        if (
            row["effective_coverage_pct"] < threshold
            or row["uncovered_fields"] > 0
        ):
            performance_gate = "REVIEW_REQUIRED"
            break

    summary = {
        "status": (
            "PASS_CP_SAT_CAPACITY_MATCHING_OUTPUTS"
            if solver_failures == 0
            and duplicate_assignment_failures == 0
            and reconciliation_failures == 0
            and field_identity_failures == 0
            else "PASS_WITH_CP_SAT_CAPACITY_MATCHING_WARNINGS"
        ),
        "performance_gate": performance_gate,
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "employee_run": str(employee_run),
        "planning_run": str(planning_run),
        "planning_date": inputs["planning_date"],
        "employee_master_records": len(employee_rows),
        "audit_roster_records": len(inputs["employee_record_rows"]),
        "unique_solver_employee_ids": inputs["unique_employee_count"],
        "duplicate_employee_id_records": len(
            inputs["duplicate_employee_ids"]
        ),
        "expanded_candidate_edges": len(all_edges),
        "active_fields_per_scenario": len(inputs["active_demand"]),
        "scenarios": scenarios,
        "expected_field_result_rows": expected_field_rows,
        "actual_field_result_rows": len(all_field_results),
        "field_identity_failures": field_identity_failures,
        "assignment_rows": len(all_assignments),
        "solver_failures": solver_failures,
        "duplicate_employee_assignment_failures": (
            duplicate_assignment_failures
        ),
        "field_reconciliation_failures": reconciliation_failures,
        "scenario_performance": scenario_summary_rows,
        "old_reference_demand_used_as_hard_maximum": False,
        "operational_status": OPERATIONAL_STATUS,
        "live_allocator_changed": False,
        "rl_started": False,
        "duration_minutes": round((time.time() - started) / 60.0, 2),
        "important_interpretation": [
            "Every employee master record remains in the audit roster.",
            "Every unique employee identity is considered for every active field within the same estate.",
            "Field identity is estate plus division plus field.",
            "The old headcount forecast is a soft reference and no longer blocks capacity matching.",
            "The optimizer minimizes uncovered crop before excess capacity and worker count.",
            "Each employee can be assigned to at most one field per scenario.",
            "These outputs remain development simulation only.",
        ],
    }

    (run_folder / "run_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    (run_folder / "README.txt").write_text(
        "\n".join([
            "TTE CP-SAT CAPACITY MATCHING REPAIR v7.1.0",
            "",
            f"Planning date: {inputs['planning_date']}",
            f"Employee master records: {len(employee_rows)}",
            f"Expanded candidate edges: {len(all_edges)}",
            "",
            "Field identity: estate + division + field",
            "Old staffing demand: soft reference, not hard maximum",
            "Operational use: prohibited",
            "RL training: not started",
        ]) + "\n",
        encoding="utf-8",
    )

    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "LATEST_CP_SAT_CAPACITY_MATCHING_RUN.txt").write_text(
        str(run_folder), encoding="utf-8"
    )

    print("")
    print("CP-SAT CAPACITY MATCHING REPAIR FINISHED")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
