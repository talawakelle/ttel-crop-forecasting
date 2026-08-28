from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.forecast import sha256_file
from allocator.version import MODEL_SCHEMA_VERSION


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify forecast-aware RL model compatibility")
    parser.add_argument("--profile", type=Path, default=ROOT / "data" / "workforce_profile.json")
    parser.add_argument("--model", type=Path, default=ROOT / "models" / "maskable_ppo_allocator.zip")
    parser.add_argument("--forecast", type=Path, default=ROOT / "models" / "productivity_catboost.cbm")
    args = parser.parse_args()
    metrics_path = args.model.with_name("training_metrics.json")
    if not args.model.exists() or not metrics_path.exists():
        print("MODEL ERROR: model or approved training metrics file is missing.", file=sys.stderr)
        return 1
    if not args.forecast.exists():
        print("MODEL ERROR: the CatBoost model used by RL is missing.", file=sys.stderr)
        return 1
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    expected_source = profile["metadata"].get("source_sha256")
    active_forecast_hash = sha256_file(args.forecast)
    summary = {
        "model_file": str(args.model),
        "approved": metrics.get("approved"),
        "model_schema_version": metrics.get("model_schema_version"),
        "required_model_schema_version": MODEL_SCHEMA_VERSION,
        "profile_fingerprint_matches": metrics.get("profile_source_sha256") == expected_source,
        "forecast_fingerprint_matches": metrics.get("forecast_base_model_sha256") == active_forecast_hash,
        "forecast_ready_during_training": metrics.get("forecast_ready_during_training"),
        "rl_mean_coverage_pct": metrics.get("rl_mean_coverage_pct"),
        "greedy_mean_coverage_pct": metrics.get("greedy_mean_coverage_pct"),
        "difference_pct_points": metrics.get("rl_minus_greedy_pct_points"),
        "win_rate_pct": metrics.get("rl_win_rate_pct"),
        "p10_difference_pct_points": metrics.get("difference_p10_pct_points"),
        "constraint_violations": metrics.get("rl_constraint_violations"),
        "approval_gate": metrics.get("approval_gate"),
    }
    print(json.dumps(summary, indent=2))
    compatible = (
        summary["approved"] is True
        and summary["model_schema_version"] == MODEL_SCHEMA_VERSION
        and summary["profile_fingerprint_matches"]
        and summary["forecast_fingerprint_matches"]
        and summary["forecast_ready_during_training"] is True
        and summary["constraint_violations"] == 0
    )
    if not compatible:
        print("MODEL ERROR: the selected model is not approved or its profile/forecast fingerprint changed.", file=sys.stderr)
        return 1
    print("MODEL READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
