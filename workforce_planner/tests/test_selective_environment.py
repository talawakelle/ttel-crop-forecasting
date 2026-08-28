from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pytest

pytest.importorskip("gymnasium")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.data import WorkforceData
from allocator.selective_environment import (
    ACCEPT_GREEDY,
    KEEP_CURRENT,
    SelectiveHybridReallocationEnv,
)


@pytest.fixture(scope="module")
def data() -> WorkforceData:
    loaded = WorkforceData.load(ROOT / "data" / "workforce_profile.json")
    loaded.configure_forecaster(
        model_path=ROOT / "models" / "productivity_catboost.cbm",
        weather_model_path=ROOT / "models" / "productivity_weather_catboost.cbm",
        metadata_path=ROOT / "models" / "productivity_metrics.json",
        state_path=ROOT / "data" / "productivity_state.json.gz",
        weather_daily_path=ROOT / "data" / "weather_daily.csv.gz",
        weather_metadata_path=ROOT / "data" / "weather_metadata.json",
    )
    loaded.configure_crop_forecaster(ROOT / "data" / "crop_forecast_clarendon.json")
    return loaded


def rollout(env: SelectiveHybridReallocationEnv, action: int) -> dict:
    observation, _ = env.reset(seed=123)
    assert observation.shape == env.observation_space.shape
    terminated = False
    while not terminated:
        observation, _reward, terminated, _truncated, _info = env.step(action)
    return env.result()


def test_accept_all_matches_budgeted_greedy(data: WorkforceData):
    env = SelectiveHybridReallocationEnv(data, seed=123, difficulty="full")
    result = rollout(env, ACCEPT_GREEDY)
    metrics = result["metrics"]
    assert metrics["actual_simulated_coverage_pct"] == pytest.approx(
        metrics["budgeted_dynamic_greedy_coverage_pct"], abs=0.001
    )
    assert metrics["reassignments"] <= metrics["move_budget"] <= 15
    assert metrics["reassignment_rate"] <= 0.15 + 1e-6
    assert metrics["constraint_violations"] == 0


def test_veto_policy_is_shielded_or_falls_back(data: WorkforceData):
    env = SelectiveHybridReallocationEnv(data, seed=321, difficulty="extreme")
    result = rollout(env, KEEP_CURRENT)
    metrics = result["metrics"]
    assert metrics["constraint_violations"] == 0
    assert metrics["reassignments"] <= metrics["move_budget"]
    assert (
        metrics["fallback_triggered"]
        or metrics["conservative_gap_vs_budgeted_greedy_pct_points"] >= -0.05
    )


def test_reference_outcomes_are_not_in_observation(data: WorkforceData):
    env = SelectiveHybridReallocationEnv(data, seed=777, difficulty="medium")
    first, _ = env.reset(seed=777)
    env.greedy_replan_metrics["coverage"] = -999.0
    env.budgeted_greedy_metrics["coverage"] = 999.0
    env.no_replan_metrics["coverage"] = 555.0
    second = env._observation()
    assert np.array_equal(first, second)
    assert np.isfinite(second).all()


@pytest.mark.parametrize("difficulty", ["easy", "medium", "full", "extreme"])
def test_hard_rules_hold_across_difficulties(data: WorkforceData, difficulty: str):
    env = SelectiveHybridReallocationEnv(data, seed=99, difficulty=difficulty)
    result = rollout(env, ACCEPT_GREEDY)
    assert result["metrics"]["constraint_violations"] == 0
    assert result["metrics"]["reassignments"] <= 15
