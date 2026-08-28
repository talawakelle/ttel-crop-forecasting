from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any, Iterable
import math
import random

import gymnasium as gym
from gymnasium import spaces
import numpy as np

from .baseline import greedy_allocate
from .data import Scenario, WorkforceData, validate_plan


@dataclass(frozen=True)
class DisruptionConfig:
    demand_sigma: float
    worker_absence_rate: float
    late_absence_rate: float
    reserve_worker_rate: float
    worker_output_sigma: float
    field_output_sigma: float
    late_demand_sigma: float
    allow_cross_division: bool
    max_cross_division_rate: float
    morning_fraction: float = 0.35
    decision_fractions: tuple[float, float] = (0.35, 0.30)


CURRICULUM: dict[str, DisruptionConfig] = {
    "easy": DisruptionConfig(0.04, 0.00, 0.00, 0.04, 0.04, 0.02, 0.02, False, 0.00),
    "medium": DisruptionConfig(0.08, 0.02, 0.01, 0.08, 0.08, 0.05, 0.05, False, 0.00),
    "full": DisruptionConfig(0.15, 0.05, 0.025, 0.12, 0.12, 0.08, 0.08, True, 0.08),
    "extreme": DisruptionConfig(0.24, 0.09, 0.05, 0.16, 0.18, 0.12, 0.14, True, 0.15),
}
MIXED_DIFFICULTIES = ("easy", "medium", "full", "full", "extreme")


class DynamicReallocationEnv(gym.Env):
    """Event-driven intraday reallocation environment.

    A forecast-aware morning plan works for the first part of the shift. The RL
    agent then makes two genuine replanning rounds (midday and afternoon) after
    attendance, crop-demand and productivity shocks. Each available employee can
    be kept, moved or idled in every replanning round. The environment never puts
    reference-policy outcomes in the observation, preventing future-information
    leakage.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        data: WorkforceData,
        *,
        scenario_dates: Iterable[str] | None = None,
        seed: int = 42,
        difficulty: str = "full",
    ):
        super().__init__()
        if difficulty not in CURRICULUM and difficulty != "mixed":
            raise ValueError(f"Unknown difficulty: {difficulty}")
        self.data = data
        self.scenario_dates = list(scenario_dates or data.complete_dates)
        if not self.scenario_dates:
            raise ValueError("At least one scenario date is required")
        self.requested_difficulty = difficulty
        self.difficulty = difficulty
        self._rng = random.Random(seed)
        self.field_ids = [field.id for field in data.fields]
        self.field_index = {field_id: index for index, field_id in enumerate(self.field_ids)}
        self.idle_action = len(self.field_ids)
        self.action_space = spaces.Discrete(len(self.field_ids) + 1)
        # Ten per-field groups and ten global/current-worker features.
        self.observation_space = spaces.Box(
            low=0.0,
            high=5.0,
            shape=(len(self.field_ids) * 10 + 10,),
            dtype=np.float32,
        )

        self.config = CURRICULUM["full"]
        self.scenario: Scenario | None = None
        self.initial_demand = np.zeros(len(self.field_ids), dtype=np.float32)
        self.remaining_demand = np.zeros(len(self.field_ids), dtype=np.float32)
        self.post_morning_remaining = np.zeros(len(self.field_ids), dtype=np.float32)
        self.capacities = np.zeros(len(self.field_ids), dtype=np.int32)
        self.stage_counts = np.zeros(len(self.field_ids), dtype=np.int32)
        self.initial_target = 0.0

        self.employee_ids: list[str] = []
        self.employee_row: dict[str, int] = {}
        self.original_field: dict[str, str | None] = {}
        self.current_field: dict[str, str | None] = {}
        self.move_count: dict[str, int] = {}
        self.reserve_ids: set[str] = set()
        self.max_cross_division_moves = 0
        self.cross_division_employee_ids: set[str] = set()
        self.stage_orders: list[list[str]] = []
        self.stage_index = 0
        self.position = 0

        self.prediction_matrix = np.zeros((1, len(self.field_ids)), dtype=np.float32)
        self.confidence_matrix = np.zeros((1, len(self.field_ids)), dtype=np.float32)
        self.conservative_matrix = np.zeros((1, len(self.field_ids)), dtype=np.float32)
        self.actual_output_matrix = np.zeros((1, len(self.field_ids)), dtype=np.float32)
        self.eligible_matrix = np.zeros((1, len(self.field_ids)), dtype=np.float32)
        self.late_demand_adjustment = np.zeros(len(self.field_ids), dtype=np.float32)

        self.morning_segments: list[dict[str, Any]] = []
        self.assignments: list[dict[str, Any]] = []
        self.no_replan_metrics: dict[str, float] = {}
        self.greedy_replan_metrics: dict[str, float] = {}
        self.perfect_info_metrics: dict[str, float] = {}

    @property
    def current_stage_fraction(self) -> float:
        return float(self.config.decision_fractions[self.stage_index])

    @property
    def current_employee_id(self) -> str | None:
        if self.stage_index >= len(self.stage_orders):
            return None
        order = self.stage_orders[self.stage_index]
        if self.position >= len(order):
            return None
        return order[self.position]

    def _sample_config(self) -> None:
        if self.requested_difficulty == "mixed":
            selected = self._rng.choice(MIXED_DIFFICULTIES)
        else:
            selected = self.requested_difficulty
        self.difficulty = selected
        base = CURRICULUM[selected]
        if selected in {"full", "extreme"} and self.data.crop_forecaster is not None:
            calibrated = max(0.05, min(0.30, float(self.data.crop_forecaster.representative_wape())))
            base = replace(base, demand_sigma=max(base.demand_sigma, calibrated))
        # Domain randomisation prevents the policy from memorising one shock size.
        scale = self._rng.uniform(0.80, 1.20)
        self.config = replace(
            base,
            demand_sigma=min(0.35, base.demand_sigma * scale),
            worker_absence_rate=min(0.15, base.worker_absence_rate * self._rng.uniform(0.75, 1.25)),
            late_absence_rate=min(0.10, base.late_absence_rate * self._rng.uniform(0.75, 1.25)),
            worker_output_sigma=min(0.25, base.worker_output_sigma * self._rng.uniform(0.80, 1.20)),
            field_output_sigma=min(0.18, base.field_output_sigma * self._rng.uniform(0.80, 1.20)),
            late_demand_sigma=min(0.20, base.late_demand_sigma * self._rng.uniform(0.80, 1.20)),
        )

    def _planning_date(self, offset: int) -> str:
        state_as_of = self.data.forecast_status().get("state_as_of")
        try:
            start = date.fromisoformat(str(state_as_of)) + timedelta(days=1)
        except (TypeError, ValueError):
            start = date.today()
        return (start + timedelta(days=int(offset) % 90)).isoformat()

    def _scenario(self) -> Scenario:
        template_date = self._rng.choice(self.scenario_dates)
        return self.data.create_scenario(
            template_date=template_date,
            planning_date=self._planning_date(self._rng.randrange(0, 90)),
            attendance_rate=self._rng.uniform(0.78, 1.0),
            demand_multiplier=self._rng.uniform(0.90, 1.10),
            same_division_only=not self.config.allow_cross_division or self._rng.random() < 0.65,
            seed=self._rng.randrange(1, 10_000_000),
        )

    def _positive_lognormal(self, sigma: float) -> float:
        if sigma <= 0.0:
            return 1.0
        return math.exp(self._rng.gauss(-0.5 * sigma * sigma, sigma))

    def _field_coverages(self, remaining: np.ndarray) -> np.ndarray:
        active = self.initial_demand > 0.0
        values = np.ones(len(self.field_ids), dtype=np.float32)
        values[active] = 1.0 - np.divide(
            remaining[active],
            np.maximum(self.initial_demand[active], 1.0),
        )
        return np.clip(values, 0.0, 1.0)

    def _bottom_quartile_coverage(self, remaining: np.ndarray) -> float:
        active_values = self._field_coverages(remaining)[self.initial_demand > 0.0]
        if not len(active_values):
            return 1.0
        count = max(1, math.ceil(len(active_values) * 0.25))
        return float(np.mean(np.sort(active_values)[:count]))

    def _prepare_episode(self) -> None:
        if self.scenario is None:
            raise RuntimeError("Scenario missing")
        baseline = greedy_allocate(self.data, self.scenario)
        baseline_assignments = baseline["assignments"]
        assigned_ids = [item["employee_id"] for item in baseline_assignments]
        self.original_field = {item["employee_id"]: item["field_id"] for item in baseline_assignments}

        early_survivors = [
            employee_id for employee_id in assigned_ids
            if self._rng.random() >= self.config.worker_absence_rate
        ]
        assigned_set = set(assigned_ids)
        reserve_candidates = [
            employee_id for employee_id in self.scenario.employee_ids
            if employee_id not in assigned_set
        ]
        self._rng.shuffle(reserve_candidates)
        reserve_count = min(
            len(reserve_candidates),
            max(0, round(len(assigned_ids) * self.config.reserve_worker_rate)),
        )
        reserves = reserve_candidates[:reserve_count]
        self.reserve_ids = set(reserves)
        for employee_id in reserves:
            self.original_field[employee_id] = None

        self.employee_ids = early_survivors + reserves
        self.employee_row = {employee_id: row for row, employee_id in enumerate(self.employee_ids)}
        self.current_field = dict(self.original_field)
        self.move_count = {employee_id: 0 for employee_id in self.employee_ids}
        self.max_cross_division_moves = (
            0 if self.scenario.same_division_only
            else max(1, round(len(self.employee_ids) * self.config.max_cross_division_rate))
        )
        self.cross_division_employee_ids = set()

        self.initial_demand.fill(0.0)
        self.remaining_demand.fill(0.0)
        self.capacities.fill(0)
        active_fields = set(self.scenario.demand_kg)
        disrupted_demand: dict[str, float] = {}
        disrupted_capacity: dict[str, int] = {}
        for field_id, target in list(self.scenario.demand_kg.items()):
            index = self.field_index[field_id]
            updated = float(target) * self._positive_lognormal(self.config.demand_sigma)
            self.initial_demand[index] = updated
            self.remaining_demand[index] = updated
            original_capacity = int(self.scenario.capacity[field_id])
            capacity = max(
                original_capacity,
                math.ceil(updated / max(1.0, self.data.field_by_id[field_id].median_worker_kg)),
            )
            self.capacities[index] = capacity
            disrupted_demand[field_id] = round(updated, 3)
            disrupted_capacity[field_id] = capacity
        self.scenario.demand_kg = disrupted_demand
        self.scenario.capacity = disrupted_capacity
        self.initial_target = float(self.initial_demand.sum())

        rows = max(1, len(self.employee_ids))
        columns = len(self.field_ids)
        self.prediction_matrix = np.zeros((rows, columns), dtype=np.float32)
        self.confidence_matrix = np.zeros((rows, columns), dtype=np.float32)
        self.conservative_matrix = np.zeros((rows, columns), dtype=np.float32)
        self.actual_output_matrix = np.zeros((rows, columns), dtype=np.float32)
        self.eligible_matrix = np.zeros((rows, columns), dtype=np.float32)
        bundles = self.data.prediction_bundle_map(
            self.employee_ids,
            self.field_ids,
            self.scenario.planning_date,
        ) if self.employee_ids else {}
        worker_factors = {
            employee_id: self._positive_lognormal(self.config.worker_output_sigma)
            for employee_id in self.employee_ids
        }
        field_factors = {
            field_id: self._positive_lognormal(self.config.field_output_sigma)
            for field_id in self.field_ids
        }
        for row, employee_id in enumerate(self.employee_ids):
            employee = self.data.employee_by_id[employee_id]
            for column, field_id in enumerate(self.field_ids):
                field = self.data.field_by_id[field_id]
                details = bundles[(employee_id, field_id)]
                expected = float(details["expected_kg"])
                confidence = float(details["confidence"])
                uncertainty = float(details.get("uncertainty_kg", max(1.0, expected * 0.25)))
                conservative = max(0.25, expected - 0.65 * uncertainty)
                eligible = field_id in active_fields and (
                    not self.scenario.same_division_only or employee.home_division == field.division
                )
                self.prediction_matrix[row, column] = expected
                self.confidence_matrix[row, column] = confidence
                self.conservative_matrix[row, column] = conservative
                self.actual_output_matrix[row, column] = max(
                    0.25,
                    expected * worker_factors[employee_id] * field_factors[field_id],
                )
                self.eligible_matrix[row, column] = float(eligible)

        # Morning work is completed before the first RL decision.
        self.morning_segments = []
        for employee_id in early_survivors:
            field_id = self.original_field.get(employee_id)
            if field_id not in self.field_index:
                continue
            row = self.employee_row[employee_id]
            column = self.field_index[field_id]
            output = float(self.actual_output_matrix[row, column]) * self.config.morning_fraction
            fulfilled = min(float(self.remaining_demand[column]), output)
            self.remaining_demand[column] = max(0.0, float(self.remaining_demand[column]) - output)
            self.morning_segments.append({
                "stage": "morning",
                "stage_index": -1,
                "employee_id": employee_id,
                "field_id": field_id,
                "home_division": self.data.employee_by_id[employee_id].home_division,
                "division": self.data.field_by_id[field_id].division,
                "fraction_of_day": self.config.morning_fraction,
                "actual_simulated_kg": output,
                "fulfilled_kg": fulfilled,
                "changed": False,
                "cross_division": False,
            })
        self.post_morning_remaining = self.remaining_demand.copy()

        # Late absences and progressive reserve release create real stage-to-stage changes.
        stage_zero = [
            employee_id for employee_id in early_survivors
            if self._rng.random() >= self.config.late_absence_rate
        ]
        first_release_count = math.ceil(len(reserves) * 0.60)
        stage_zero.extend(reserves[:first_release_count])
        stage_one = [
            employee_id for employee_id in stage_zero
            if employee_id in self.reserve_ids or self._rng.random() >= self.config.late_absence_rate
        ]
        stage_one.extend(employee_id for employee_id in reserves[first_release_count:] if employee_id not in stage_one)
        self._rng.shuffle(stage_zero)
        self._rng.shuffle(stage_one)
        self.stage_orders = [stage_zero, stage_one]

        self.late_demand_adjustment = np.zeros(len(self.field_ids), dtype=np.float32)
        for field_id in active_fields:
            index = self.field_index[field_id]
            factor = self._positive_lognormal(self.config.late_demand_sigma)
            self.late_demand_adjustment[index] = float(self.initial_demand[index]) * (factor - 1.0) * 0.35

        self.no_replan_metrics = self._simulate_reference("no_replan")
        self.greedy_replan_metrics = self._simulate_reference("greedy")
        self.perfect_info_metrics = self._simulate_reference("perfect_info")

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
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
        while self.stage_index < len(self.stage_orders) and not self.stage_orders[self.stage_index]:
            if self._advance_stage():
                break
        return self._observation(), self._info()

    def _action_masks_for(
        self,
        employee_id: str,
        counts: np.ndarray,
        remaining: np.ndarray,
        current_fields: dict[str, str | None],
        move_counts: dict[str, int],
        cross_division_employee_ids: set[str] | None = None,
        max_cross_division: int | None = None,
    ) -> np.ndarray:
        masks = np.zeros(len(self.field_ids) + 1, dtype=bool)
        row = self.employee_row[employee_id]
        eligible = self.eligible_matrix[row] > 0.5
        masks[:-1] = eligible & (counts < self.capacities) & (remaining > 0.05)
        transfer_employees = (
            self.cross_division_employee_ids
            if cross_division_employee_ids is None
            else cross_division_employee_ids
        )
        transfer_limit = self.max_cross_division_moves if max_cross_division is None else int(max_cross_division)
        home = self.data.employee_by_id[employee_id].home_division
        current = current_fields.get(employee_id)
        currently_cross_division = bool(
            current in self.field_index
            and self.data.field_by_id[current].division != home
        )
        for index, field_id in enumerate(self.field_ids):
            destination_cross_division = self.data.field_by_id[field_id].division != home
            would_create_new_transfer = destination_cross_division and not currently_cross_division
            if (
                would_create_new_transfer
                and employee_id not in transfer_employees
                and len(transfer_employees) >= transfer_limit
            ):
                masks[index] = False
        # One voluntary move per day. A second move is allowed only when the current
        # field is complete or inactive, avoiding unrealistic worker shuttling.
        if move_counts.get(employee_id, 0) >= 1 and current in self.field_index:
            current_index = self.field_index[current]
            if masks[current_index] and remaining[current_index] > 0.05:
                masks[:-1] = False
                masks[current_index] = True
        masks[self.idle_action] = True
        return masks

    def action_masks(self) -> np.ndarray:
        employee_id = self.current_employee_id
        if employee_id is None:
            masks = np.zeros(len(self.field_ids) + 1, dtype=bool)
            masks[self.idle_action] = True
            return masks
        return self._action_masks_for(
            employee_id,
            self.stage_counts,
            self.remaining_demand,
            self.current_field,
            self.move_count,
            self.cross_division_employee_ids,
            self.max_cross_division_moves,
        )

    def _pending_conservative_output(self) -> np.ndarray:
        pending = np.zeros(len(self.field_ids), dtype=np.float32)
        if self.stage_index >= len(self.stage_orders):
            return pending
        fraction = self.current_stage_fraction
        for employee_id in self.stage_orders[self.stage_index][self.position + 1:]:
            current = self.current_field.get(employee_id)
            if current not in self.field_index:
                continue
            column = self.field_index[current]
            row = self.employee_row[employee_id]
            if self.eligible_matrix[row, column] > 0.5:
                pending[column] += self.conservative_matrix[row, column] * fraction
        return pending

    def _observation(self) -> np.ndarray:
        employee_id = self.current_employee_id
        if employee_id is None:
            return np.zeros(self.observation_space.shape, dtype=np.float32)
        row = self.employee_row[employee_id]
        fraction = self.current_stage_fraction
        confidence = self.confidence_matrix[row]
        predicted = self.prediction_matrix[row] * fraction
        conservative = self.conservative_matrix[row] * fraction
        remaining_slots = np.maximum(0, self.capacities - self.stage_counts).astype(np.float32)
        capacity_ratio = np.divide(
            remaining_slots,
            np.maximum(self.capacities, 1),
            out=np.zeros_like(remaining_slots),
        )
        shortage = np.divide(
            self.remaining_demand,
            np.maximum(self.initial_demand, 1.0),
            out=np.zeros_like(self.remaining_demand),
        )
        current = np.zeros(len(self.field_ids), dtype=np.float32)
        current_id = self.current_field.get(employee_id)
        if current_id in self.field_index:
            current[self.field_index[current_id]] = 1.0
        active = (self.initial_demand > 0.0).astype(np.float32)
        pending = self._pending_conservative_output()
        pending_ratio = np.divide(
            pending,
            np.maximum(self.remaining_demand, 1.0),
            out=np.zeros_like(pending),
        )
        field_coverages = self._field_coverages(self.remaining_demand)
        progress = self.position / max(1, len(self.stage_orders[self.stage_index]))
        overall_coverage = 1.0 - float(self.remaining_demand.sum()) / max(1.0, self.initial_target)
        minimum_coverage = float(np.min(field_coverages[self.initial_demand > 0.0])) if np.any(self.initial_demand > 0.0) else 1.0
        masks = self._action_masks_for(
            employee_id,
            self.stage_counts,
            self.remaining_demand,
            self.current_field,
            self.move_count,
            self.cross_division_employee_ids,
            self.max_cross_division_moves,
        )[:-1]
        flexibility = float(np.count_nonzero(masks)) / max(1, np.count_nonzero(active))
        reserve = float(employee_id in self.reserve_ids)
        remaining_time = sum(self.config.decision_fractions[self.stage_index:])
        move_count = min(2.0, float(self.move_count.get(employee_id, 0))) / 2.0
        transfer_budget_remaining = (
            0.0 if self.max_cross_division_moves <= 0
            else max(0.0, 1.0 - len(self.cross_division_employee_ids) / self.max_cross_division_moves)
        )
        observation = np.concatenate([
            np.clip(shortage, 0.0, 5.0),
            np.clip(self.initial_demand / 500.0, 0.0, 5.0),
            np.clip(capacity_ratio, 0.0, 5.0),
            np.clip(predicted / 20.0, 0.0, 5.0),
            np.clip(conservative / 20.0, 0.0, 5.0),
            np.clip(confidence, 0.0, 1.0),
            np.clip(field_coverages, 0.0, 1.0),
            current,
            active,
            np.clip(pending_ratio, 0.0, 5.0),
            np.asarray([
                (self.stage_index + 1) / max(1, len(self.stage_orders)),
                progress,
                max(0.0, min(1.0, overall_coverage)),
                max(0.0, min(1.0, minimum_coverage)),
                flexibility,
                reserve,
                float(self.scenario.same_division_only if self.scenario else True),
                transfer_budget_remaining,
                remaining_time,
                move_count,
            ], dtype=np.float32),
        ])
        return observation.astype(np.float32)

    def _apply_late_demand_update(self, remaining: np.ndarray) -> None:
        remaining += self.late_demand_adjustment
        np.maximum(remaining, 0.0, out=remaining)

    def _reference_action(
        self,
        mode: str,
        employee_id: str,
        stage_index: int,
        counts: np.ndarray,
        remaining: np.ndarray,
        current_fields: dict[str, str | None],
        move_counts: dict[str, int],
        cross_division_employee_ids: set[str],
    ) -> int:
        masks = self._action_masks_for(
            employee_id, counts, remaining, current_fields, move_counts,
            cross_division_employee_ids=cross_division_employee_ids,
            max_cross_division=self.max_cross_division_moves,
        )
        current_id = current_fields.get(employee_id)
        if mode == "no_replan" and current_id in self.field_index:
            current_index = self.field_index[current_id]
            return current_index if masks[current_index] else self.idle_action
        row = self.employee_row[employee_id]
        fraction = float(self.config.decision_fractions[stage_index])
        best_action = self.idle_action
        best_score = 0.0
        for index in np.flatnonzero(masks[:-1]):
            if mode == "perfect_info":
                output = float(self.actual_output_matrix[row, index]) * fraction
            else:
                output = float(self.conservative_matrix[row, index]) * fraction
            fulfilled = min(float(remaining[index]), output)
            shortage = float(remaining[index]) / max(1.0, float(self.initial_demand[index]))
            field_id = self.field_ids[index]
            changed = current_id is not None and field_id != current_id
            employee = self.data.employee_by_id[employee_id]
            destination_cross = employee.home_division != self.data.field_by_id[field_id].division
            currently_cross = bool(
                current_id in self.field_index
                and self.data.field_by_id[current_id].division != employee.home_division
            )
            new_cross_transfer = destination_cross and not currently_cross
            score = fulfilled * (1.0 + 0.75 * shortage)
            score -= 0.45 * int(changed) + 1.75 * int(new_cross_transfer)
            score -= 0.25 * move_counts.get(employee_id, 0) * int(changed)
            if score > best_score:
                best_score = score
                best_action = int(index)
        return best_action

    def _simulate_reference(self, mode: str) -> dict[str, Any]:
        remaining = self.post_morning_remaining.copy()
        conservative_remaining = self.post_morning_remaining.copy()
        current_fields = dict(self.original_field)
        move_counts = {employee_id: 0 for employee_id in self.employee_ids}
        changes = 0
        cross_division_employees: set[str] = set()
        cross_division_segments = 0
        assigned = 0
        assignments: list[dict[str, Any]] = []
        for stage_index, order in enumerate(self.stage_orders):
            if stage_index > 0:
                self._apply_late_demand_update(remaining)
                self._apply_late_demand_update(conservative_remaining)
            counts = np.zeros(len(self.field_ids), dtype=np.int32)
            fraction = float(self.config.decision_fractions[stage_index])
            for employee_id in order:
                action = self._reference_action(
                    mode,
                    employee_id,
                    stage_index,
                    counts,
                    remaining,
                    current_fields,
                    move_counts,
                    cross_division_employees,
                )
                if action == self.idle_action:
                    continue
                field_id = self.field_ids[action]
                row = self.employee_row[employee_id]
                actual = float(self.actual_output_matrix[row, action]) * fraction
                conservative = float(self.conservative_matrix[row, action]) * fraction
                remaining[action] = max(0.0, float(remaining[action]) - actual)
                conservative_remaining[action] = max(
                    0.0, float(conservative_remaining[action]) - conservative
                )
                counts[action] += 1
                assigned += 1
                previous = current_fields.get(employee_id)
                changed = previous is not None and previous != field_id
                move_counts[employee_id] += int(changed)
                current_fields[employee_id] = field_id
                changes += int(changed)
                employee = self.data.employee_by_id[employee_id]
                destination_cross = employee.home_division != self.data.field_by_id[field_id].division
                previous_cross = bool(
                    previous in self.field_index
                    and self.data.field_by_id[previous].division != employee.home_division
                )
                if destination_cross:
                    cross_division_segments += 1
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
                    "conservative_kg": conservative,
                    "changed": changed,
                    "cross_division": destination_cross,
                    "new_cross_division_transfer": destination_cross and not previous_cross,
                    "decision_source": mode,
                })
        coverage = 1.0 - float(remaining.sum()) / max(1.0, self.initial_target)
        conservative_coverage = 1.0 - float(conservative_remaining.sum()) / max(1.0, self.initial_target)
        field_coverages = self._field_coverages(remaining)
        active = self.initial_demand > 0.0
        critical = int(np.sum(field_coverages[active] < 0.75)) if np.any(active) else 0
        return {
            "coverage": max(0.0, min(1.0, coverage)),
            "conservative_coverage": max(0.0, min(1.0, conservative_coverage)),
            "bottom_quartile_coverage": self._bottom_quartile_coverage(remaining),
            "critical_fields": float(critical),
            "assigned_segments": float(assigned),
            "changes": float(changes),
            "transfers": float(len(cross_division_employees)),
            "cross_division_segments": float(cross_division_segments),
            "remaining": remaining.copy(),
            "conservative_remaining": conservative_remaining.copy(),
            "assignments": assignments,
        }

    def _advance_stage(self) -> bool:
        while True:
            self.stage_index += 1
            self.position = 0
            self.stage_counts.fill(0)
            if self.stage_index >= len(self.stage_orders):
                return True
            self._apply_late_demand_update(self.remaining_demand)
            if self.stage_orders[self.stage_index]:
                return False

    def step(self, action):
        if self.scenario is None:
            raise RuntimeError("reset() must be called before step()")
        employee_id = self.current_employee_id
        if employee_id is None:
            return self._observation(), 0.0, True, False, self._info()
        action = int(action)
        masks = self.action_masks()
        reward = 0.0
        if action < 0 or action >= len(masks) or not masks[action]:
            reward = -5.0
            action = self.idle_action
        row = self.employee_row[employee_id]
        current_id = self.current_field.get(employee_id)
        fraction = self.current_stage_fraction
        shortage = np.divide(
            self.remaining_demand,
            np.maximum(self.initial_demand, 1.0),
            out=np.zeros_like(self.remaining_demand),
        )
        if action == self.idle_action:
            feasible = np.flatnonzero(masks[:-1])
            if len(feasible):
                best_index = max(
                    feasible,
                    key=lambda index: min(
                        float(self.remaining_demand[index]),
                        float(self.conservative_matrix[row, index]) * fraction,
                    ) * (1.0 + float(shortage[index])),
                )
                opportunity = min(
                    float(self.remaining_demand[best_index]),
                    float(self.conservative_matrix[row, best_index]) * fraction,
                )
                reward -= 25.0 * opportunity / max(1.0, self.initial_target)
            self.assignments.append({
                "stage": "midday" if self.stage_index == 0 else "afternoon",
                "stage_index": self.stage_index,
                "employee_id": employee_id,
                "field_id": None,
                "fraction_of_day": fraction,
            })
        else:
            field_id = self.field_ids[action]
            actual = float(self.actual_output_matrix[row, action]) * fraction
            fulfilled = min(float(self.remaining_demand[action]), actual)
            waste = max(0.0, actual - float(self.remaining_demand[action]))
            confidence = float(self.confidence_matrix[row, action])
            changed = current_id is not None and current_id != field_id
            employee = self.data.employee_by_id[employee_id]
            destination_cross = employee.home_division != self.data.field_by_id[field_id].division
            currently_cross = bool(
                current_id in self.field_index
                and self.data.field_by_id[current_id].division != employee.home_division
            )
            new_cross_transfer = destination_cross and not currently_cross
            scarcity_weight = 1.0 + 1.25 * float(shortage[action])
            reward += 105.0 * fulfilled * scarcity_weight / max(1.0, self.initial_target)
            reward += 5.0 * confidence * fulfilled / max(1.0, self.initial_target)
            reward -= 28.0 * waste / max(1.0, self.initial_target)
            reward -= (0.05 + 0.08 * self.move_count.get(employee_id, 0)) * int(changed)
            reward -= 0.55 * int(new_cross_transfer)
            if current_id == field_id:
                reward += 0.012
            self.remaining_demand[action] = max(0.0, float(self.remaining_demand[action]) - actual)
            self.stage_counts[action] += 1
            self.move_count[employee_id] = self.move_count.get(employee_id, 0) + int(changed)
            self.current_field[employee_id] = field_id
            if new_cross_transfer:
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
                "conservative_kg": float(self.conservative_matrix[row, action]) * fraction,
                "actual_simulated_kg": actual,
                "fulfilled_kg": fulfilled,
                "forecast_confidence": confidence,
                "changed": changed,
                "cross_division": destination_cross,
                "new_cross_division_transfer": new_cross_transfer,
            })

        self.position += 1
        stage_done = self.position >= len(self.stage_orders[self.stage_index])
        all_demand_done = float(self.remaining_demand.sum()) <= 0.05
        terminated = all_demand_done
        if stage_done and not terminated:
            before_bottom = self._bottom_quartile_coverage(self.remaining_demand)
            terminated = self._advance_stage()
            if not terminated:
                after_bottom = self._bottom_quartile_coverage(self.remaining_demand)
                reward += 4.0 * (after_bottom - before_bottom)
        if terminated:
            coverage = 1.0 - float(self.remaining_demand.sum()) / max(1.0, self.initial_target)
            bottom = self._bottom_quartile_coverage(self.remaining_demand)
            no_replan = float(self.no_replan_metrics.get("coverage", 0.0))
            no_replan_bottom = float(self.no_replan_metrics.get("bottom_quartile_coverage", 0.0))
            reward += 85.0 * (coverage - no_replan)
            reward += 20.0 * (bottom - no_replan_bottom)
            reward += 12.0 * coverage + 6.0 * bottom
        return self._observation(), float(reward), terminated, False, self._info()

    def _info(self) -> dict[str, Any]:
        coverage = 1.0 - float(self.remaining_demand.sum()) / max(1.0, self.initial_target)
        return {
            "difficulty": self.difficulty,
            "stage_index": self.stage_index,
            "stage": "complete" if self.stage_index >= len(self.stage_orders) else ("midday" if self.stage_index == 0 else "afternoon"),
            "position": self.position,
            "stage_employee_count": 0 if self.stage_index >= len(self.stage_orders) else len(self.stage_orders[self.stage_index]),
            "coverage_pct": round(100.0 * max(0.0, min(1.0, coverage)), 3),
            "bottom_quartile_field_coverage_pct": round(100.0 * self._bottom_quartile_coverage(self.remaining_demand), 3),
        }

    def _stage_violations(self) -> list[str]:
        if self.scenario is None:
            return ["Scenario missing"]
        violations: list[str] = []
        for stage_index in range(len(self.stage_orders)):
            stage_assignments = [
                item for item in self.assignments
                if item.get("stage_index") == stage_index and item.get("field_id")
            ]
            for violation in validate_plan(self.scenario, stage_assignments):
                violations.append(f"stage {stage_index + 1}: {violation}")
        return violations

    def result(self, policy: str = "event-driven-dynamic-rl") -> dict[str, Any]:
        if self.scenario is None:
            raise RuntimeError("No episode result")
        coverage = 1.0 - float(self.remaining_demand.sum()) / max(1.0, self.initial_target)
        normalized = [item for item in self.assignments if item.get("field_id")]
        violations = self._stage_violations()
        changes = sum(int(item.get("changed", False)) for item in normalized)
        transfer_segments = sum(int(item.get("cross_division", False)) for item in normalized)
        transfer_workers = len({
            item["employee_id"] for item in normalized
            if item.get("new_cross_division_transfer", False)
        })
        field_coverages = self._field_coverages(self.remaining_demand)
        active = self.initial_demand > 0.0
        critical = int(np.sum(field_coverages[active] < 0.75)) if np.any(active) else 0
        no_replan = float(self.no_replan_metrics.get("coverage", 0.0))
        greedy = float(self.greedy_replan_metrics.get("coverage", 0.0))
        perfect = float(self.perfect_info_metrics.get("coverage", 0.0))
        bottom = self._bottom_quartile_coverage(self.remaining_demand)
        return {
            "policy": policy,
            "difficulty": self.difficulty,
            "template_date": self.scenario.template_date,
            "planning_date": self.scenario.planning_date,
            "metrics": {
                "actual_simulated_coverage_pct": round(100.0 * coverage, 3),
                "bottom_quartile_field_coverage_pct": round(100.0 * bottom, 3),
                "critical_fields_below_75_pct": critical,
                "no_replan_coverage_pct": round(100.0 * no_replan, 3),
                "no_replan_bottom_quartile_pct": round(100.0 * float(self.no_replan_metrics.get("bottom_quartile_coverage", 0.0)), 3),
                "dynamic_greedy_coverage_pct": round(100.0 * greedy, 3),
                "dynamic_greedy_bottom_quartile_pct": round(100.0 * float(self.greedy_replan_metrics.get("bottom_quartile_coverage", 0.0)), 3),
                "perfect_information_greedy_reference_pct": round(100.0 * perfect, 3),
                "perfect_information_upper_bound_pct": round(100.0 * perfect, 3),
                "perfect_information_reference_is_certified_upper_bound": False,
                "gain_vs_no_replan_pct_points": round(100.0 * (coverage - no_replan), 3),
                "gain_vs_dynamic_greedy_pct_points": round(100.0 * (coverage - greedy), 3),
                "field_floor_gain_vs_no_replan_pct_points": round(100.0 * (bottom - float(self.no_replan_metrics.get("bottom_quartile_coverage", 0.0))), 3),
                "reassignments": changes,
                "cross_division_transfers": transfer_workers,
                "cross_division_assignment_segments": transfer_segments,
                "cross_division_assignments": transfer_workers,
                "constraint_violations": len(violations),
                "workers_considered": len(self.employee_ids),
                "decision_segments": len(normalized),
                "replanning_rounds": len(self.stage_orders),
            },
            "morning_segments": self.morning_segments,
            "assignments": normalized,
            "violations": violations,
            "notice": (
                "This is an event-driven two-round intraday simulation. Operational approval still requires "
                "shadow-mode comparison with actual attendance, transfers, hours and harvested kilograms."
            ),
        }
