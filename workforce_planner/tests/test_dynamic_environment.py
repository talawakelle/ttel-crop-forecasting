from pathlib import Path
import sys
import numpy as np
import pytest

pytest.importorskip("gymnasium")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.data import WorkforceData
from allocator.dynamic_environment import DynamicReallocationEnv
from allocator.version import DYNAMIC_MODEL_SCHEMA_VERSION


def configured_data() -> WorkforceData:
    data = WorkforceData.load(ROOT / "data" / "workforce_profile.json")
    data.configure_forecaster(
        model_path=ROOT / "models" / "productivity_catboost.cbm",
        weather_model_path=ROOT / "models" / "productivity_weather_catboost.cbm",
        metadata_path=ROOT / "models" / "productivity_metrics.json",
        state_path=ROOT / "data" / "productivity_state.json.gz",
        weather_daily_path=ROOT / "data" / "weather_daily.csv.gz",
        weather_metadata_path=ROOT / "data" / "weather_metadata.json",
    )
    data.configure_crop_forecaster(ROOT / "data" / "crop_forecast_clarendon.json")
    return data


def test_dynamic_environment_is_two_round_and_valid():
    data = configured_data()
    env = DynamicReallocationEnv(data, scenario_dates=data.complete_dates[-90:], seed=42)
    observation, _ = env.reset(seed=99)
    assert observation.shape == env.observation_space.shape
    assert len(env.stage_orders) == 2
    assert abs(env.config.morning_fraction + sum(env.config.decision_fractions) - 1.0) < 1e-9
    terminated = False
    rewards = []
    while not terminated:
        masks = env.action_masks()
        assert masks.any()
        action = int(next(index for index, valid in enumerate(masks) if valid))
        observation, reward, terminated, _, _ = env.step(action)
        rewards.append(reward)
        assert np.isfinite(observation).all()
        assert np.isfinite(reward)
    result = env.result()
    assert result["metrics"]["constraint_violations"] == 0
    assert result["metrics"]["replanning_rounds"] == 2
    assert result["metrics"]["cross_division_assignment_segments"] >= result["metrics"]["cross_division_transfers"]
    assert result["metrics"]["perfect_information_reference_is_certified_upper_bound"] is False
    assert DYNAMIC_MODEL_SCHEMA_VERSION == 3
    assert rewards


def test_reset_is_reproducible_and_observation_has_no_reference_coverage():
    data = configured_data()
    env = DynamicReallocationEnv(data, scenario_dates=data.complete_dates[-90:], seed=5)
    first, _ = env.reset(seed=12345)
    first_no_replan = env.no_replan_metrics["coverage"]
    second, _ = env.reset(seed=12345)
    second_no_replan = env.no_replan_metrics["coverage"]
    assert np.allclose(first, second)
    assert first_no_replan == second_no_replan
    # Reference metrics are available for evaluation, but are deliberately not
    # appended as global observation features in schema 2.
    assert first.shape[0] == len(env.field_ids) * 10 + 10


def test_extreme_stress_keeps_action_masks_safe():
    data = configured_data()
    env = DynamicReallocationEnv(data, scenario_dates=data.complete_dates[-90:], seed=77, difficulty="extreme")
    observation, _ = env.reset(seed=77)
    terminated = False
    while not terminated:
        masks = env.action_masks()
        feasible = np.flatnonzero(masks)
        action = int(feasible[-1])
        observation, _reward, terminated, _, _ = env.step(action)
    assert env.result()["metrics"]["constraint_violations"] == 0
