from __future__ import annotations

from typing import Any, Iterable
import math

import gymnasium as gym
from gymnasium import spaces
import numpy as np

from .dynamic_environment import DynamicReallocationEnv
from .data import validate_plan
from .selective_actions import ACCEPT_GREEDY, KEEP_CURRENT


class SelectiveHybridReallocationEnv(DynamicReallocationEnv):
    """Selective RL gate around a budgeted dynamic-greedy intraday planner.

    Dynamic greedy remains the default planner. The RL agent is consulted only
    when a proposed move is uncertain. It may accept the proposal or veto it and
    keep the employee in the current field. Hard move budgets, action masks and
    a conservative global fallback prevent the policy from reorganising the
    whole workforce or deploying a forecast-inferior plan.
    """

    def __init__(
        self,
        data,
        *,
        scenario_dates: Iterable[str] | None = None,
        seed: int = 42,
        difficulty: str = "full",
        max_move_rate: float = 0.15,
        max_total_moves: int = 15,
        max_stage_moves: int = 10,
        conservative_fallback_tolerance_pct_points: float = 0.05,
    ):
        super().__init__(
            data,
            scenario_dates=scenario_dates,
            seed=seed,
            difficulty=difficulty,
        )
        self.max_move_rate = max(0.02, min(0.25, float(max_move_rate)))
        self.configured_max_total_moves = max(1, int(max_total_moves))
        self.configured_max_stage_moves = max(1, int(max_stage_moves))
        self.conservative_fallback_tolerance_pct_points = max(
            0.0, float(conservative_fallback_tolerance_pct_points)
        )

        self.accept_action = ACCEPT_GREEDY
        self.keep_action = KEEP_CURRENT
        base_observation_size = int(self.observation_space.shape[0])
        self.action_space = spaces.Discrete(2)
        self.selective_extra_features = len(self.field_ids) * 2 + 12
        self.observation_space = spaces.Box(
            low=0.0,
            high=5.0,
            shape=(base_observation_size + self.selective_extra_features,),
            dtype=np.float32,
        )

        self.predicted_remaining = np.zeros(len(self.field_ids), dtype=np.float32)
        self.total_move_budget = 0
        self.stage_move_budget = 0
        self.total_moves_used = 0
        self.stage_moves_used = 0
        self.max_selective_decisions = 0
        self.selective_decisions = 0
        self.rl_accepts = 0
        self.rl_vetoes = 0
        self.shield_blocked_vetoes = 0
        self.automatic_greedy_actions = 0
        self.automatic_keep_actions = 0
        self.proposal_action = self.idle_action
        self.keep_field_action = self.idle_action
        self.proposal_score = 0.0
        self.keep_score = 0.0
        self.proposal_margin = 0.0
        self.proposal_uncertainty = 0.0
        self.proposal_confidence = 0.0
        self.proposal_cross_division = False
        self.proposal_changed = False
        self.budgeted_greedy_metrics: dict[str, Any] = {}
        self.raw_hybrid_remaining = np.zeros(len(self.field_ids), dtype=np.float32)
        self.raw_hybrid_conservative_remaining = np.zeros(len(self.field_ids), dtype=np.float32)
        self._terminated = False

    def _reset_selective_state(self) -> None:
        worker_count = max(1, len(self.employee_ids))
        rate_budget = max(1, math.ceil(worker_count * self.max_move_rate))
        self.total_move_budget = min(self.configured_max_total_moves, rate_budget)
        self.stage_move_budget = min(
            self.configured_max_stage_moves,
            max(1, math.ceil(worker_count * min(0.10, self.max_move_rate))),
        )
        self.max_selective_decisions = max(4, min(30, math.ceil(worker_count * 0.25)))
        self.total_moves_used = 0
        self.stage_moves_used = 0
        self.selective_decisions = 0
        self.rl_accepts = 0
        self.rl_vetoes = 0
        self.shield_blocked_vetoes = 0
        self.automatic_greedy_actions = 0
        self.automatic_keep_actions = 0
        self.proposal_action = self.idle_action
        self.keep_field_action = self.idle_action
        self.proposal_score = 0.0
        self.keep_score = 0.0
        self.proposal_margin = 0.0
        self.proposal_uncertainty = 0.0
        self.proposal_confidence = 0.0
        self.proposal_cross_division = False
        self.proposal_changed = False
        self.predicted_remaining = self.post_morning_remaining.copy()
        self.raw_hybrid_remaining = self.remaining_demand.copy()
        self.raw_hybrid_conservative_remaining = self.predicted_remaining.copy()
        self.budgeted_greedy_metrics = self._simulate_budgeted_greedy()
        self._terminated = False

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        gym.Env.reset(self, seed=seed)
        if seed is not None:
            self._rng.seed(seed)
        self._sample_config()
        options = options or {}
        self.scenario = options.get("scenario") or self._scenario()
        self.stage_index = 0
        self.position = 0
        self.assignments = []
        self.stage_counts.fill(0)
        self._prepare_episode()
        self._reset_selective_state()
        self._advance_to_selective_decision()
        return self._observation(), self._info()

    def _keep_action_for(self, employee_id: str) -> int:
        current = self.current_field.get(employee_id)
        masks = self._action_masks_for(
            employee_id,
            self.stage_counts,
            self.predicted_remaining,
            self.current_field,
            self.move_count,
            self.cross_division_employee_ids,
            self.max_cross_division_moves,
        )
        if current in self.field_index:
            index = self.field_index[current]
            if masks[index]:
                return index
        return self.idle_action

    def _estimated_score(self, employee_id: str, action: int) -> float:
        if action == self.idle_action:
            return 0.0
        row = self.employee_row[employee_id]
        fraction = self.current_stage_fraction
        output = float(self.conservative_matrix[row, action]) * fraction
        fulfilled = min(float(self.predicted_remaining[action]), output)
        shortage = float(self.predicted_remaining[action]) / max(
            1.0, float(self.initial_demand[action])
        )
        field_id = self.field_ids[action]
        current = self.current_field.get(employee_id)
        changed = current is not None and current != field_id
        employee = self.data.employee_by_id[employee_id]
        destination_cross = employee.home_division != self.data.field_by_id[field_id].division
        currently_cross = bool(
            current in self.field_index
            and self.data.field_by_id[current].division != employee.home_division
        )
        new_cross = destination_cross and not currently_cross
        score = fulfilled * (1.0 + 0.75 * shortage)
        score -= 0.70 * int(changed)
        score -= 2.25 * int(new_cross)
        score -= 0.35 * self.move_count.get(employee_id, 0) * int(changed)
        return float(score)

    def _proposal_details(self, employee_id: str) -> tuple[int, int, float, float]:
        proposal = self._reference_action(
            "greedy",
            employee_id,
            self.stage_index,
            self.stage_counts,
            self.predicted_remaining,
            self.current_field,
            self.move_count,
            self.cross_division_employee_ids,
        )
        keep = self._keep_action_for(employee_id)
        return proposal, keep, self._estimated_score(employee_id, proposal), self._estimated_score(employee_id, keep)

    def _is_changed_action(self, employee_id: str, action: int) -> bool:
        if action == self.idle_action:
            return False
        current = self.current_field.get(employee_id)
        return current is not None and current != self.field_ids[action]

    def _is_cross_action(self, employee_id: str, action: int) -> bool:
        if action == self.idle_action:
            return False
        employee = self.data.employee_by_id[employee_id]
        return employee.home_division != self.data.field_by_id[self.field_ids[action]].division

    def _move_budget_available(self) -> bool:
        return (
            self.total_moves_used < self.total_move_budget
            and self.stage_moves_used < self.stage_move_budget
        )

    def _uncertainty_threshold(self, employee_id: str, proposal: int) -> float:
        if proposal == self.idle_action:
            return 0.0
        row = self.employee_row[employee_id]
        fraction = self.current_stage_fraction
        uncertainty = max(
            0.0,
            float(self.prediction_matrix[row, proposal] - self.conservative_matrix[row, proposal]),
        ) * fraction
        confidence = float(self.confidence_matrix[row, proposal])
        return 0.65 + 0.85 * uncertainty + 1.5 * (1.0 - confidence)

    def _set_current_proposal(
        self,
        employee_id: str,
        proposal: int,
        keep: int,
        proposal_score: float,
        keep_score: float,
    ) -> None:
        self.proposal_action = int(proposal)
        self.keep_field_action = int(keep)
        self.proposal_score = float(proposal_score)
        self.keep_score = float(keep_score)
        self.proposal_margin = max(0.0, self.proposal_score - self.keep_score)
        if proposal == self.idle_action:
            self.proposal_uncertainty = 0.0
            self.proposal_confidence = 0.0
        else:
            row = self.employee_row[employee_id]
            self.proposal_uncertainty = max(
                0.0,
                float(self.prediction_matrix[row, proposal] - self.conservative_matrix[row, proposal]),
            ) * self.current_stage_fraction
            self.proposal_confidence = float(self.confidence_matrix[row, proposal])
        self.proposal_changed = self._is_changed_action(employee_id, proposal)
        self.proposal_cross_division = self._is_cross_action(employee_id, proposal)

    def _apply_field_action(
        self,
        employee_id: str,
        action: int,
        *,
        decision_source: str,
        rl_action: str | None = None,
    ) -> dict[str, float | bool]:
        fraction = self.current_stage_fraction
        current = self.current_field.get(employee_id)
        if action == self.idle_action:
            self.assignments.append({
                "stage": "midday" if self.stage_index == 0 else "afternoon",
                "stage_index": self.stage_index,
                "employee_id": employee_id,
                "field_id": None,
                "fraction_of_day": fraction,
                "decision_source": decision_source,
                "rl_action": rl_action,
            })
            return {
                "actual_fulfilled": 0.0,
                "conservative_fulfilled": 0.0,
                "changed": False,
                "new_cross": False,
            }

        field_id = self.field_ids[action]
        row = self.employee_row[employee_id]
        actual = float(self.actual_output_matrix[row, action]) * fraction
        conservative = float(self.conservative_matrix[row, action]) * fraction
        actual_fulfilled = min(float(self.remaining_demand[action]), actual)
        conservative_fulfilled = min(float(self.predicted_remaining[action]), conservative)
        self.remaining_demand[action] = max(0.0, float(self.remaining_demand[action]) - actual)
        self.predicted_remaining[action] = max(
            0.0, float(self.predicted_remaining[action]) - conservative
        )
        self.stage_counts[action] += 1

        changed = current is not None and current != field_id
        employee = self.data.employee_by_id[employee_id]
        destination_cross = employee.home_division != self.data.field_by_id[field_id].division
        currently_cross = bool(
            current in self.field_index
            and self.data.field_by_id[current].division != employee.home_division
        )
        new_cross = destination_cross and not currently_cross
        if changed:
            self.move_count[employee_id] = self.move_count.get(employee_id, 0) + 1
            self.total_moves_used += 1
            self.stage_moves_used += 1
        self.current_field[employee_id] = field_id
        if new_cross:
            self.cross_division_employee_ids.add(employee_id)

        self.assignments.append({
            "stage": "midday" if self.stage_index == 0 else "afternoon",
            "stage_index": self.stage_index,
            "employee_id": employee_id,
            "field_id": field_id,
            "home_division": employee.home_division,
            "division": self.data.field_by_id[field_id].division,
            "fraction_of_day": fraction,
            "predicted_kg": float(self.prediction_matrix[row, action]) * fraction,
            "conservative_kg": conservative,
            "actual_simulated_kg": actual,
            "fulfilled_kg": actual_fulfilled,
            "forecast_confidence": float(self.confidence_matrix[row, action]),
            "changed": changed,
            "cross_division": destination_cross,
            "new_cross_division_transfer": new_cross,
            "decision_source": decision_source,
            "rl_action": rl_action,
        })
        return {
            "actual_fulfilled": actual_fulfilled,
            "conservative_fulfilled": conservative_fulfilled,
            "changed": changed,
            "new_cross": new_cross,
        }

    def _next_stage(self) -> bool:
        while True:
            self.stage_index += 1
            self.position = 0
            self.stage_counts.fill(0)
            self.stage_moves_used = 0
            if self.stage_index >= len(self.stage_orders):
                self._terminated = True
                return True
            self._apply_late_demand_update(self.remaining_demand)
            self._apply_late_demand_update(self.predicted_remaining)
            if self.stage_orders[self.stage_index]:
                return False

    def _advance_position(self) -> bool:
        self.position += 1
        if self.stage_index >= len(self.stage_orders):
            self._terminated = True
            return True
        if self.position >= len(self.stage_orders[self.stage_index]):
            return self._next_stage()
        return False

    def _advance_to_selective_decision(self) -> bool:
        while not self._terminated:
            employee_id = self.current_employee_id
            if employee_id is None:
                if self._next_stage():
                    break
                continue
            proposal, keep, proposal_score, keep_score = self._proposal_details(employee_id)
            proposal_changed = self._is_changed_action(employee_id, proposal)
            threshold = self._uncertainty_threshold(employee_id, proposal)
            margin = proposal_score - keep_score
            keep_is_valid = keep != self.idle_action or self.current_field.get(employee_id) is None

            if proposal == keep:
                self._apply_field_action(employee_id, proposal, decision_source="automatic-same")
                self.automatic_greedy_actions += 1
                self._advance_position()
                continue

            if proposal_changed and not self._move_budget_available():
                self._apply_field_action(employee_id, keep, decision_source="automatic-move-budget")
                self.automatic_keep_actions += 1
                self._advance_position()
                continue

            if not keep_is_valid:
                self._apply_field_action(employee_id, proposal, decision_source="automatic-no-keep")
                self.automatic_greedy_actions += 1
                self._advance_position()
                continue

            uncertain = margin <= threshold
            special = self._is_cross_action(employee_id, proposal) or employee_id in self.reserve_ids
            if (
                not uncertain
                and not special
                or self.selective_decisions >= self.max_selective_decisions
            ):
                self._apply_field_action(employee_id, proposal, decision_source="automatic-high-margin")
                self.automatic_greedy_actions += 1
                self._advance_position()
                continue

            self._set_current_proposal(employee_id, proposal, keep, proposal_score, keep_score)
            return False

        self.raw_hybrid_remaining = self.remaining_demand.copy()
        self.raw_hybrid_conservative_remaining = self.predicted_remaining.copy()
        return True

    def action_masks(self) -> np.ndarray:
        if self._terminated or self.current_employee_id is None:
            return np.asarray([True, False], dtype=bool)
        return np.asarray([True, True], dtype=bool)

    def _observation(self) -> np.ndarray:
        if self._terminated or self.current_employee_id is None:
            return np.zeros(self.observation_space.shape, dtype=np.float32)
        base = DynamicReallocationEnv._observation(self)
        proposal = np.zeros(len(self.field_ids), dtype=np.float32)
        keep = np.zeros(len(self.field_ids), dtype=np.float32)
        if self.proposal_action in range(len(self.field_ids)):
            proposal[self.proposal_action] = 1.0
        if self.keep_field_action in range(len(self.field_ids)):
            keep[self.keep_field_action] = 1.0
        total_budget_remaining = max(
            0.0,
            1.0 - self.total_moves_used / max(1, self.total_move_budget),
        )
        stage_budget_remaining = max(
            0.0,
            1.0 - self.stage_moves_used / max(1, self.stage_move_budget),
        )
        selective_progress = self.selective_decisions / max(1, self.max_selective_decisions)
        current_employee = self.current_employee_id
        reserve = float(current_employee in self.reserve_ids)
        proposal_output = 0.0
        keep_output = 0.0
        if self.proposal_action != self.idle_action:
            row = self.employee_row[current_employee]
            proposal_output = float(self.conservative_matrix[row, self.proposal_action]) * self.current_stage_fraction
        if self.keep_field_action != self.idle_action:
            row = self.employee_row[current_employee]
            keep_output = float(self.conservative_matrix[row, self.keep_field_action]) * self.current_stage_fraction
        extra = np.concatenate([
            proposal,
            keep,
            np.asarray([
                min(5.0, self.proposal_margin / 10.0),
                min(5.0, self.proposal_uncertainty / 10.0),
                max(0.0, min(1.0, self.proposal_confidence)),
                total_budget_remaining,
                stage_budget_remaining,
                float(self.proposal_changed),
                float(self.proposal_cross_division),
                reserve,
                min(5.0, proposal_output / 20.0),
                min(5.0, keep_output / 20.0),
                max(0.0, min(1.0, selective_progress)),
                max(0.0, min(1.0, self.max_move_rate)),
            ], dtype=np.float32),
        ])
        return np.concatenate([base, extra]).astype(np.float32)

    def _counterfactual_fulfilled(self, employee_id: str, action: int) -> float:
        if action == self.idle_action:
            return 0.0
        row = self.employee_row[employee_id]
        actual = float(self.actual_output_matrix[row, action]) * self.current_stage_fraction
        return min(float(self.remaining_demand[action]), actual)

    def _veto_is_shield_safe(self, employee_id: str) -> bool:
        if self.keep_field_action == self.proposal_action:
            return True
        predicted_loss = max(0.0, self.proposal_score - self.keep_score)
        uncertainty_allowance = max(0.20, 0.30 * self.proposal_uncertainty)
        return predicted_loss <= uncertainty_allowance

    def _terminal_reward(self) -> float:
        raw_coverage = 1.0 - float(self.remaining_demand.sum()) / max(1.0, self.initial_target)
        budgeted = float(self.budgeted_greedy_metrics.get("coverage", 0.0))
        no_replan = float(self.no_replan_metrics.get("coverage", 0.0))
        full_greedy = float(self.greedy_replan_metrics.get("coverage", 0.0))
        bottom = self._bottom_quartile_coverage(self.remaining_demand)
        budgeted_bottom = float(self.budgeted_greedy_metrics.get("bottom_quartile_coverage", 0.0))
        move_saving = float(self.budgeted_greedy_metrics.get("changes", 0.0)) - self.total_moves_used
        reward = 220.0 * (raw_coverage - budgeted)
        reward += 65.0 * (raw_coverage - no_replan)
        reward += 20.0 * (raw_coverage - full_greedy)
        reward += 8.0 * (bottom - budgeted_bottom)
        reward += 0.12 * move_saving
        return float(reward)

    def step(self, action):
        if self.scenario is None:
            raise RuntimeError("reset() must be called before step()")
        if self._terminated or self.current_employee_id is None:
            return self._observation(), 0.0, True, False, self._info()

        employee_id = self.current_employee_id
        action = int(action)
        if action not in (self.accept_action, self.keep_action):
            action = self.accept_action
        proposal_actual = self._counterfactual_fulfilled(employee_id, self.proposal_action)
        keep_actual = self._counterfactual_fulfilled(employee_id, self.keep_field_action)
        chosen = self.proposal_action
        rl_label = "accept-greedy"
        reward = 0.0
        self.selective_decisions += 1

        if action == self.keep_action:
            if self._veto_is_shield_safe(employee_id):
                chosen = self.keep_field_action
                rl_label = "veto-keep"
                self.rl_vetoes += 1
                reward += 0.45 * (keep_actual - proposal_actual)
                if self._is_changed_action(employee_id, self.proposal_action):
                    reward += 0.08
            else:
                self.shield_blocked_vetoes += 1
                rl_label = "veto-blocked-by-shield"
                reward -= 0.03
        else:
            self.rl_accepts += 1
            reward += 0.05 * max(0.0, proposal_actual - keep_actual)

        details = self._apply_field_action(
            employee_id,
            chosen,
            decision_source="selective-rl",
            rl_action=rl_label,
        )
        reward -= 0.18 * int(bool(details["changed"]))
        reward -= 0.65 * int(bool(details["new_cross"]))
        self._advance_position()
        terminated = self._advance_to_selective_decision()
        if terminated:
            reward += self._terminal_reward()
        return self._observation(), float(reward), terminated, False, self._info()

    def _simulate_budgeted_greedy(self) -> dict[str, Any]:
        remaining = self.post_morning_remaining.copy()
        conservative_remaining = self.post_morning_remaining.copy()
        current_fields = dict(self.original_field)
        move_counts = {employee_id: 0 for employee_id in self.employee_ids}
        cross_division_employees: set[str] = set()
        changes = 0
        assigned = 0
        assignments: list[dict[str, Any]] = []
        total_move_budget = self.total_move_budget
        for stage_index, order in enumerate(self.stage_orders):
            if stage_index > 0:
                self._apply_late_demand_update(remaining)
                self._apply_late_demand_update(conservative_remaining)
            counts = np.zeros(len(self.field_ids), dtype=np.int32)
            stage_moves = 0
            fraction = float(self.config.decision_fractions[stage_index])
            for employee_id in order:
                proposal = self._reference_action(
                    "greedy",
                    employee_id,
                    stage_index,
                    counts,
                    conservative_remaining,
                    current_fields,
                    move_counts,
                    cross_division_employees,
                )
                current = current_fields.get(employee_id)
                changed = bool(
                    proposal != self.idle_action
                    and current is not None
                    and self.field_ids[proposal] != current
                )
                if changed and (
                    changes >= total_move_budget or stage_moves >= self.stage_move_budget
                ):
                    masks = self._action_masks_for(
                        employee_id,
                        counts,
                        conservative_remaining,
                        current_fields,
                        move_counts,
                        cross_division_employees,
                        self.max_cross_division_moves,
                    )
                    if current in self.field_index and masks[self.field_index[current]]:
                        proposal = self.field_index[current]
                    else:
                        proposal = self.idle_action
                    changed = False
                if proposal == self.idle_action:
                    continue
                field_id = self.field_ids[proposal]
                row = self.employee_row[employee_id]
                actual = float(self.actual_output_matrix[row, proposal]) * fraction
                conservative = float(self.conservative_matrix[row, proposal]) * fraction
                actual_fulfilled = min(float(remaining[proposal]), actual)
                remaining[proposal] = max(0.0, float(remaining[proposal]) - actual)
                conservative_remaining[proposal] = max(
                    0.0, float(conservative_remaining[proposal]) - conservative
                )
                counts[proposal] += 1
                assigned += 1
                previous = current_fields.get(employee_id)
                changed = previous is not None and previous != field_id
                if changed:
                    move_counts[employee_id] += 1
                    changes += 1
                    stage_moves += 1
                current_fields[employee_id] = field_id
                employee = self.data.employee_by_id[employee_id]
                destination_cross = employee.home_division != self.data.field_by_id[field_id].division
                previous_cross = bool(
                    previous in self.field_index
                    and self.data.field_by_id[previous].division != employee.home_division
                )
                if destination_cross and not previous_cross:
                    cross_division_employees.add(employee_id)
                assignments.append({
                    "stage": "midday" if stage_index == 0 else "afternoon",
                    "stage_index": stage_index,
                    "employee_id": employee_id,
                    "field_id": field_id,
                    "home_division": employee.home_division,
                    "division": self.data.field_by_id[field_id].division,
                    "fraction_of_day": fraction,
                    "actual_simulated_kg": actual,
                    "fulfilled_kg": actual_fulfilled,
                    "conservative_kg": conservative,
                    "changed": changed,
                    "cross_division": destination_cross,
                    "new_cross_division_transfer": destination_cross and not previous_cross,
                    "decision_source": "budgeted-dynamic-greedy",
                })
        coverage = 1.0 - float(remaining.sum()) / max(1.0, self.initial_target)
        conservative_coverage = 1.0 - float(conservative_remaining.sum()) / max(1.0, self.initial_target)
        field_coverages = self._field_coverages(remaining)
        active = self.initial_demand > 0.0
        critical = int(np.sum(field_coverages[active] < 0.75)) if np.any(active) else 0
        violations: list[str] = []
        if self.scenario is not None:
            for stage_index in range(len(self.stage_orders)):
                stage_assignments = [
                    item for item in assignments if item["stage_index"] == stage_index
                ]
                violations.extend(validate_plan(self.scenario, stage_assignments))
        return {
            "coverage": max(0.0, min(1.0, coverage)),
            "conservative_coverage": max(0.0, min(1.0, conservative_coverage)),
            "bottom_quartile_coverage": self._bottom_quartile_coverage(remaining),
            "critical_fields": float(critical),
            "assigned_segments": float(assigned),
            "changes": float(changes),
            "transfers": float(len(cross_division_employees)),
            "remaining": remaining,
            "conservative_remaining": conservative_remaining,
            "assignments": assignments,
            "violations": violations,
        }

    def _stage_violations_for(self, assignments: list[dict[str, Any]]) -> list[str]:
        if self.scenario is None:
            return ["Scenario missing"]
        violations: list[str] = []
        for stage_index in range(len(self.stage_orders)):
            stage_assignments = [
                item for item in assignments
                if item.get("stage_index") == stage_index and item.get("field_id")
            ]
            for violation in validate_plan(self.scenario, stage_assignments):
                violations.append(f"stage {stage_index + 1}: {violation}")
        return violations

    def result(self, policy: str = "selective-hybrid-rl-v1") -> dict[str, Any]:
        if self.scenario is None:
            raise RuntimeError("No episode result")
        raw_assignments = [item for item in self.assignments if item.get("field_id")]
        raw_violations = self._stage_violations_for(raw_assignments)
        raw_coverage = 1.0 - float(self.remaining_demand.sum()) / max(1.0, self.initial_target)
        raw_conservative_coverage = 1.0 - float(self.predicted_remaining.sum()) / max(
            1.0, self.initial_target
        )
        budgeted_conservative = float(
            self.budgeted_greedy_metrics.get("conservative_coverage", 0.0)
        )
        conservative_gap_points = 100.0 * (
            raw_conservative_coverage - budgeted_conservative
        )
        fallback_reasons: list[str] = []
        if raw_violations:
            fallback_reasons.append("hard-rule violation")
        if self.total_moves_used > self.total_move_budget:
            fallback_reasons.append("movement budget exceeded")
        if conservative_gap_points < -self.conservative_fallback_tolerance_pct_points:
            fallback_reasons.append("conservative predicted coverage below budgeted greedy")
        fallback = bool(fallback_reasons)

        if fallback:
            selected_assignments = list(self.budgeted_greedy_metrics.get("assignments", []))
            selected_remaining = np.asarray(
                self.budgeted_greedy_metrics.get("remaining", self.remaining_demand),
                dtype=np.float32,
            )
            selected_coverage = float(self.budgeted_greedy_metrics.get("coverage", 0.0))
            selected_conservative_coverage = budgeted_conservative
            selected_changes = int(self.budgeted_greedy_metrics.get("changes", 0.0))
            selected_transfers = int(self.budgeted_greedy_metrics.get("transfers", 0.0))
            selected_violations = list(self.budgeted_greedy_metrics.get("violations", []))
            selected_policy = "budgeted-dynamic-greedy-fallback"
        else:
            selected_assignments = raw_assignments
            selected_remaining = self.remaining_demand
            selected_coverage = raw_coverage
            selected_conservative_coverage = raw_conservative_coverage
            selected_changes = self.total_moves_used
            selected_transfers = len(self.cross_division_employee_ids)
            selected_violations = raw_violations
            selected_policy = policy

        bottom = self._bottom_quartile_coverage(selected_remaining)
        field_coverages = self._field_coverages(selected_remaining)
        active = self.initial_demand > 0.0
        critical = int(np.sum(field_coverages[active] < 0.75)) if np.any(active) else 0
        no_replan = float(self.no_replan_metrics.get("coverage", 0.0))
        budgeted = float(self.budgeted_greedy_metrics.get("coverage", 0.0))
        full_greedy = float(self.greedy_replan_metrics.get("coverage", 0.0))
        return {
            "policy": selected_policy,
            "raw_policy": policy,
            "difficulty": self.difficulty,
            "template_date": self.scenario.template_date,
            "planning_date": self.scenario.planning_date,
            "metrics": {
                "actual_simulated_coverage_pct": round(100.0 * selected_coverage, 3),
                "raw_hybrid_coverage_pct": round(100.0 * raw_coverage, 3),
                "conservative_predicted_coverage_pct": round(
                    100.0 * selected_conservative_coverage, 3
                ),
                "raw_conservative_predicted_coverage_pct": round(
                    100.0 * raw_conservative_coverage, 3
                ),
                "bottom_quartile_field_coverage_pct": round(100.0 * bottom, 3),
                "critical_fields_below_75_pct": critical,
                "no_replan_coverage_pct": round(100.0 * no_replan, 3),
                "budgeted_dynamic_greedy_coverage_pct": round(100.0 * budgeted, 3),
                "dynamic_greedy_coverage_pct": round(100.0 * full_greedy, 3),
                "perfect_information_greedy_reference_pct": round(
                    100.0 * float(self.perfect_info_metrics.get("coverage", 0.0)), 3
                ),
                "gain_vs_no_replan_pct_points": round(
                    100.0 * (selected_coverage - no_replan), 3
                ),
                "gain_vs_budgeted_dynamic_greedy_pct_points": round(
                    100.0 * (selected_coverage - budgeted), 3
                ),
                "gain_vs_dynamic_greedy_pct_points": round(
                    100.0 * (selected_coverage - full_greedy), 3
                ),
                "raw_gain_vs_budgeted_dynamic_greedy_pct_points": round(
                    100.0 * (raw_coverage - budgeted), 3
                ),
                "field_floor_gain_vs_no_replan_pct_points": round(
                    100.0 * (
                        bottom
                        - float(self.no_replan_metrics.get("bottom_quartile_coverage", 0.0))
                    ),
                    3,
                ),
                "reassignments": int(selected_changes),
                "raw_reassignments": int(self.total_moves_used),
                "budgeted_dynamic_greedy_reassignments": int(
                    self.budgeted_greedy_metrics.get("changes", 0.0)
                ),
                "dynamic_greedy_reassignments": int(
                    self.greedy_replan_metrics.get("changes", 0.0)
                ),
                "movement_saving_vs_budgeted_greedy": int(
                    self.budgeted_greedy_metrics.get("changes", 0.0)
                ) - int(selected_changes),
                "move_budget": int(self.total_move_budget),
                "stage_move_budget": int(self.stage_move_budget),
                "reassignment_rate": round(selected_changes / max(1, len(self.employee_ids)), 4),
                "cross_division_assignments": int(selected_transfers),
                "constraint_violations": len(selected_violations),
                "workers_considered": len(self.employee_ids),
                "selective_decisions": int(self.selective_decisions),
                "rl_accepts": int(self.rl_accepts),
                "rl_vetoes": int(self.rl_vetoes),
                "shield_blocked_vetoes": int(self.shield_blocked_vetoes),
                "automatic_greedy_actions": int(self.automatic_greedy_actions),
                "automatic_keep_actions": int(self.automatic_keep_actions),
                "fallback_triggered": fallback,
                "conservative_gap_vs_budgeted_greedy_pct_points": round(
                    conservative_gap_points, 3
                ),
                "replanning_rounds": len(self.stage_orders),
            },
            "morning_segments": self.morning_segments,
            "assignments": selected_assignments,
            "raw_assignments": raw_assignments,
            "violations": selected_violations,
            "safety": {
                "fallback_triggered": fallback,
                "fallback_reasons": fallback_reasons,
                "fallback_policy": "budgeted-dynamic-greedy",
                "maximum_total_moves": self.total_move_budget,
                "maximum_stage_moves": self.stage_move_budget,
                "conservative_fallback_tolerance_pct_points": (
                    self.conservative_fallback_tolerance_pct_points
                ),
            },
            "notice": (
                "Dynamic greedy remains the main intraday planner. RL only accepts or vetoes uncertain moves. "
                "A conservative safety check falls back to the budgeted greedy plan when required. "
                "Operational use still requires actual shadow-mode evidence."
            ),
        }
