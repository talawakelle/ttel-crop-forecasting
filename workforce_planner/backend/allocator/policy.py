from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from sb3_contrib import MaskablePPO

from .data import Scenario, WorkforceData
from .environment import ORDER_MODES, WorkforceAllocationEnv


@lru_cache(maxsize=4)
def load_policy(path: str, modified_ns: int):
    del modified_ns
    return MaskablePPO.load(path)


def rollout_plan(data: WorkforceData, scenario: Scenario, model: MaskablePPO, rollouts: int = 32) -> dict:
    candidates = []
    for rollout in range(max(1, int(rollouts))):
        environment = WorkforceAllocationEnv(data, seed=scenario.seed + rollout * 7919)
        order_mode = ORDER_MODES[rollout % len(ORDER_MODES)]
        observation, _ = environment.reset(options={"scenario": scenario, "order_mode": order_mode})
        terminated = False
        while not terminated:
            action, _ = model.predict(
                observation,
                action_masks=environment.action_masks(),
                deterministic=True,
            )
            observation, _reward, terminated, _truncated, _info = environment.step(action)
        candidates.append(environment.result(
            "forecast-aware-maskable-ppo",
            f"forecast-aware scarcity policy · best of {max(1, int(rollouts))} feasible rollouts",
        ))
    return max(
        candidates,
        key=lambda plan: (
            plan["metrics"]["coverage_pct"],
            -plan["metrics"]["cross_division_assignments"],
            plan["metrics"]["assigned_workers"],
        ),
    )


def rl_allocate(data: WorkforceData, scenario: Scenario, model_path: Path, rollouts: int = 32) -> dict:
    if not model_path.exists():
        raise FileNotFoundError("The RL policy has not been trained yet")
    return rollout_plan(data, scenario, load_policy(str(model_path), model_path.stat().st_mtime_ns), rollouts)
