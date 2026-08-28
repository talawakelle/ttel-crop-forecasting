from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys

from sb3_contrib import MaskablePPO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.data import WorkforceData
from allocator.dynamic_training import temporal_three_way_split
from allocator.selective_training import (
    evaluate_selective_hybrid_policy,
    selective_hybrid_approval_gate,
)


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
    parser = argparse.ArgumentParser(
        description="Re-evaluate an approved selective hybrid RL model"
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=ROOT / "models" / "selective_hybrid_maskable_ppo.zip",
    )
    parser.add_argument(
        "--profile", type=Path, default=ROOT / "data" / "workforce_profile.json"
    )
    parser.add_argument("--episodes", type=int, default=240)
    parser.add_argument("--stress-episodes", type=int, default=120)
    parser.add_argument("--validation-days", type=int, default=120)
    parser.add_argument("--test-days", type=int, default=180)
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="auto")
    args = parser.parse_args()
    if not args.model.exists():
        raise FileNotFoundError(f"Selective hybrid model not found: {args.model}")
    data = configured_data(args.profile)
    _training, _validation, test_dates = temporal_three_way_split(
        data,
        validation_days=args.validation_days,
        test_days=args.test_days,
    )
    metrics_path = args.model.with_name("selective_hybrid_training_metrics.json")
    threshold = 0.90
    if metrics_path.exists():
        try:
            threshold = float(
                json.loads(metrics_path.read_text(encoding="utf-8")).get(
                    "selected_veto_confidence_threshold", 0.90
                )
            )
        except (OSError, ValueError, json.JSONDecodeError):
            threshold = 0.90
    model = MaskablePPO.load(str(args.model), device=args.device)
    full = evaluate_selective_hybrid_policy(
        data,
        model,
        dates=test_dates,
        episodes=args.episodes,
        seed=9_000_043,
        difficulty="full",
        evaluation_label="test",
        veto_confidence_threshold=threshold,
    )
    extreme = evaluate_selective_hybrid_policy(
        data,
        model,
        dates=test_dates,
        episodes=args.stress_episodes,
        seed=19_000_081,
        difficulty="extreme",
        evaluation_label="test",
        veto_confidence_threshold=threshold,
    )
    combined = dict(full)
    combined["extreme_stress"] = extreme
    combined["selected_veto_confidence_threshold"] = threshold
    combined["approval_gate"] = selective_hybrid_approval_gate(combined)
    combined["approved"] = all(combined["approval_gate"].values())
    print(json.dumps(combined, indent=2))
    if not combined["approved"]:
        raise SystemExit("Selective hybrid RL failed re-evaluation")


if __name__ == "__main__":
    main()
