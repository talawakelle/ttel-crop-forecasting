from __future__ import annotations

from typing import Any
import os
import time

from .data import Scenario, WorkforceData, build_plan


OPTIMIZER_NAME = "Google OR-Tools CP-SAT"
OPTIMIZER_VERSION_REQUIRED = "9.15.6755"
KG_SCALE = 1_000


class OptimizerUnavailableError(RuntimeError):
    """Raised when the optional OR-Tools runtime is not installed."""


class OptimizationFailedError(RuntimeError):
    """Raised when CP-SAT cannot produce a feasible allocation."""


def optimizer_runtime() -> dict[str, Any]:
    try:
        import ortools
        from ortools.sat.python import cp_model  # noqa: F401
    except (ImportError, OSError) as exc:
        return {
            "available": False,
            "name": OPTIMIZER_NAME,
            "version": None,
            "required_version": OPTIMIZER_VERSION_REQUIRED,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "available": True,
        "name": OPTIMIZER_NAME,
        "version": getattr(ortools, "__version__", "unknown"),
        "required_version": OPTIMIZER_VERSION_REQUIRED,
        "error": None,
    }


def optimizer_available() -> bool:
    return bool(optimizer_runtime()["available"])


def _solver(cp_model, scenario: Scenario, seconds: float, search_workers: int):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.05, float(seconds))
    solver.parameters.num_search_workers = max(1, min(int(search_workers), os.cpu_count() or 1))
    solver.parameters.random_seed = int(scenario.seed) % 2_147_483_647
    solver.parameters.log_search_progress = False
    return solver


def _status_name(solver, status: int) -> str:
    try:
        return str(solver.StatusName(status)).upper()
    except TypeError:
        return str(solver.StatusName()).upper()


def optimize_allocate(
    data: WorkforceData,
    scenario: Scenario,
    *,
    time_limit_seconds: float = 5.0,
    warm_start_plan: dict[str, Any] | None = None,
    baseline_employee_ids: set[str] | None = None,
    max_additional_workers: int | None = None,
    max_cross_division_assignments: int | None = None,
) -> dict[str, Any]:
    """Maximize predicted fulfilled crop under the same hard rules as other policies.

    Stage one maximizes covered crop. Stage two keeps that coverage fixed and uses
    any remaining time to reduce oversupply and transfers. A plan is described as
    mathematically optimal only when CP-SAT proves the stage-one objective.
    """

    runtime = optimizer_runtime()
    if not runtime["available"]:
        raise OptimizerUnavailableError(
            f"{OPTIMIZER_NAME} is unavailable. Install ortools=={OPTIMIZER_VERSION_REQUIRED}."
        )

    from ortools.sat.python import cp_model

    started = time.perf_counter()
    total_limit = max(0.25, float(time_limit_seconds))
    employees = list(scenario.employee_ids)
    fields = list(scenario.demand_kg)
    model = cp_model.CpModel()

    forecast_status = data.forecast_status(scenario.planning_date)
    forecast_active = bool(forecast_status.get("eligible_for_planning_date"))
    # The v0.8 request can run the ordinary optimizer plus two goal checks.
    # Keeping every CP-SAT solve deterministic and single-worker avoids native
    # worker-pool contention with CatBoost and between sequential CP-SAT solves.
    # This estate model is small enough for the normal five-second budget.
    search_workers = 1

    prediction_bundles = data.prediction_bundle_map(
        employees,
        fields,
        scenario.planning_date,
    )

    variables: dict[tuple[str, str], Any] = {}
    predictions: dict[tuple[str, str], int] = {}
    confidences: dict[tuple[str, str], int] = {}
    employee_variables: dict[str, list[Any]] = {employee_id: [] for employee_id in employees}
    field_variables: dict[str, list[Any]] = {field_id: [] for field_id in fields}

    for employee_id in employees:
        employee = data.employee_by_id[employee_id]
        for field_id in fields:
            field = data.field_by_id[field_id]
            if scenario.same_division_only and employee.home_division != field.division:
                continue
            variable = model.NewBoolVar(f"assign_{employee_id}_{field_id}")
            variables[(employee_id, field_id)] = variable
            details = prediction_bundles[(employee_id, field_id)]
            predictions[(employee_id, field_id)] = int(
                round(float(details["expected_kg"]) * KG_SCALE)
            )
            confidences[(employee_id, field_id)] = int(
                round(float(details["confidence"]) * 1_000)
            )
            employee_variables[employee_id].append(variable)
            field_variables[field_id].append(variable)

    for employee_id, choices in employee_variables.items():
        if choices:
            model.Add(sum(choices) <= 1)

    baseline_ids = set(
        employees if baseline_employee_ids is None else baseline_employee_ids
    )
    additional_variables = [
        variable
        for (employee_id, _field_id), variable in variables.items()
        if employee_id not in baseline_ids
    ]
    transfer_variables = [
        variable
        for (employee_id, field_id), variable in variables.items()
        if data.employee_by_id[employee_id].home_division
        != data.field_by_id[field_id].division
    ]
    if max_additional_workers is not None:
        model.Add(sum(additional_variables) <= max(0, int(max_additional_workers)))
    if max_cross_division_assignments is not None:
        model.Add(
            sum(transfer_variables)
            <= max(0, int(max_cross_division_assignments))
        )

    produced_variables: dict[str, Any] = {}
    fulfilled_variables: dict[str, Any] = {}
    waste_variables: dict[str, Any] = {}
    for field_id in fields:
        choices = field_variables[field_id]
        model.Add(sum(choices) <= int(scenario.capacity[field_id]))
        maximum_production = sum(
            predictions[(employee_id, field_id)]
            for employee_id in employees
            if (employee_id, field_id) in variables
        )
        target = int(round(float(scenario.demand_kg[field_id]) * KG_SCALE))
        produced = model.NewIntVar(0, maximum_production, f"produced_{field_id}")
        fulfilled = model.NewIntVar(0, target, f"fulfilled_{field_id}")
        waste = model.NewIntVar(0, maximum_production, f"waste_{field_id}")
        model.Add(
            produced
            == sum(
                predictions[(employee_id, field_id)] * variables[(employee_id, field_id)]
                for employee_id in employees
                if (employee_id, field_id) in variables
            )
        )
        model.Add(fulfilled <= produced)
        model.Add(waste == produced - fulfilled)
        produced_variables[field_id] = produced
        fulfilled_variables[field_id] = fulfilled
        waste_variables[field_id] = waste

    total_fulfilled = sum(fulfilled_variables.values())
    model.Maximize(total_fulfilled)

    if warm_start_plan:
        selected_pairs = {
            (item.get("employee_id"), item.get("field_id"))
            for item in warm_start_plan.get("assignments", [])
        }
        for pair, variable in variables.items():
            model.AddHint(variable, int(pair in selected_pairs))

    primary_budget = max(0.2, total_limit * 0.82)
    primary_solver = _solver(cp_model, scenario, primary_budget, search_workers)
    primary_status = primary_solver.Solve(model)
    feasible_statuses = (cp_model.OPTIMAL, cp_model.FEASIBLE)
    if primary_status not in feasible_statuses:
        raise OptimizationFailedError(
            f"CP-SAT returned {_status_name(primary_solver, primary_status)} without a feasible plan."
        )

    best_fulfilled = int(primary_solver.Value(total_fulfilled))
    primary_values = {pair: bool(primary_solver.Value(variable)) for pair, variable in variables.items()}
    objective_upper_bound = max(float(best_fulfilled), float(primary_solver.BestObjectiveBound()))
    optimality_proven = primary_status == cp_model.OPTIMAL

    chosen_values = primary_values
    refinement_status_name = "SKIPPED"
    elapsed = time.perf_counter() - started
    remaining_budget = total_limit - elapsed
    if remaining_budget >= 0.10:
        model.Add(total_fulfilled == best_fulfilled)
        experienced_variables = []
        confidence_score = sum(
            confidences[pair] * variable for pair, variable in variables.items()
        )
        all_assignment_variables = list(variables.values())
        for (employee_id, field_id), variable in variables.items():
            employee = data.employee_by_id[employee_id]
            if field_id in employee.field_productivity:
                experienced_variables.append(variable)
        # Lexicographic-scale refinement: waste first, then transfers, then
        # direct experience and finally fewer workers for the same coverage.
        secondary_score = (
            -1_000_000 * sum(waste_variables.values())
            -10_000 * sum(transfer_variables)
            +5 * confidence_score
            +2 * sum(experienced_variables)
            -sum(all_assignment_variables)
        )
        model.Maximize(secondary_score)
        refinement_solver = _solver(cp_model, scenario, remaining_budget, search_workers)
        refinement_status = refinement_solver.Solve(model)
        refinement_status_name = _status_name(refinement_solver, refinement_status)
        if refinement_status in feasible_statuses:
            chosen_values = {
                pair: bool(refinement_solver.Value(variable))
                for pair, variable in variables.items()
            }

    assignments = []
    for (employee_id, field_id), selected in chosen_values.items():
        if not selected:
            continue
        assignments.append({
            "employee_id": employee_id,
            "field_id": field_id,
            "predicted_kg": predictions[(employee_id, field_id)] / KG_SCALE,
            "forecast_confidence": confidences[(employee_id, field_id)] / 1_000,
        })

    plan = build_plan(
        data,
        scenario,
        assignments,
        "cp-sat-optimal" if optimality_proven else "cp-sat-feasible",
        (
            "mathematical maximum coverage proven"
            if optimality_proven
            else "best feasible coverage found within the solver time limit"
        ),
    )
    total_target = max(1, int(round(sum(scenario.demand_kg.values()) * KG_SCALE)))
    upper_bound_pct = min(100.0, 100.0 * objective_upper_bound / total_target)
    plan["optimization"] = {
        **runtime,
        "primary_status": _status_name(primary_solver, primary_status),
        "refinement_status": refinement_status_name,
        "optimality_proven": optimality_proven,
        "time_limit_seconds": round(total_limit, 3),
        "solve_seconds": round(time.perf_counter() - started, 3),
        "coverage_upper_bound_pct": round(upper_bound_pct, 3),
        "optimality_gap_pct_points": round(
            max(0.0, upper_bound_pct - float(plan["metrics"]["coverage_pct"])),
            3,
        ),
        "decision_variables": len(variables),
        "search_workers": search_workers,
        "forecast_native_thread_safety_mode": forecast_active,
        "warm_start_policy": warm_start_plan.get("policy") if warm_start_plan else None,
        "max_additional_workers": (
            max(0, int(max_additional_workers))
            if max_additional_workers is not None else None
        ),
        "max_cross_division_assignments": (
            max(0, int(max_cross_division_assignments))
            if max_cross_division_assignments is not None else None
        ),
    }
    return plan
