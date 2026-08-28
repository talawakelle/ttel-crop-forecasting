from __future__ import annotations

from pathlib import Path
from typing import Any

from .baseline import greedy_allocate
from .data import Scenario, WorkforceData
from .optimizer import optimize_allocate, optimizer_available


def plan_rank(plan: dict[str, Any]) -> tuple[float, float, int, int]:
    metrics = plan["metrics"]
    return (
        float(metrics["predicted_fulfilled_kg"]),
        float(metrics["coverage_pct"]),
        -int(metrics["cross_division_assignments"]),
        -int(metrics["assigned_workers"]),
    )


def strongest_feasible(plans: dict[str, dict[str, Any] | None]) -> tuple[str, dict[str, Any]]:
    feasible = [
        (name, plan)
        for name, plan in plans.items()
        if plan is not None and int(plan["metrics"]["constraint_violations"]) == 0
    ]
    if not feasible:
        raise RuntimeError("No candidate produced a zero-violation allocation plan")
    return max(feasible, key=lambda item: plan_rank(item[1]))


def candidate_summary(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    if plan is None:
        return None
    metrics = plan["metrics"]
    summary = {
        "policy": plan["policy"],
        "coverage_pct": metrics["coverage_pct"],
        "predicted_fulfilled_kg": metrics["predicted_fulfilled_kg"],
        "assigned_workers": metrics["assigned_workers"],
        "cross_division_assignments": metrics["cross_division_assignments"],
        "constraint_violations": metrics["constraint_violations"],
    }
    if plan.get("optimization"):
        summary["optimization"] = plan["optimization"]
    return summary


def build_candidate_plans(
    data: WorkforceData,
    scenario: Scenario,
    *,
    model_path: Path | None,
    include_rl: bool = True,
    include_optimizer: bool = True,
    optimizer_time_limit_seconds: float = 5.0,
) -> dict[str, Any]:
    plans: dict[str, dict[str, Any] | None] = {
        "standard": greedy_allocate(data, scenario),
        "rl": None,
        "optimizer": None,
    }
    errors: dict[str, str | None] = {"rl": None, "optimizer": None}

    if include_rl:
        if model_path is None or not model_path.exists():
            errors["rl"] = "A compatible RL model is unavailable"
        else:
            try:
                from .policy import rl_allocate

                plans["rl"] = rl_allocate(data, scenario, model_path)
            except Exception as exc:
                errors["rl"] = f"RL inference failed: {type(exc).__name__}: {exc}"

    if include_optimizer:
        if not optimizer_available():
            errors["optimizer"] = "OR-Tools CP-SAT is not installed"
        else:
            warm_candidates = {
                name: plan for name, plan in plans.items()
                if name in {"standard", "rl"} and plan is not None
            }
            _warm_name, warm_plan = strongest_feasible(warm_candidates)
            try:
                plans["optimizer"] = optimize_allocate(
                    data,
                    scenario,
                    time_limit_seconds=optimizer_time_limit_seconds,
                    warm_start_plan=warm_plan,
                )
            except Exception as exc:
                errors["optimizer"] = f"Optimizer failed: {type(exc).__name__}: {exc}"

    selected_name, selected_plan = strongest_feasible(plans)
    selected = dict(selected_plan)
    checked = [name for name, plan in plans.items() if plan is not None]
    selected["policy_status"] = (
        f"Hybrid compared {', '.join(checked)} and selected {selected_name} "
        "as the highest-coverage zero-violation plan."
    )
    return {
        "selected_name": selected_name,
        "selected": selected,
        "plans": plans,
        "errors": errors,
        "summaries": {name: candidate_summary(plan) for name, plan in plans.items()},
    }
