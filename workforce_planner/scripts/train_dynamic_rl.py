from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.data import WorkforceData
from allocator.dynamic_training import train_dynamic_policy


def configured_data(profile: Path) -> WorkforceData:
    data = WorkforceData.load(profile)
    forecast = data.configure_forecaster(
        model_path=ROOT / "models" / "productivity_catboost.cbm",
        weather_model_path=ROOT / "models" / "productivity_weather_catboost.cbm",
        metadata_path=ROOT / "models" / "productivity_metrics.json",
        state_path=ROOT / "data" / "productivity_state.json.gz",
        weather_daily_path=ROOT / "data" / "weather_daily.csv.gz",
        weather_metadata_path=ROOT / "data" / "weather_metadata.json",
    )
    data.configure_crop_forecaster(ROOT / "data" / "crop_forecast_clarendon.json")
    if not forecast.get("ready"):
        raise RuntimeError(f"Approved employee-productivity forecast is required: {forecast.get('error')}")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Train tournament-selected event-driven intraday RL")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--candidate-seeds", type=int, default=3)
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cuda")
    parser.add_argument("--env-count", type=int, default=4)
    parser.add_argument("--easy-steps", type=int, default=150_000)
    parser.add_argument("--medium-steps", type=int, default=250_000)
    parser.add_argument("--full-steps", type=int, default=400_000)
    parser.add_argument("--mixed-steps", type=int, default=300_000)
    parser.add_argument("--validation-days", type=int, default=120)
    parser.add_argument("--test-days", type=int, default=180)
    parser.add_argument("--evaluation-episodes", type=int, default=240)
    parser.add_argument("--stress-episodes", type=int, default=120)
    parser.add_argument("--profile", type=Path, default=ROOT / "data" / "workforce_profile.json")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "models" / "dynamic_maskable_ppo_reallocator.zip",
    )
    args = parser.parse_args()
    data = configured_data(args.profile)
    metrics = train_dynamic_policy(
        data,
        args.output,
        seed=args.seed,
        candidate_seeds=args.candidate_seeds,
        device=args.device,
        env_count=args.env_count,
        easy_steps=args.easy_steps,
        medium_steps=args.medium_steps,
        full_steps=args.full_steps,
        mixed_steps=args.mixed_steps,
        validation_days=args.validation_days,
        test_days=args.test_days,
        evaluation_episodes=args.evaluation_episodes,
        stress_episodes=args.stress_episodes,
    )
    print(json.dumps(metrics, indent=2))
    if not metrics.get("approved"):
        raise SystemExit("Dynamic RL candidate was rejected by the untouched-test safety gate")


if __name__ == "__main__":
    main()
