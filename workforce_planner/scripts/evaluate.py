from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sb3_contrib import MaskablePPO
from allocator.data import WorkforceData
from allocator.training import evaluate_policy


def configured_data(profile: Path) -> WorkforceData:
    data = WorkforceData.load(profile)
    status = data.configure_forecaster(
        model_path=ROOT / "models" / "productivity_catboost.cbm",
        weather_model_path=ROOT / "models" / "productivity_weather_catboost.cbm",
        metadata_path=ROOT / "models" / "productivity_metrics.json",
        state_path=ROOT / "data" / "productivity_state.json.gz",
        weather_daily_path=ROOT / "data" / "weather_daily.csv.gz",
        weather_metadata_path=ROOT / "data" / "weather_metadata.json",
    )
    if not status.get("ready"):
        raise RuntimeError(f"Approved CatBoost forecast is required: {status.get('error')}")
    return data


def main():
    parser = argparse.ArgumentParser(description="Evaluate forecast-aware RL against the greedy baseline")
    parser.add_argument("--episodes", type=int, default=100)
    parser.add_argument("--seed", type=int, default=1042)
    parser.add_argument("--rollouts", type=int, default=32)
    parser.add_argument("--profile", type=Path, default=ROOT / "data" / "workforce_profile.json")
    parser.add_argument("--model", type=Path, default=ROOT / "models" / "maskable_ppo_allocator.zip")
    args = parser.parse_args()
    data = configured_data(args.profile)
    model = MaskablePPO.load(str(args.model))
    metrics = evaluate_policy(data, model, args.episodes, args.seed, args.rollouts)
    print(json.dumps(metrics, indent=2))
    if not metrics.get("approved"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
