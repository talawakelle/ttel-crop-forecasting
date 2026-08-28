from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys

from sb3_contrib import MaskablePPO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.data import WorkforceData
from allocator.dynamic_training import evaluate_dynamic_policy, temporal_three_way_split


def configured_data(profile: Path) -> WorkforceData:
    data = WorkforceData.load(profile)
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-evaluate an approved dynamic RL model")
    parser.add_argument("--model", type=Path, default=ROOT / "models" / "dynamic_maskable_ppo_reallocator.zip")
    parser.add_argument("--profile", type=Path, default=ROOT / "data" / "workforce_profile.json")
    parser.add_argument("--episodes", type=int, default=240)
    parser.add_argument("--stress-episodes", type=int, default=120)
    parser.add_argument("--validation-days", type=int, default=120)
    parser.add_argument("--test-days", type=int, default=180)
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="auto")
    args = parser.parse_args()
    if not args.model.exists():
        raise FileNotFoundError(f"Dynamic model not found: {args.model}")
    data = configured_data(args.profile)
    _training, _validation, test_dates = temporal_three_way_split(
        data,
        validation_days=args.validation_days,
        test_days=args.test_days,
    )
    model = MaskablePPO.load(str(args.model), device=args.device)
    full = evaluate_dynamic_policy(
        data,
        model,
        dates=test_dates,
        episodes=args.episodes,
        seed=9_000_043,
        difficulty="full",
        evaluation_label="test",
    )
    extreme = evaluate_dynamic_policy(
        data,
        model,
        dates=test_dates,
        episodes=args.stress_episodes,
        seed=19_000_081,
        difficulty="extreme",
        evaluation_label="test",
    )
    print(json.dumps({"full": full, "extreme": extreme}, indent=2))


if __name__ == "__main__":
    main()
