from __future__ import annotations

from dataclasses import replace
from typing import Any

from .data import Scenario, WorkforceData
from .optimizer import optimize_allocate, optimizer_available


def _source_day_pool(data: WorkforceData, scenario: Scenario) -> list[str]:
    source_day = data.day_by_date[scenario.template_date]
    return sorted(
        employee_id
        for employee_id in source_day["available_employee_ids"]
        if employee_id in data.employee_by_id
    )


def build_practical_plan(
    data: WorkforceData,
    scenario: Scenario,
    current_plan: dict[str, Any],
    *,
    max_additional_workers: int,
    max_cross_division_assignments: int,
    goal_coverage_pct: float = 85.0,
    time_limit_seconds: float = 10.0,
) -> dict[str, Any]:
    """Build one executable plan under supervisor-entered operating limits.

    The wider employee pool contains only workers recorded on the selected
    historical template day. The optimizer may select at most the authorized
    number beyond the current expected-attendance sample, and may create at
    most the authorized number of cross-division assignments.
    """

    if not optimizer_available():
        return {
            "ready": False,
            "status": "optimizer_unavailable",
            "error": "OR-Tools CP-SAT is unavailable",
            "plan": None,
        }

    additional_limit = max(0, int(max_additional_workers))
    transfer_limit = max(0, int(max_cross_division_assignments))
    baseline_ids = set(scenario.employee_ids)
    source_pool = _source_day_pool(data, scenario)

    # A selected division normally starts with only its own employees. Once a
    # supervisor authorizes transfers, employees from other divisions become
    # candidates, while the hard transfer cap remains in the solver.
    if scenario.division and transfer_limit == 0:
        source_pool = [
            employee_id
            for employee_id in source_pool
            if data.employee_by_id[employee_id].home_division == scenario.division
        ]
    employee_pool = sorted(baseline_ids | set(source_pool))
    candidate_additional_ids = set(employee_pool) - baseline_ids
    effective_additional_limit = min(additional_limit, len(candidate_additional_ids))

    practical_scenario = replace(
        scenario,
        employee_ids=employee_pool,
        same_division_only=transfer_limit == 0,
    )
    plan = optimize_allocate(
        data,
        practical_scenario,
        time_limit_seconds=time_limit_seconds,
        baseline_employee_ids=baseline_ids,
        max_additional_workers=effective_additional_limit,
        max_cross_division_assignments=transfer_limit,
    )

    selected_ids = {
        item["employee_id"]
        for item in plan.get("assignments", [])
    }
    additional_ids = selected_ids - baseline_ids
    additional_workers = [
        {
            "employee_id": item["employee_id"],
            "home_division": item["home_division"],
            "field_id": item["field_id"],
            "assigned_division": item["division"],
            "predicted_kg": item["predicted_kg"],
        }
        for item in plan.get("assignments", [])
        if item["employee_id"] in additional_ids
    ]
    transfer_assignments = [
        {
            "employee_id": item["employee_id"],
            "home_division": item["home_division"],
            "field_id": item["field_id"],
            "assigned_division": item["division"],
            "predicted_kg": item["predicted_kg"],
        }
        for item in plan.get("assignments", [])
        if item.get("cross_division")
    ]

    operational_violations = []
    if len(additional_workers) > effective_additional_limit:
        operational_violations.append("Additional-worker authorization exceeded")
    if len(transfer_assignments) > transfer_limit:
        operational_violations.append("Cross-division transfer authorization exceeded")
    if plan["metrics"]["constraint_violations"]:
        operational_violations.extend(plan.get("violations", []))

    coverage = float(plan["metrics"]["coverage_pct"])
    current_coverage = float(current_plan["metrics"]["coverage_pct"])
    goal = float(goal_coverage_pct)
    ready = not operational_violations
    status = (
        "goal_reached"
        if ready and coverage >= goal
        else "ready_below_goal"
        if ready
        else "constraint_failure"
    )
    proof = plan.get("optimization") or {}
    return {
        "ready": ready,
        "status": status,
        "error": None if ready else "; ".join(operational_violations),
        "goal_coverage_pct": round(goal, 1),
        "coverage_pct": coverage,
        "current_coverage_pct": current_coverage,
        "improvement_pct_points": round(coverage - current_coverage, 1),
        "goal_reached": coverage >= goal,
        "gap_to_goal_pct_points": round(max(0.0, goal - coverage), 1),
        "baseline_expected_workers": len(baseline_ids),
        "template_day_worker_pool": len(employee_pool),
        "candidate_additional_workers": len(candidate_additional_ids),
        "requested_additional_worker_limit": additional_limit,
        "effective_additional_worker_limit": effective_additional_limit,
        "additional_workers_used": len(additional_workers),
        "requested_transfer_limit": transfer_limit,
        "transfers_used": len(transfer_assignments),
        "additional_workers": additional_workers,
        "transfer_assignments": transfer_assignments,
        "worker_confirmation_required": bool(additional_workers),
        "transfer_approval_required": bool(transfer_assignments),
        "constraint_violations": len(operational_violations),
        "violations": operational_violations,
        "optimality_proven": bool(proof.get("optimality_proven")),
        "coverage_upper_bound_pct": proof.get("coverage_upper_bound_pct"),
        "optimality_gap_pct_points": proof.get("optimality_gap_pct_points"),
        "solve_seconds": proof.get("solve_seconds"),
        "plan": plan,
        "notice": (
            "The employee aliases and transfers are a proposed morning roster. "
            "A supervisor must confirm every listed call-up and transfer before export or deployment."
        ),
    }
