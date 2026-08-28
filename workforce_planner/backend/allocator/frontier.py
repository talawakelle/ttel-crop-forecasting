from __future__ import annotations

from dataclasses import replace
from typing import Any
import random

from .baseline import greedy_allocate
from .data import Scenario, WorkforceData
from .optimizer import optimize_allocate, optimizer_available


REFERENCE_BENCHMARK = {
    "episodes": 40,
    "seed": 1042,
    "prediction_method": "historical median fallback",
    "strict_mean_coverage_pct": 67.75,
    "standard_mean_coverage_pct": 65.30,
    "open_divisions_mean_coverage_pct": 71.50,
    "full_attendance_mean_coverage_pct": 77.56,
    "full_attendance_open_divisions_mean_coverage_pct": 81.37,
    "capacity_plus_one_improvement_points": 0.01,
    "half_day_blocks_improvement_points": 0.02,
}


def _full_employee_pool(
    data: WorkforceData,
    scenario: Scenario,
    *,
    allow_cross_division: bool,
) -> list[str]:
    source_day = data.day_by_date[scenario.template_date]
    employees = [
        employee_id
        for employee_id in source_day["available_employee_ids"]
        if employee_id in data.employee_by_id
    ]
    if scenario.division and not allow_cross_division:
        employees = [
            employee_id
            for employee_id in employees
            if data.employee_by_id[employee_id].home_division == scenario.division
        ]
    return sorted(employees)


def _flexible_attendance_pool(
    data: WorkforceData,
    scenario: Scenario,
) -> list[str]:
    """Keep current attendees and sample expected attendees from other divisions.

    ``create_scenario`` filters a selected division before sampling attendance.
    A transfer what-if therefore needs a separate, deterministic sample of
    workers from the other divisions while preserving every current attendee.
    """
    if not scenario.division:
        return sorted(scenario.employee_ids)
    source_day = data.day_by_date[scenario.template_date]
    outside = [
        employee_id
        for employee_id in source_day["available_employee_ids"]
        if employee_id in data.employee_by_id
        and data.employee_by_id[employee_id].home_division != scenario.division
    ]
    rng = random.Random(scenario.seed + 90_901)
    rng.shuffle(outside)
    keep = round(len(outside) * scenario.attendance_rate)
    return sorted(set(scenario.employee_ids) | set(outside[:keep]))


def _optimize_variant(
    data: WorkforceData,
    scenario: Scenario,
    *,
    time_limit_seconds: float,
) -> dict[str, Any]:
    warm = greedy_allocate(data, scenario)
    return optimize_allocate(
        data,
        scenario,
        time_limit_seconds=time_limit_seconds,
        warm_start_plan=warm,
    )


def _summary(
    name: str,
    label: str,
    plan: dict[str, Any],
    *,
    current_plan: dict[str, Any],
    current_employee_ids: set[str],
    conditions: list[str],
) -> dict[str, Any]:
    metrics = plan["metrics"]
    current_coverage = float(current_plan["metrics"]["coverage_pct"])
    assigned_ids = {item["employee_id"] for item in plan.get("assignments", [])}
    additional_assigned = len(assigned_ids - current_employee_ids)
    optimization = plan.get("optimization") or {}
    return {
        "name": name,
        "label": label,
        "coverage_pct": float(metrics["coverage_pct"]),
        "improvement_pct_points": round(float(metrics["coverage_pct"]) - current_coverage, 1),
        "goal_reached": float(metrics["coverage_pct"]) >= 85.0,
        "gap_to_85_pct_points": round(max(0.0, 85.0 - float(metrics["coverage_pct"])), 1),
        "available_workers": int(metrics["available_workers"]),
        "assigned_workers": int(metrics["assigned_workers"]),
        "additional_assigned_workers": additional_assigned,
        "cross_division_assignments": int(metrics["cross_division_assignments"]),
        "constraint_violations": int(metrics["constraint_violations"]),
        "optimality_proven": bool(optimization.get("optimality_proven")),
        "coverage_upper_bound_pct": optimization.get("coverage_upper_bound_pct"),
        "solve_seconds": optimization.get("solve_seconds"),
        "conditions": conditions,
    }


def build_coverage_frontier(
    data: WorkforceData,
    scenario: Scenario,
    current_plan: dict[str, Any],
    *,
    time_limit_seconds: float = 3.0,
) -> dict[str, Any]:
    if not optimizer_available():
        return {
            "ready": False,
            "error": "OR-Tools CP-SAT is unavailable",
            "options": [],
            "best_plan": None,
            "reference_benchmark": REFERENCE_BENCHMARK,
        }

    current_ids = set(scenario.employee_ids)
    plans: dict[str, dict[str, Any]] = {"current": current_plan}
    errors: dict[str, str | None] = {
        "flexible_divisions": None,
        "full_attendance": None,
        "full_attendance_flexible": None,
    }

    flexible_scenario = replace(
        scenario,
        employee_ids=_flexible_attendance_pool(data, scenario),
        same_division_only=False,
    )
    if scenario.same_division_only:
        try:
            plans["flexible_divisions"] = _optimize_variant(
                data,
                flexible_scenario,
                time_limit_seconds=time_limit_seconds,
            )
        except Exception as exc:
            errors["flexible_divisions"] = f"{type(exc).__name__}: {exc}"
    else:
        plans["flexible_divisions"] = current_plan

    full_home_scenario = replace(
        scenario,
        employee_ids=_full_employee_pool(data, scenario, allow_cross_division=False),
        attendance_rate=1.0,
    )
    try:
        plans["full_attendance"] = _optimize_variant(
            data,
            full_home_scenario,
            time_limit_seconds=time_limit_seconds,
        )
    except Exception as exc:
        errors["full_attendance"] = f"{type(exc).__name__}: {exc}"

    full_flexible_scenario = replace(
        scenario,
        employee_ids=_full_employee_pool(data, scenario, allow_cross_division=True),
        attendance_rate=1.0,
        same_division_only=False,
    )
    try:
        plans["full_attendance_flexible"] = _optimize_variant(
            data,
            full_flexible_scenario,
            time_limit_seconds=time_limit_seconds,
        )
    except Exception as exc:
        errors["full_attendance_flexible"] = f"{type(exc).__name__}: {exc}"

    current_division_condition = (
        "Selected division rule" if scenario.same_division_only else "Division transfers already enabled"
    )
    definitions = {
        "current": (
            "Current rules",
            ["Expected attendance", current_division_condition],
        ),
        "flexible_divisions": (
            "Flexible divisions",
            ["Expected attendance", "Supervisor-approved division transfers"],
        ),
        "full_attendance": (
            "Full attendance",
            ["100% of the template-day worker pool", current_division_condition],
        ),
        "full_attendance_flexible": (
            "Full attendance + flexible divisions",
            ["100% of the template-day worker pool", "Supervisor-approved division transfers"],
        ),
    }
    options = []
    for name in ("current", "flexible_divisions", "full_attendance", "full_attendance_flexible"):
        if name not in plans:
            continue
        label, conditions = definitions[name]
        options.append(_summary(
            name,
            label,
            plans[name],
            current_plan=current_plan,
            current_employee_ids=current_ids,
            conditions=conditions,
        ))

    valid_options = [
        option
        for option in options
        if option["constraint_violations"] == 0
    ]
    if not valid_options:
        return {
            "ready": False,
            "error": "No zero-violation frontier option was produced",
            "options": options,
            "errors": errors,
            "best_plan": None,
            "reference_benchmark": REFERENCE_BENCHMARK,
        }
    best = max(valid_options, key=lambda item: item["coverage_pct"])
    best_plan = plans[best["name"]]
    return {
        "ready": True,
        "error": None,
        "current_coverage_pct": float(current_plan["metrics"]["coverage_pct"]),
        "best_option": best["name"],
        "best_coverage_pct": best["coverage_pct"],
        "best_improvement_pct_points": best["improvement_pct_points"],
        "best_is_conditional": best["name"] != "current",
        "options": options,
        "errors": errors,
        "best_plan": best_plan,
        "reference_benchmark": REFERENCE_BENCHMARK,
        "excluded_levers": [
            {
                "name": "one_extra_field_capacity",
                "reason": "Only +0.01 mean coverage points across the fixed 40-scenario test.",
            },
            {
                "name": "half_day_splitting",
                "reason": "Only +0.02 mean coverage points and adds operational complexity.",
            },
        ],
        "notice": (
            "Frontier plans are conditional scenarios, not confirmed staffing. "
            "Attendance and cross-division transfers require supervisor approval."
        ),
    }
