from __future__ import annotations

from pathlib import Path
import argparse
import json
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.data import WorkforceData
from allocator.selective_environment import (
    ACCEPT_GREEDY,
    KEEP_CURRENT,
    SelectiveHybridReallocationEnv,
)


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


def rollout(data: WorkforceData, *, episodes: int, difficulty: str, action: int, seed: int) -> dict:
    rows: list[dict] = []
    dates = data.complete_dates[-180:]
    for episode in range(episodes):
        env = SelectiveHybridReallocationEnv(
            data,
            scenario_dates=dates,
            seed=seed + episode * 7919,
            difficulty=difficulty,
        )
        env.reset(seed=seed + episode * 104729)
        terminated = False
        while not terminated:
            _obs, _reward, terminated, _truncated, _info = env.step(action)
        rows.append(env.result()["metrics"])
    keys = [
        "actual_simulated_coverage_pct",
        "no_replan_coverage_pct",
        "budgeted_dynamic_greedy_coverage_pct",
        "dynamic_greedy_coverage_pct",
        "gain_vs_no_replan_pct_points",
        "gain_vs_budgeted_dynamic_greedy_pct_points",
        "gain_vs_dynamic_greedy_pct_points",
        "reassignments",
        "budgeted_dynamic_greedy_reassignments",
        "dynamic_greedy_reassignments",
        "movement_saving_vs_budgeted_greedy",
        "selective_decisions",
        "rl_vetoes",
    ]
    result = {key: round(statistics.mean(float(row[key]) for row in rows), 3) for key in keys}
    result.update({
        "episodes": episodes,
        "difficulty": difficulty,
        "fallback_rate_pct": round(
            100.0 * statistics.mean(float(bool(row["fallback_triggered"])) for row in rows), 3
        ),
        "constraint_violations": sum(int(row["constraint_violations"]) for row in rows),
    })
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark the v1.5 conservative hybrid safety architecture")
    parser.add_argument("--full-episodes", type=int, default=80)
    parser.add_argument("--extreme-episodes", type=int, default=40)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "models" / "selective_hybrid_safety_benchmark.json",
    )
    args = parser.parse_args()
    data = configured_data()
    report = {
        "note": (
            "Accept-all reproduces budgeted dynamic greedy. Veto-all is a stress check for the shield and fallback, "
            "not a trained policy result."
        ),
        "full_accept_all": rollout(
            data, episodes=args.full_episodes, difficulty="full", action=ACCEPT_GREEDY, seed=1_001
        ),
        "full_veto_all": rollout(
            data, episodes=args.full_episodes, difficulty="full", action=KEEP_CURRENT, seed=2_003
        ),
        "extreme_accept_all": rollout(
            data, episodes=args.extreme_episodes, difficulty="extreme", action=ACCEPT_GREEDY, seed=3_007
        ),
        "extreme_veto_all": rollout(
            data, episodes=args.extreme_episodes, difficulty="extreme", action=KEEP_CURRENT, seed=4_009
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
