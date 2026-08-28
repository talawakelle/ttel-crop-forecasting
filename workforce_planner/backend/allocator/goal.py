from __future__ import annotations

from dataclasses import replace
from math import ceil
from statistics import median
from typing import Any
import os
import time

from .data import Scenario, WorkforceData, build_plan
from .optimizer import KG_SCALE, optimizer_runtime


def _solver(cp_model, scenario: Scenario, seconds: float, search_workers: int):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.25, float(seconds))
    solver.parameters.num_search_workers = max(1, min(search_workers, os.cpu_count() or 1))
    solver.parameters.random_seed = int(scenario.seed) % 2_147_483_647
    solver.parameters.log_search_progress = False
    return solver


def _status_name(solver, status: int) -> str:
    try:
        return str(solver.StatusName(status)).upper()
    except TypeError:
        return str(solver.StatusName()).upper()


def _full_employee_pool(
    data: WorkforceData,
    scenario: Scenario,
    *,
    allow_cross_division: bool,
) -> list[str]:
    source_day = data.day_by_date[scenario.template_date]
    employee_ids = [
        employee_id
        for employee_id in source_day["available_employee_ids"]
        if employee_id in data.employee_by_id
    ]
    if scenario.division and not allow_cross_division:
        employee_ids = [
            employee_id
            for employee_id in employee_ids
            if data.employee_by_id[employee_id].home_division == scenario.division
        ]
    return sorted(employee_ids)


def _goal_staffing_plan(
    data: WorkforceData,
    scenario: Scenario,
    *,
    current_employee_ids: set[str],
    goal_coverage_pct: float,
    allow_cross_division: bool,
    time_limit_seconds: float,
) -> dict[str, Any]:
    runtime = optimizer_runtime()
    if not runtime["available"]:
        return {
            "available": False,
            "error": runtime["error"] or "OR-Tools CP-SAT is unavailable",
        }

    from ortools.sat.python import cp_model

    started = time.perf_counter()
    employee_ids = _full_employee_pool(
        data,
        scenario,
        allow_cross_division=allow_cross_division,
    )
    full_scenario = replace(
        scenario,
        employee_ids=employee_ids,
        attendance_rate=1.0,
        same_division_only=not allow_cross_division,
    )
    fields = list(full_scenario.demand_kg)
    total_target = max(1, int(round(sum(full_scenario.demand_kg.values()) * KG_SCALE)))
    goal_fulfilled = min(
        total_target,
        int(ceil(total_target * float(goal_coverage_pct) / 100.0)),
    )
    prediction_map = data.prediction_map(
        employee_ids,
        fields,
        full_scenario.planning_date,
    )
    # Goal analysis may run twice (home-division, then flexible divisions) after
    # the ordinary optimizer. A deterministic single CP-SAT worker avoids native
    # worker-pool contention and is sufficient for this small estate model.
    search_workers = 1

    model = cp_model.CpModel()
    variables: dict[tuple[str, str], Any] = {}
    predictions: dict[tuple[str, str], int] = {}
    employee_variables: dict[str, list[Any]] = {employee_id: [] for employee_id in employee_ids}
    field_variables: dict[str, list[Any]] = {field_id: [] for field_id in fields}

    for employee_id in employee_ids:
        employee = data.employee_by_id[employee_id]
        for field_id in fields:
            field = data.field_by_id[field_id]
            if full_scenario.same_division_only and employee.home_division != field.division:
                continue
            variable = model.NewBoolVar(f"goal_assign_{employee_id}_{field_id}")
            variables[(employee_id, field_id)] = variable
            predictions[(employee_id, field_id)] = int(
                round(prediction_map[(employee_id, field_id)] * KG_SCALE)
            )
            employee_variables[employee_id].append(variable)
            field_variables[field_id].append(variable)

    for choices in employee_variables.values():
        if choices:
            model.Add(sum(choices) <= 1)

    fulfilled_variables: dict[str, Any] = {}
    for field_id in fields:
        choices = field_variables[field_id]
        model.Add(sum(choices) <= int(full_scenario.capacity[field_id]))
        maximum_production = sum(
            predictions[(employee_id, field_id)]
            for employee_id in employee_ids
            if (employee_id, field_id) in variables
        )
        target = int(round(float(full_scenario.demand_kg[field_id]) * KG_SCALE))
        produced = model.NewIntVar(0, maximum_production, f"goal_produced_{field_id}")
        fulfilled = model.NewIntVar(0, target, f"goal_fulfilled_{field_id}")
        model.Add(
            produced
            == sum(
                predictions[(employee_id, field_id)] * variables[(employee_id, field_id)]
                for employee_id in employee_ids
                if (employee_id, field_id) in variables
            )
        )
        model.Add(fulfilled <= produced)
        fulfilled_variables[field_id] = fulfilled

    total_fulfilled = sum(fulfilled_variables.values())
    credited = model.NewIntVar(0, goal_fulfilled, "goal_credited")
    model.Add(credited <= total_fulfilled)

    extra_variables = [
        variable
        for (employee_id, _field_id), variable in variables.items()
        if employee_id not in current_employee_ids
    ]
    transfer_variables = [
        variable
        for (employee_id, field_id), variable in variables.items()
        if data.employee_by_id[employee_id].home_division != data.field_by_id[field_id].division
    ]
    all_variables = list(variables.values())
    # Lexicographic objective: reach as much of the requested goal as possible,
    # then use the fewest additional attendees, transfers and total assignments.
    tier = len(employee_ids) + 1
    objective = (
        credited * tier * tier * tier
        - sum(extra_variables) * tier * tier
        - sum(transfer_variables) * tier
        - sum(all_variables)
    )
    model.Maximize(objective)

    solver = _solver(cp_model, full_scenario, time_limit_seconds, search_workers)
    status = solver.Solve(model)
    feasible_statuses = (cp_model.OPTIMAL, cp_model.FEASIBLE)
    if status not in feasible_statuses:
        return {
            "available": True,
            "error": f"CP-SAT returned {_status_name(solver, status)}",
            "solver_status": _status_name(solver, status),
        }

    assignments = []
    for (employee_id, field_id), variable in variables.items():
        if solver.Value(variable):
            assignments.append({
                "employee_id": employee_id,
                "field_id": field_id,
                "predicted_kg": predictions[(employee_id, field_id)] / KG_SCALE,
            })
    plan = build_plan(
        data,
        full_scenario,
        assignments,
        "coverage-goal",
        "minimum additional attendance plan for the requested coverage goal",
    )
    added_assignments = [
        item
        for item in plan["assignments"]
        if item["employee_id"] not in current_employee_ids
    ]
    achieved = float(plan["metrics"]["coverage_pct"])
    shortfall_kg = max(
        0.0,
        goal_fulfilled / KG_SCALE - float(plan["metrics"]["predicted_fulfilled_kg"]),
    )
    best_values = []
    for employee_id in employee_ids:
        values = [
            prediction_map[(employee_id, field_id)]
            for field_id in fields
            if (employee_id, field_id) in variables
        ]
        if values:
            best_values.append(max(values))
    typical_productive_kg = median(best_values) if best_values else 1.0
    return {
        "available": True,
        "error": None,
        "solver_status": _status_name(solver, status),
        "optimality_proven": status == cp_model.OPTIMAL,
        "solve_seconds": round(time.perf_counter() - started, 3),
        "search_workers": search_workers,
        "allow_cross_division": allow_cross_division,
        "known_worker_pool": len(employee_ids),
        "goal_attainable": achieved + 0.051 >= float(goal_coverage_pct),
        "achieved_coverage_pct": achieved,
        "goal_shortfall_kg": round(shortfall_kg, 2),
        "additional_workers": len(added_assignments),
        "required_attendance_workers": min(
            len(employee_ids),
            len(current_employee_ids) + len(added_assignments),
        ),
        "required_attendance_pct": round(
            100.0
            * min(len(employee_ids), len(current_employee_ids) + len(added_assignments))
            / max(1, len(employee_ids)),
            1,
        ),
        "transfer_assignments": int(plan["metrics"]["cross_division_assignments"]),
        "additional_worker_assignments": added_assignments,
        "estimated_external_workers_if_still_short": (
            int(ceil(shortfall_kg / max(1.0, typical_productive_kg)))
            if shortfall_kg > 0.01 else 0
        ),
        "plan": plan,
    }


def _field_shortfalls(plan: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    rows = sorted(plan.get("fields", []), key=lambda item: float(item.get("gap_kg", 0)), reverse=True)
    return [
        {
            "field_id": item["field_id"],
            "division": item["division"],
            "gap_kg": item["gap_kg"],
            "coverage_pct": item["coverage_pct"],
        }
        for item in rows[:limit]
        if float(item.get("gap_kg", 0)) > 0.01
    ]


def analyze_coverage_goal(
    data: WorkforceData,
    scenario: Scenario,
    selected_plan: dict[str, Any],
    *,
    goal_coverage_pct: float = 85.0,
    time_limit_seconds: float = 3.0,
) -> dict[str, Any]:
    goal = max(50.0, min(100.0, float(goal_coverage_pct)))
    metrics = selected_plan["metrics"]
    current_coverage = float(metrics["coverage_pct"])
    target_kg = float(metrics["target_kg"])
    required_kg = target_kg * goal / 100.0
    current_fulfilled = float(metrics["predicted_fulfilled_kg"])
    current_shortfall = max(0.0, required_kg - current_fulfilled)
    base = {
        "goal_coverage_pct": round(goal, 1),
        "goal_fulfilled_kg": round(required_kg, 2),
        "current_coverage_pct": round(current_coverage, 1),
        "current_fulfilled_kg": round(current_fulfilled, 2),
        "current_shortfall_kg": round(current_shortfall, 2),
        "current_available_workers": int(metrics["available_workers"]),
        "field_shortfalls": _field_shortfalls(selected_plan),
        "current_plan_goal_met": current_coverage + 0.051 >= goal,
    }
    if base["current_plan_goal_met"]:
        return {
            **base,
            "status": "goal_met",
            "headline": f"The {goal:.0f}% goal is achievable with the current plan.",
            "minimum_additional_workers": 0,
            "minimum_additional_workers_proven": True,
            "required_attendance_pct": round(100.0 * scenario.attendance_rate, 1),
            "cross_division_required": bool(metrics["cross_division_assignments"]),
            "next_actions": [
                "Use the selected zero-violation allocation.",
                "Confirm actual attendance before deployment.",
            ],
            "goal_plan": selected_plan,
            "analysis": None,
        }

    same_rules = _goal_staffing_plan(
        data,
        scenario,
        current_employee_ids=set(scenario.employee_ids),
        goal_coverage_pct=goal,
        allow_cross_division=not scenario.same_division_only,
        time_limit_seconds=time_limit_seconds,
    )
    if same_rules.get("goal_attainable"):
        additional = int(same_rules["additional_workers"])
        transfers = int(same_rules["transfer_assignments"])
        minimum_proven = bool(same_rules["optimality_proven"])
        actions = [
            f"Confirm {additional} additional worker(s) for the verified goal plan.",
            f"Raise attendance from {scenario.attendance_rate * 100:.0f}% to at least {same_rules['required_attendance_pct']:.1f}%.",
        ]
        if transfers:
            actions.append(f"Supervisor approval is required for {transfers} cross-division assignment(s).")
        actions.append("Use the goal staffing assignments after supervisor confirmation.")
        return {
            **base,
            "status": "more_attendance_needed",
            "headline": (
                f"The {goal:.0f}% goal needs exactly {additional} more available worker(s)."
                if minimum_proven
                else f"A verified {goal:.0f}% plan uses {additional} more available worker(s)."
            ),
            "minimum_additional_workers": additional,
            "minimum_additional_workers_proven": minimum_proven,
            "verified_additional_workers": additional,
            "required_attendance_pct": same_rules["required_attendance_pct"],
            "cross_division_required": transfers > 0,
            "required_transfer_assignments": transfers,
            "next_actions": actions,
            "goal_plan": same_rules["plan"],
            "analysis": {key: value for key, value in same_rules.items() if key != "plan"},
        }

    flexible = None
    if scenario.same_division_only:
        flexible = _goal_staffing_plan(
            data,
            scenario,
            current_employee_ids=set(scenario.employee_ids),
            goal_coverage_pct=goal,
            allow_cross_division=True,
            time_limit_seconds=time_limit_seconds,
        )
        if flexible.get("goal_attainable"):
            additional = int(flexible["additional_workers"])
            transfers = int(flexible["transfer_assignments"])
            minimum_proven = bool(flexible["optimality_proven"])
            return {
                **base,
                "status": "cross_division_needed",
                "headline": (
                    f"The {goal:.0f}% goal needs exactly {additional} more worker(s) and flexible divisions."
                    if minimum_proven
                    else f"A verified {goal:.0f}% plan uses {additional} more worker(s) and flexible divisions."
                ),
                "minimum_additional_workers": additional,
                "minimum_additional_workers_proven": minimum_proven,
                "verified_additional_workers": additional,
                "required_attendance_pct": flexible["required_attendance_pct"],
                "cross_division_required": True,
                "required_transfer_assignments": transfers,
                "next_actions": [
                    f"Confirm {additional} additional worker(s) for the verified goal plan.",
                    f"Supervisor approval is required for {transfers} cross-division assignment(s).",
                    "Use the goal staffing assignments only after both checks pass.",
                ],
                "goal_plan": flexible["plan"],
                "analysis": {key: value for key, value in flexible.items() if key != "plan"},
            }

    strongest = flexible if flexible and flexible.get("available") else same_rules
    achieved = strongest.get("achieved_coverage_pct")
    estimate = strongest.get("estimated_external_workers_if_still_short", 0)
    achieved_text = f"{achieved:.1f}%" if isinstance(achieved, (int, float)) else "the available maximum"
    return {
        **base,
        "status": "capacity_gap",
        "headline": f"The {goal:.0f}% goal is not feasible with the known worker pool and capacities.",
        "minimum_additional_workers": None,
        "minimum_additional_workers_proven": False,
        "required_attendance_pct": 100.0,
        "cross_division_required": False,
        "cross_division_tested": bool(scenario.same_division_only),
        "best_full_attendance_coverage_pct": achieved,
        "estimated_external_workers": estimate,
        "next_actions": [
            f"Full attendance reaches about {achieved_text} under the tested rules.",
            f"Review at least {estimate} equivalent external worker(s) and field-capacity headroom.",
            "Do not lower crop targets unless an approved crop forecast supports the change.",
        ],
        "goal_plan": strongest.get("plan"),
        "analysis": {key: value for key, value in strongest.items() if key != "plan"},
    }
