from __future__ import annotations

from .data import Scenario, WorkforceData, build_plan


def greedy_allocate(data: WorkforceData, scenario: Scenario) -> dict:
    """Deterministic forecast-aware baseline used as the RL safety benchmark."""
    pairs = []
    field_ids = list(scenario.demand_kg)
    bundles = data.prediction_bundle_map(
        scenario.employee_ids,
        field_ids,
        scenario.planning_date,
    )
    for employee_id in scenario.employee_ids:
        employee = data.employee_by_id[employee_id]
        for field_id in field_ids:
            field = data.field_by_id[field_id]
            if scenario.same_division_only and employee.home_division != field.division:
                continue
            details = bundles[(employee_id, field_id)]
            predicted = float(details["expected_kg"])
            confidence = float(details["confidence"])
            direct_experience = field_id in employee.field_productivity
            demand_per_slot = scenario.demand_kg[field_id] / max(1, scenario.capacity[field_id])
            risk_adjusted = predicted * (0.82 + 0.18 * confidence)
            score = risk_adjusted + 0.18 * demand_per_slot + (1.5 if direct_experience else 0.0)
            if employee.home_division != field.division:
                score -= 3.0
            pairs.append((score, risk_adjusted, predicted, confidence, employee_id, field_id))
    pairs.sort(reverse=True)
    used = set()
    counts = {field_id: 0 for field_id in scenario.demand_kg}
    predicted_by_field = {field_id: 0.0 for field_id in scenario.demand_kg}
    assignments = []
    for _score, _risk_adjusted, predicted, confidence, employee_id, field_id in pairs:
        if employee_id in used:
            continue
        if counts[field_id] >= scenario.capacity[field_id]:
            continue
        if predicted_by_field[field_id] >= scenario.demand_kg[field_id]:
            continue
        assignments.append({
            "employee_id": employee_id,
            "field_id": field_id,
            "predicted_kg": predicted,
            "forecast_confidence": confidence,
        })
        used.add(employee_id)
        counts[field_id] += 1
        predicted_by_field[field_id] += predicted
    return build_plan(
        data,
        scenario,
        assignments,
        "forecast-greedy",
        "deterministic forecast-aware safety baseline",
    )
