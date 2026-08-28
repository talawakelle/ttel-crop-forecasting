from __future__ import annotations

from typing import Any
from datetime import date, timedelta
import random

import gymnasium as gym
from gymnasium import spaces
import numpy as np

from .data import Scenario, WorkforceData, build_plan
from .version import MODEL_SCHEMA_VERSION


ORDER_MODES = ("random", "specialists_first", "high_yield_first", "low_flexibility_first")
TARGET_COVERAGE = 0.85


class WorkforceAllocationEnv(gym.Env):
    """Sequential forecast-aware employee allocation with hard action masks.

    Version 3 adds forecast confidence and explicit shortage risk to the state.
    The dense reward measures marginal fulfilled crop and penalises opportunity
    regret, oversupply and avoidable idling. Hard constraints remain enforced by
    action masks rather than by reward alone.
    """

    metadata = {"render_modes": []}

    def __init__(self, data: WorkforceData, seed: int = 42):
        super().__init__()
        self.data = data
        self.field_ids = [field.id for field in data.fields]
        self.field_index = {field_id: index for index, field_id in enumerate(self.field_ids)}
        self.idle_action = len(self.field_ids)
        self.action_space = spaces.Discrete(len(self.field_ids) + 1)
        # Ten per-field groups plus progress, remaining workforce, flexibility,
        # and the current employee's maximum feasible predicted productivity.
        self.observation_space = spaces.Box(
            low=0.0,
            high=5.0,
            shape=(len(self.field_ids) * 10 + 4,),
            dtype=np.float32,
        )
        self._rng = random.Random(seed)
        self.scenario: Scenario | None = None
        self.employee_order: list[str] = []
        self.position = 0
        self.initial_demand = np.zeros(len(self.field_ids), dtype=np.float32)
        self.remaining_demand = np.zeros(len(self.field_ids), dtype=np.float32)
        self.assigned_counts = np.zeros(len(self.field_ids), dtype=np.int32)
        self.capacities = np.zeros(len(self.field_ids), dtype=np.int32)
        self.prediction_matrix = np.zeros((1, len(self.field_ids)), dtype=np.float32)
        self.confidence_matrix = np.zeros((1, len(self.field_ids)), dtype=np.float32)
        self.division_match_matrix = np.zeros((1, len(self.field_ids)), dtype=np.float32)
        self.experience_matrix = np.zeros((1, len(self.field_ids)), dtype=np.float32)
        self.eligible_matrix = np.zeros((1, len(self.field_ids)), dtype=np.float32)
        self.future_potential = np.zeros((1, len(self.field_ids)), dtype=np.float32)
        self.future_eligible_counts = np.zeros((1, len(self.field_ids)), dtype=np.float32)
        self.assignments: list[dict[str, Any]] = []
        self.initial_target = 0.0

    @property
    def current_employee_id(self) -> str | None:
        if self.position >= len(self.employee_order):
            return None
        return self.employee_order[self.position]

    def _random_scenario(self) -> Scenario:
        state_as_of = self.data.forecast_status().get("state_as_of")
        try:
            planning_start = date.fromisoformat(str(state_as_of)) + timedelta(days=1)
        except ValueError:
            planning_start = date.today()
        return self.data.create_scenario(
            template_date=self._rng.choice(self.data.complete_dates),
            planning_date=(planning_start + timedelta(days=self._rng.randrange(0, 60))).isoformat(),
            attendance_rate=self._rng.uniform(0.68, 1.0),
            demand_multiplier=self._rng.uniform(0.78, 1.25),
            same_division_only=self._rng.random() < 0.78,
            seed=self._rng.randrange(1, 1_000_000),
        )

    def _employee_order(self, employees: list[str], mode: str) -> list[str]:
        ordered = list(employees)
        if mode == "original":
            return ordered
        if mode == "random":
            self._rng.shuffle(ordered)
            return ordered

        def predictions(employee_id: str) -> list[float]:
            employee = self.data.employee_by_id[employee_id]
            values = []
            for field_id in self.field_ids:
                field = self.data.field_by_id[field_id]
                if self.scenario and self.scenario.same_division_only and employee.home_division != field.division:
                    continue
                if self.scenario and field_id not in self.scenario.demand_kg:
                    continue
                values.append(
                    self.data.predict_kg(
                        employee_id,
                        field_id,
                        self.scenario.planning_date if self.scenario else None,
                    )
                )
            return sorted(values, reverse=True)

        scored = []
        for employee_id in ordered:
            values = predictions(employee_id)
            maximum = values[0] if values else 0.0
            second = values[1] if len(values) > 1 else 0.0
            if mode == "specialists_first":
                score = maximum - second
            elif mode == "high_yield_first":
                score = maximum
            elif mode == "low_flexibility_first":
                flexibility = sum(value >= maximum * 0.90 for value in values) if maximum else 0
                score = -float(flexibility)
            else:
                raise ValueError(f"Unknown employee order mode: {mode}")
            scored.append((score, maximum, self._rng.random(), employee_id))
        scored.sort(reverse=True)
        return [item[-1] for item in scored]

    def _prepare_lookahead(self) -> None:
        rows = len(self.employee_order)
        columns = len(self.field_ids)
        self.prediction_matrix = np.zeros((rows, columns), dtype=np.float32)
        self.confidence_matrix = np.zeros((rows, columns), dtype=np.float32)
        self.division_match_matrix = np.zeros((rows, columns), dtype=np.float32)
        self.experience_matrix = np.zeros((rows, columns), dtype=np.float32)
        self.eligible_matrix = np.zeros((rows, columns), dtype=np.float32)
        active_fields = set(self.scenario.demand_kg) if self.scenario else set()
        bundles = self.data.prediction_bundle_map(
            self.employee_order,
            self.field_ids,
            self.scenario.planning_date if self.scenario else None,
        )
        for row_index, employee_id in enumerate(self.employee_order):
            employee = self.data.employee_by_id[employee_id]
            for field_index, field_id in enumerate(self.field_ids):
                field = self.data.field_by_id[field_id]
                division_match = employee.home_division == field.division
                details = bundles[(employee_id, field_id)]
                self.prediction_matrix[row_index, field_index] = float(details["expected_kg"])
                self.confidence_matrix[row_index, field_index] = float(details["confidence"])
                self.division_match_matrix[row_index, field_index] = float(division_match)
                self.experience_matrix[row_index, field_index] = float(field_id in employee.field_productivity)
                eligible = field_id in active_fields and (
                    not self.scenario or not self.scenario.same_division_only or division_match
                )
                self.eligible_matrix[row_index, field_index] = float(eligible)
        # Confidence-adjusted potential prevents sparse, optimistic predictions from
        # falsely making a field look well supplied to the policy.
        confidence_weight = 0.70 + 0.30 * self.confidence_matrix
        eligible_predictions = self.prediction_matrix * confidence_weight * self.eligible_matrix
        self.future_potential = np.flip(
            np.cumsum(np.flip(eligible_predictions, axis=0), axis=0),
            axis=0,
        ).copy()
        self.future_eligible_counts = np.flip(
            np.cumsum(np.flip(self.eligible_matrix, axis=0), axis=0),
            axis=0,
        ).copy()

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        if seed is not None:
            self._rng.seed(seed)
        options = options or {}
        self.scenario = options.get("scenario") or self._random_scenario()
        order_mode = options.get("order_mode")
        if order_mode is None:
            if options.get("shuffle") is False:
                order_mode = "original"
            else:
                order_mode = self._rng.choice(("random", "random", *ORDER_MODES[1:]))
        self.employee_order = self._employee_order(list(self.scenario.employee_ids), order_mode)
        self.position = 0
        self.assignments = []
        self.initial_demand.fill(0.0)
        self.remaining_demand.fill(0.0)
        self.assigned_counts.fill(0)
        self.capacities.fill(0)
        for field_id, target in self.scenario.demand_kg.items():
            index = self.field_index[field_id]
            self.initial_demand[index] = float(target)
            self.remaining_demand[index] = float(target)
            self.capacities[index] = int(self.scenario.capacity[field_id])
        self.initial_target = float(self.remaining_demand.sum())
        self._prepare_lookahead()
        return self._observation(), self._info()

    def _field_state(self, row_index: int) -> tuple[np.ndarray, ...]:
        predicted = self.prediction_matrix[row_index]
        confidence = self.confidence_matrix[row_index]
        remaining_slots = np.maximum(0, self.capacities - self.assigned_counts).astype(np.float32)
        demand_per_slot = np.divide(
            self.remaining_demand,
            np.maximum(remaining_slots, 1.0),
            out=np.zeros_like(self.remaining_demand),
        )
        future_potential = self.future_potential[row_index]
        supply_ratio = np.divide(
            future_potential,
            np.maximum(self.remaining_demand, 1.0),
            out=np.zeros_like(future_potential),
        )
        future_counts = self.future_eligible_counts[row_index]
        worker_ratio = np.divide(
            future_counts,
            np.maximum(remaining_slots, 1.0),
            out=np.zeros_like(future_counts),
        )
        fill_ratio = np.divide(
            self.initial_demand - self.remaining_demand,
            np.maximum(self.initial_demand, 1.0),
            out=np.zeros_like(self.remaining_demand),
        )
        shortage_risk = np.clip(1.0 - supply_ratio, 0.0, 1.0)
        return (
            predicted,
            confidence,
            remaining_slots,
            demand_per_slot,
            supply_ratio,
            worker_ratio,
            fill_ratio,
            shortage_risk,
        )

    def _observation(self) -> np.ndarray:
        if not self.scenario or not self.employee_order:
            return np.zeros(self.observation_space.shape, dtype=np.float32)
        row_index = min(self.position, len(self.employee_order) - 1)
        (
            predicted,
            confidence,
            remaining_slots,
            demand_per_slot,
            supply_ratio,
            worker_ratio,
            fill_ratio,
            shortage_risk,
        ) = self._field_state(row_index)
        progress = self.position / max(1, len(self.employee_order))
        remaining_people = (len(self.employee_order) - self.position) / max(1, len(self.employee_order))
        masks = self.action_masks()[:-1]
        valid_fields = int(np.count_nonzero(masks))
        active_fields = max(1, int(np.count_nonzero(self.remaining_demand > 0.05)))
        flexibility = valid_fields / active_fields
        max_feasible_prediction = float(predicted[masks].max()) / 45.0 if masks.any() else 0.0
        observation = np.concatenate([
            np.clip(self.remaining_demand / 300.0, 0.0, 5.0),
            np.clip(remaining_slots / 20.0, 0.0, 5.0),
            np.clip(predicted / 45.0, 0.0, 5.0),
            confidence,
            self.division_match_matrix[row_index],
            self.experience_matrix[row_index],
            np.clip(demand_per_slot / 45.0, 0.0, 5.0),
            np.clip(supply_ratio, 0.0, 5.0),
            np.clip(worker_ratio, 0.0, 5.0),
            shortage_risk,
            np.array([progress, remaining_people, flexibility, max_feasible_prediction], dtype=np.float32),
        ]).astype(np.float32)
        return observation

    def action_masks(self) -> np.ndarray:
        mask = np.zeros(self.action_space.n, dtype=bool)
        employee_id = self.current_employee_id
        if employee_id is None or not self.scenario:
            mask[self.idle_action] = True
            return mask
        employee = self.data.employee_by_id[employee_id]
        for index, field_id in enumerate(self.field_ids):
            if self.remaining_demand[index] <= 0.05:
                continue
            if self.assigned_counts[index] >= self.capacities[index]:
                continue
            field = self.data.field_by_id[field_id]
            if self.scenario.same_division_only and employee.home_division != field.division:
                continue
            mask[index] = True
        mask[self.idle_action] = True
        return mask

    def _action_utility(self, field_index: int) -> float:
        """Opportunity-aware utility used only for reward shaping."""
        predicted = float(self.prediction_matrix[self.position, field_index])
        confidence = float(self.confidence_matrix[self.position, field_index])
        remaining = float(self.remaining_demand[field_index])
        fulfilled = min(remaining, predicted)
        waste = max(0.0, predicted - remaining)
        future = float(self.future_potential[self.position, field_index])
        supply_ratio = future / max(remaining, 1.0)
        scarcity = 1.0 + 0.75 * max(0.0, 1.0 - min(1.0, supply_ratio))
        reliability = 0.75 + 0.25 * confidence
        return fulfilled * scarcity * reliability - 0.60 * waste

    def step(self, action):
        if not self.scenario or self.current_employee_id is None:
            raise RuntimeError("reset() must be called before step()")
        action = int(action)
        employee_id = self.current_employee_id
        valid_mask = self.action_masks()
        reward = 0.0
        valid_field_indices = np.flatnonzero(valid_mask[:-1])
        best_utility = max((self._action_utility(int(i)) for i in valid_field_indices), default=0.0)
        if action < 0 or action >= self.action_space.n or not valid_mask[action]:
            reward = -8.0
        elif action == self.idle_action:
            # Idling is acceptable only when no useful assignment remains.
            reward = -2.5 * best_utility / max(1.0, self.initial_target)
        else:
            field_id = self.field_ids[action]
            predicted = float(self.prediction_matrix[self.position, action])
            confidence = float(self.confidence_matrix[self.position, action])
            before = float(self.remaining_demand[action])
            fulfilled = min(before, predicted)
            waste = max(0.0, predicted - before)
            chosen_utility = self._action_utility(action)
            regret = max(0.0, best_utility - chosen_utility)
            future = float(self.future_potential[self.position, action])
            supply_ratio = future / max(before, 1.0)
            scarcity = max(0.0, 1.0 - min(1.0, supply_ratio))

            self.remaining_demand[action] = max(0.0, before - predicted)
            self.assigned_counts[action] += 1
            employee = self.data.employee_by_id[employee_id]
            field = self.data.field_by_id[field_id]

            # Marginal crop coverage is the dominant signal. Scarcity, confidence
            # and regret refine the choice without overriding the final objective.
            reward = 80.0 * fulfilled / max(1.0, self.initial_target)
            reward += 20.0 * scarcity * fulfilled / max(1.0, self.initial_target)
            reward += 4.0 * confidence * fulfilled / max(1.0, self.initial_target)
            reward -= 25.0 * waste / max(1.0, self.initial_target)
            reward -= 18.0 * regret / max(1.0, self.initial_target)
            if self.remaining_demand[action] <= 0.05:
                reward += 0.20
            if field_id in employee.field_productivity:
                reward += 0.025
            if employee.home_division != field.division:
                reward -= 0.30
            self.assignments.append({
                "employee_id": employee_id,
                "field_id": field_id,
                "predicted_kg": predicted,
                "forecast_confidence": confidence,
            })
        self.position += 1
        terminated = self.position >= len(self.employee_order)
        truncated = False
        if terminated:
            coverage = self.coverage
            unmet_share = 1.0 - coverage
            active = self.initial_demand > 0.05
            field_coverage = np.divide(
                self.initial_demand - self.remaining_demand,
                np.maximum(self.initial_demand, 1.0),
                out=np.ones_like(self.initial_demand),
            )
            minimum_field_coverage = float(field_coverage[active].min()) if active.any() else 1.0
            unmet_fields = float(np.count_nonzero(self.remaining_demand > 0.05))
            reward += 55.0 * coverage
            reward += 6.0 * minimum_field_coverage
            reward -= 28.0 * unmet_share
            reward -= 0.12 * unmet_fields
            if coverage >= TARGET_COVERAGE:
                reward += 3.0 + 12.0 * (coverage - TARGET_COVERAGE)
            else:
                reward -= 8.0 * (TARGET_COVERAGE - coverage)
        return self._observation(), float(reward), terminated, truncated, self._info()

    @property
    def coverage(self) -> float:
        if self.initial_target <= 0:
            return 1.0
        return max(0.0, min(1.0, 1.0 - float(self.remaining_demand.sum()) / self.initial_target))

    def _info(self) -> dict[str, Any]:
        return {
            "coverage": self.coverage,
            "assigned_workers": len(self.assignments),
            "remaining_demand_kg": round(float(self.remaining_demand.sum()), 3),
            "model_schema_version": MODEL_SCHEMA_VERSION,
            "forecast_method": self.data.forecast_status(
                self.scenario.planning_date if self.scenario else None
            ).get("method"),
        }

    def result(self, policy="rl", policy_status="trained policy") -> dict[str, Any]:
        if not self.scenario:
            raise RuntimeError("No scenario is active")
        return build_plan(self.data, self.scenario, self.assignments, policy, policy_status)
