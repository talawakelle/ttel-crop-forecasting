from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.forecast import (  # noqa: E402
    BASE_FEATURE_COLUMNS,
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    FEATURE_SCHEMA_VERSION,
    PREDICTION_MAX_KG,
    PREDICTION_MIN_KG,
    sha256_file,
)
from allocator.weather import weather_prefix_sha256  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def gpu_name() -> str | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    return result.stdout.strip().splitlines()[0] if result.stdout.strip() else None


def clipped(values):
    import numpy as np

    return np.clip(np.asarray(values, dtype=np.float64), PREDICTION_MIN_KG, PREDICTION_MAX_KG)


def metric_block(actual, predicted, baseline) -> dict[str, float | int]:
    import numpy as np

    actual = np.asarray(actual, dtype=np.float64)
    predicted = clipped(predicted)
    baseline = clipped(baseline)
    model_errors = predicted - actual
    baseline_errors = baseline - actual
    model_mae = float(np.mean(np.abs(model_errors)))
    baseline_mae = float(np.mean(np.abs(baseline_errors)))
    model_rmse = float(math.sqrt(np.mean(model_errors ** 2)))
    baseline_rmse = float(math.sqrt(np.mean(baseline_errors ** 2)))
    denominator = max(1.0, float(np.sum(np.abs(actual))))
    return {
        "rows": int(actual.size),
        "model_mae_kg": round(model_mae, 4),
        "baseline_mae_kg": round(baseline_mae, 4),
        "mae_improvement_kg": round(baseline_mae - model_mae, 4),
        "mae_improvement_pct": round(100.0 * (baseline_mae - model_mae) / max(1e-9, baseline_mae), 2),
        "model_rmse_kg": round(model_rmse, 4),
        "baseline_rmse_kg": round(baseline_rmse, 4),
        "model_wmape_pct": round(100.0 * float(np.sum(np.abs(model_errors))) / denominator, 2),
        "baseline_wmape_pct": round(100.0 * float(np.sum(np.abs(baseline_errors))) / denominator, 2),
    }


def model_parameters(args, iterations: int) -> dict[str, Any]:
    parameters: dict[str, Any] = {
        "iterations": max(50, int(iterations)),
        "depth": int(args.depth),
        "learning_rate": float(args.learning_rate),
        "loss_function": "RMSE",
        "eval_metric": "MAE",
        "task_type": str(args.resolved_task_type),
        "random_seed": int(args.seed),
        "random_strength": 1.0,
        "l2_leaf_reg": 5.0,
        "bootstrap_type": "Bayesian",
        "bagging_temperature": 0.7,
        "allow_writing_files": False,
        "thread_count": max(1, (os.cpu_count() or 2) - 1),
    }
    if args.resolved_task_type == "GPU":
        parameters["devices"] = str(args.devices)
        parameters["gpu_ram_part"] = float(args.gpu_ram_part)
    return parameters


def division_metrics(frame, actual_column: str, predicted, baseline) -> dict[str, dict[str, float | int]]:
    import numpy as np

    predicted = np.asarray(predicted)
    baseline = np.asarray(baseline)
    result = {}
    for division in sorted(frame["field_division"].unique()):
        mask = (frame["field_division"] == division).to_numpy()
        result[str(division)] = metric_block(
            frame.loc[mask, actual_column],
            predicted[mask],
            baseline[mask],
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Train and safety-gate base and optional weather CatBoost productivity forecasts"
    )
    parser.add_argument("--dataset", type=Path, default=ROOT / "data" / "productivity_training.csv.gz")
    parser.add_argument("--dataset-metadata", type=Path, default=ROOT / "data" / "productivity_dataset_metadata.json")
    parser.add_argument("--state", type=Path, default=ROOT / "data" / "productivity_state.json.gz")
    parser.add_argument("--weather-daily", type=Path, default=ROOT / "data" / "weather_daily.csv.gz")
    parser.add_argument("--weather-metadata", type=Path, default=ROOT / "data" / "weather_metadata.json")
    parser.add_argument("--profile", type=Path, default=ROOT / "data" / "workforce_profile.json")
    parser.add_argument("--base-model", type=Path, default=ROOT / "models" / "productivity_catboost.cbm")
    parser.add_argument("--weather-model", type=Path, default=ROOT / "models" / "productivity_weather_catboost.cbm")
    parser.add_argument("--metrics", type=Path, default=ROOT / "models" / "productivity_metrics.json")
    parser.add_argument("--rejected-metrics", type=Path, default=ROOT / "models" / "productivity_rejected_metrics.json")
    parser.add_argument("--iterations", type=int, default=3000)
    parser.add_argument("--depth", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--early-stopping-rounds", type=int, default=200)
    parser.add_argument("--min-mae-improvement-pct", type=float, default=1.0)
    parser.add_argument("--min-weather-over-base-pct", type=float, default=0.25)
    parser.add_argument("--task-type", choices=("auto", "cpu", "gpu"), default="auto")
    parser.add_argument("--devices", default="0")
    parser.add_argument("--gpu-ram-part", type=float, default=0.90)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--verbose-every", type=int, default=100)
    args = parser.parse_args()
    if not 200 <= args.iterations <= 20_000:
        raise ValueError("iterations must be between 200 and 20000")
    if not 4 <= args.depth <= 10:
        raise ValueError("depth must be between 4 and 10")
    if not 0.50 <= args.gpu_ram_part <= 0.95:
        raise ValueError("gpu-ram-part must be between 0.50 and 0.95")

    try:
        import catboost
        from catboost import CatBoostRegressor, Pool
        from catboost.utils import get_gpu_device_count
        import numpy as np
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("CatBoost, pandas and NumPy must be installed before GPU training") from exc

    device_count = int(get_gpu_device_count())
    if args.task_type == "gpu" and device_count < 1:
        raise RuntimeError("GPU training was requested, but CatBoost cannot see an NVIDIA GPU.")
    args.resolved_task_type = "GPU" if (args.task_type == "gpu" or (args.task_type == "auto" and device_count > 0)) else "CPU"

    required = [
        args.dataset,
        args.dataset_metadata,
        args.state,
        args.profile,
        args.weather_daily,
        args.weather_metadata,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Required training file(s) missing: {', '.join(missing)}")
    dataset_metadata = read_json(args.dataset_metadata)
    weather_metadata = read_json(args.weather_metadata)
    profile = read_json(args.profile)
    profile_sha = profile["metadata"].get("source_sha256")
    if not profile_sha or dataset_metadata.get("source_sha256") != profile_sha:
        raise RuntimeError("Prepared forecast data does not match the active workforce profile")
    integrity = {
        "dataset": dataset_metadata.get("dataset_sha256") == sha256_file(args.dataset),
        "state": dataset_metadata.get("state_sha256") == sha256_file(args.state),
        "weather_training_prefix": dataset_metadata.get("weather_training_sha256") == weather_prefix_sha256(
            args.weather_daily,
            dataset_metadata.get("weather_training_cutoff") or dataset_metadata.get("date_max"),
        ),
        "weather_internal": weather_metadata.get("daily_sha256") == sha256_file(args.weather_daily),
        "features": dataset_metadata.get("feature_columns") == list(FEATURE_COLUMNS),
    }
    if not all(integrity.values()):
        raise RuntimeError(f"Prepared forecast integrity check failed: {integrity}")

    print(f"Loading {args.dataset.name}...", flush=True)
    frame = pd.read_csv(args.dataset, compression="gzip", low_memory=False)
    required_columns = {"date", "split", "target_kg", "baseline_prediction_kg", *FEATURE_COLUMNS}
    missing_columns = required_columns.difference(frame.columns)
    if missing_columns:
        raise RuntimeError(f"Prepared dataset is missing columns: {', '.join(sorted(missing_columns))}")
    for name in CATEGORICAL_FEATURES:
        frame[name] = frame[name].fillna("UNK").astype(str)
    for name in set(FEATURE_COLUMNS).difference(CATEGORICAL_FEATURES):
        frame[name] = pd.to_numeric(frame[name], errors="raise").astype("float32")
    for name in ("target_kg", "baseline_prediction_kg"):
        frame[name] = pd.to_numeric(frame[name], errors="raise").astype("float32")

    train = frame[frame["split"] == "train"]
    validation = frame[frame["split"] == "validation"]
    test = frame[frame["split"] == "test"]
    if min(len(train), len(validation), len(test)) < 100:
        raise RuntimeError("Temporal train, validation and test partitions must each contain at least 100 rows")

    def pool(part, columns):
        categorical_indices = [columns.index(name) for name in CATEGORICAL_FEATURES]
        return Pool(
            part.loc[:, list(columns)],
            label=part["target_kg"],
            cat_features=categorical_indices,
            feature_names=list(columns),
        )

    print(
        f"{args.resolved_task_type} training ready ({device_count} CUDA device(s) detected). "
        f"Train {len(train):,}; validation {len(validation):,}; untouched test {len(test):,}. "
        "Training matched no-weather and weather candidates.",
        flush=True,
    )
    started = time.perf_counter()

    print("\n=== Candidate A: no-weather CatBoost ===", flush=True)
    base_candidate = CatBoostRegressor(**model_parameters(args, args.iterations))
    base_candidate.fit(
        pool(train, BASE_FEATURE_COLUMNS),
        eval_set=pool(validation, BASE_FEATURE_COLUMNS),
        use_best_model=True,
        early_stopping_rounds=args.early_stopping_rounds,
        verbose=args.verbose_every,
    )
    base_best = max(0, int(base_candidate.get_best_iteration()))
    base_validation_predictions = base_candidate.predict(pool(validation, BASE_FEATURE_COLUMNS), task_type="CPU")
    base_test_predictions = base_candidate.predict(pool(test, BASE_FEATURE_COLUMNS), task_type="CPU")
    base_validation = metric_block(
        validation["target_kg"], base_validation_predictions, validation["baseline_prediction_kg"]
    )
    base_test = metric_block(test["target_kg"], base_test_predictions, test["baseline_prediction_kg"])
    base_divisions = division_metrics(
        test,
        "target_kg",
        base_test_predictions,
        test["baseline_prediction_kg"].to_numpy(),
    )
    base_gate = {
        "minimum_test_mae_improvement": float(base_test["mae_improvement_pct"]) >= args.min_mae_improvement_pct,
        "test_rmse_not_materially_worse": float(base_test["model_rmse_kg"]) <= float(base_test["baseline_rmse_kg"]) * 1.02,
        "no_division_mae_materially_worse": all(
            float(item["model_mae_kg"]) <= float(item["baseline_mae_kg"]) * 1.05
            for item in base_divisions.values()
            if int(item["rows"]) >= 100
        ),
        "all_predictions_finite": bool(np.isfinite(np.asarray(base_test_predictions, dtype=float)).all()),
    }
    base_approved = all(base_gate.values())

    print("\n=== Candidate B: past-weather CatBoost ===", flush=True)
    weather_candidate = CatBoostRegressor(**model_parameters(args, args.iterations))
    weather_candidate.fit(
        pool(train, FEATURE_COLUMNS),
        eval_set=pool(validation, FEATURE_COLUMNS),
        use_best_model=True,
        early_stopping_rounds=args.early_stopping_rounds,
        verbose=args.verbose_every,
    )
    weather_best = max(0, int(weather_candidate.get_best_iteration()))
    weather_validation_predictions = weather_candidate.predict(pool(validation, FEATURE_COLUMNS), task_type="CPU")
    weather_test_predictions = weather_candidate.predict(pool(test, FEATURE_COLUMNS), task_type="CPU")
    weather_validation = metric_block(
        validation["target_kg"], weather_validation_predictions, validation["baseline_prediction_kg"]
    )
    weather_test = metric_block(test["target_kg"], weather_test_predictions, test["baseline_prediction_kg"])
    weather_vs_base = metric_block(test["target_kg"], weather_test_predictions, base_test_predictions)
    weather_divisions = division_metrics(
        test,
        "target_kg",
        weather_test_predictions,
        test["baseline_prediction_kg"].to_numpy(),
    )
    weather_vs_base_divisions = division_metrics(
        test,
        "target_kg",
        weather_test_predictions,
        base_test_predictions,
    )
    weather_gate = {
        "beats_historical_baseline": float(weather_test["mae_improvement_pct"]) >= args.min_mae_improvement_pct,
        "beats_matched_no_weather_model": float(weather_vs_base["mae_improvement_pct"]) >= args.min_weather_over_base_pct,
        "rmse_not_worse_than_no_weather": float(weather_vs_base["model_rmse_kg"]) <= float(weather_vs_base["baseline_rmse_kg"]) * 1.01,
        "no_division_materially_worse_than_no_weather": all(
            float(item["model_mae_kg"]) <= float(item["baseline_mae_kg"]) * 1.02
            for item in weather_vs_base_divisions.values()
            if int(item["rows"]) >= 100
        ),
        "all_predictions_finite": bool(np.isfinite(np.asarray(weather_test_predictions, dtype=float)).all()),
    }
    weather_approved = all(weather_gate.values())
    approved = base_approved or weather_approved

    report: dict[str, Any] = {
        "forecast_schema_version": 2,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "approved": approved,
        "base_approved": base_approved,
        "weather_approved": weather_approved,
        "base_safety_gate": base_gate,
        "weather_safety_gate": weather_gate,
        "required_test_mae_improvement_pct": args.min_mae_improvement_pct,
        "required_weather_over_base_pct": args.min_weather_over_base_pct,
        "profile_source_sha256": profile_sha,
        "profile_source_name": profile["metadata"].get("source_name"),
        "profile_date_min": profile["metadata"].get("date_min"),
        "profile_date_max": profile["metadata"].get("date_max"),
        "dataset_sha256": dataset_metadata["dataset_sha256"],
        "state_sha256": dataset_metadata["state_sha256"],
        "weather_daily_sha256": dataset_metadata["weather_daily_sha256"],
        "weather_metadata_sha256": dataset_metadata["weather_metadata_sha256"],
        "weather_source_name": dataset_metadata.get("weather_source_name"),
        "weather_source_sha256": dataset_metadata.get("weather_source_sha256"),
        "weather_date_min": dataset_metadata.get("weather_date_min"),
        "weather_date_max": dataset_metadata.get("weather_date_max"),
        "weather_training_cutoff": dataset_metadata.get("weather_training_cutoff"),
        "weather_training_sha256": dataset_metadata.get("weather_training_sha256"),
        "weather_join": dataset_metadata.get("weather_join"),
        "state_as_of": dataset_metadata["date_max"],
        "base_feature_columns": list(BASE_FEATURE_COLUMNS),
        "feature_columns": list(FEATURE_COLUMNS),
        "categorical_features": list(CATEGORICAL_FEATURES),
        "target_cap_kg": dataset_metadata["target_cap_kg"],
        "temporal_split": {
            "train_end": dataset_metadata["train_end"],
            "validation_start": dataset_metadata["validation_start"],
            "validation_end": dataset_metadata["validation_end"],
            "test_start": dataset_metadata["test_start"],
            "test_end": dataset_metadata["date_max"],
            "rows": dataset_metadata["split_rows"],
        },
        "base_validation_metrics": base_validation,
        "base_test_metrics": base_test,
        "base_test_metrics_by_division": base_divisions,
        "weather_validation_metrics": weather_validation,
        "weather_test_metrics": weather_test,
        "weather_test_metrics_by_division": weather_divisions,
        "weather_vs_base_test_metrics": weather_vs_base,
        "weather_vs_base_test_metrics_by_division": weather_vs_base_divisions,
        "test_metrics": weather_test if weather_approved else base_test,
        "base_candidate_best_iteration": base_best,
        "weather_candidate_best_iteration": weather_best,
        "requested_iterations": args.iterations,
        "base_production_iterations": base_best + 1,
        "weather_production_iterations": weather_best + 1,
        "depth": args.depth,
        "learning_rate": args.learning_rate,
        "seed": args.seed,
        "training_device": args.resolved_task_type,
        "gpu_devices": args.devices if args.resolved_task_type == "GPU" else None,
        "gpu_device_count": device_count,
        "gpu_name": gpu_name() if args.resolved_task_type == "GPU" else None,
        "gpu_ram_part": args.gpu_ram_part if args.resolved_task_type == "GPU" else None,
        "catboost_version": catboost.__version__,
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "reproducibility_note": (
            "GPU training can vary slightly because of parallel floating-point reductions; "
            "CPU training is more deterministic for the same package versions and seed."
        ),
        "leakage_control": dataset_metadata["leakage_control"],
        "weather_operational_gate": (
            "The weather model is used only when the newest prior observation is at most two days old, "
            "at least four of the previous seven days are usable, and the target date has at least eight "
            "station observations timestamped before 06:00 local time."
        ),
        "privacy": dataset_metadata["privacy"],
    }

    if not approved:
        report["training_seconds"] = round(time.perf_counter() - started, 2)
        write_json_atomic(args.rejected_metrics, report)
        print(json.dumps({
            "approved": False,
            "base_safety_gate": base_gate,
            "weather_safety_gate": weather_gate,
            "base_test_metrics": base_test,
            "weather_test_metrics": weather_test,
            "weather_vs_base_test_metrics": weather_vs_base,
        }, indent=2))
        print("BOTH FORECASTS REJECTED: the historical median and optimizer remain active.")
        return 0

    candidates: list[tuple[Path, Path]] = []
    if base_approved:
        print(
            f"Base gate passed. Retraining on all {len(frame):,} rows for {base_best + 1:,} trees...",
            flush=True,
        )
        production = CatBoostRegressor(**model_parameters(args, base_best + 1))
        production.fit(pool(frame, BASE_FEATURE_COLUMNS), verbose=args.verbose_every)
        candidate_path = args.base_model.with_suffix(args.base_model.suffix + ".candidate")
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        production.save_model(str(candidate_path))
        candidates.append((candidate_path, args.base_model))

    if weather_approved:
        print(
            f"Weather gate passed. Retraining on all {len(frame):,} rows for {weather_best + 1:,} trees...",
            flush=True,
        )
        production = CatBoostRegressor(**model_parameters(args, weather_best + 1))
        production.fit(pool(frame, FEATURE_COLUMNS), verbose=args.verbose_every)
        candidate_path = args.weather_model.with_suffix(args.weather_model.suffix + ".candidate")
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        production.save_model(str(candidate_path))
        candidates.append((candidate_path, args.weather_model))

    if args.metrics.exists() or any(destination.exists() for _, destination in candidates):
        backup = args.metrics.parent / "forecast-backup" / datetime.now().strftime("%Y%m%d-%H%M%S")
        backup.mkdir(parents=True, exist_ok=True)
        for path in (args.base_model, args.weather_model, args.metrics):
            if path.exists():
                shutil.copy2(path, backup / path.name)
    for candidate_path, destination in candidates:
        os.replace(candidate_path, destination)

    if base_approved:
        report["base_model_file"] = args.base_model.name
        report["base_model_sha256"] = sha256_file(args.base_model)
        report["model_sha256"] = report["base_model_sha256"]
    if weather_approved:
        report["weather_model_file"] = args.weather_model.name
        report["weather_model_sha256"] = sha256_file(args.weather_model)
    report["training_seconds"] = round(time.perf_counter() - started, 2)
    write_json_atomic(args.metrics, report)
    print(json.dumps({
        "approved": True,
        "base_approved": base_approved,
        "weather_approved": weather_approved,
        "base_test_metrics": base_test,
        "weather_test_metrics": weather_test,
        "weather_vs_base_test_metrics": weather_vs_base,
        "base_best_iteration": base_best,
        "weather_best_iteration": weather_best,
        "training_seconds": report["training_seconds"],
        "gpu_name": report["gpu_name"],
    }, indent=2))
    if weather_approved:
        print("WEATHER FORECAST APPROVED; BASE MODEL IS THE AUTOMATIC STALE-WEATHER FALLBACK")
    else:
        print("WEATHER DID NOT ADD VERIFIED ACCURACY; APPROVED BASE FORECAST IS ACTIVE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
