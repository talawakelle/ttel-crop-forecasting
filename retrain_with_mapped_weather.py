from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

import joblib
import pandas as pd

from src.modeling import train_direct_forecasts
from src.pipeline import load_weather_daily_many
from train import _json_default, build_dashboard


def _atomic_csv(frame: pd.DataFrame, path: Path, **kwargs) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, **kwargs)
    temporary.replace(path)
    if temporary.exists():
        temporary.unlink()


def _weekly_with_weather(crop_weekly: pd.DataFrame, weather_daily: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    crop_weekly = crop_weekly.copy()
    crop_weekly.index = pd.to_datetime(crop_weekly.index)
    crop_weekly = crop_weekly[["crop_net_kg", "crop_records", "crop_days"]]

    start = max(crop_weekly.index.min() - pd.Timedelta(days=6), weather_daily.index.min())
    boundary = min(crop_weekly.index.max(), weather_daily.index.max())
    last_complete_sunday = boundary - pd.Timedelta(days=(boundary.weekday() + 1) % 7)
    calendar = pd.date_range(start, boundary, freq="D")
    daily = weather_daily.reindex(calendar)
    weather_columns = [column for column in weather_daily.columns if column != "weather_records"]
    daily[weather_columns] = daily[weather_columns].interpolate(limit=2, limit_direction="both")
    daily["has_weather"] = daily["weather_records"].notna().astype(int)

    weekly_weather = pd.DataFrame(index=daily.resample("W-SUN").size().index)
    weekly_weather["weather_days"] = daily["has_weather"].resample("W-SUN").sum()
    weekly_weather["rainfall_mm"] = daily["rainfall_mm"].resample("W-SUN").sum(min_count=1)
    for column in [column for column in weather_columns if column != "rainfall_mm"]:
        weekly_weather[column] = daily[column].resample("W-SUN").mean()

    weekly = crop_weekly.join(weekly_weather, how="inner")
    weekly = weekly.loc[weekly.index <= last_complete_sunday]
    quality = {
        "mode": "mapped_weather_from_weekly_crop_checkpoint",
        "join_start": start.date().isoformat(),
        "join_end": boundary.date().isoformat(),
        "weekly_rows": int(len(weekly)),
        "weeks_with_7_weather_days": int((weekly["weather_days"] == 7).sum()),
        "weeks_with_less_than_5_weather_days": int((weekly["weather_days"] < 5).sum()),
        "last_complete_week_ending": weekly.index.max().date().isoformat(),
    }
    return weekly, quality


def _write_result(
    estate: str,
    directory: Path,
    weekly: pd.DataFrame,
    quality: dict,
    previous_directory: Path | None = None,
) -> dict:
    model_dir = directory / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    old_forecast_path = (previous_directory or directory) / "forecast.csv"
    old_average_wape = None
    if old_forecast_path.exists():
        previous = pd.read_csv(old_forecast_path)
        if not previous.empty:
            old_average_wape = float(previous["validation_wape_pct"].mean())

    result = train_direct_forecasts(weekly, model_dir=model_dir, use_weather=True)
    forecast = result.forecast.copy()
    forecast.insert(0, "estate", estate)
    metrics = pd.DataFrame(result.model_rows)

    importance_rows = []
    for model_path in sorted(model_dir.glob("horizon_*.joblib")):
        bundle = joblib.load(model_path)
        model = bundle["model"]
        if hasattr(model, "feature_importances_"):
            for feature, importance in zip(bundle["features"], model.feature_importances_):
                importance_rows.append(
                    {
                        "horizon_weeks": bundle["horizon_weeks"],
                        "selected_method": bundle["selected_method"],
                        "feature": feature,
                        "importance": float(importance),
                    }
                )
    importance = pd.DataFrame(importance_rows)

    _atomic_csv(weekly, directory / "weekly_history.csv", index_label="week_ending")
    _atomic_csv(forecast, directory / "forecast.csv", index=False)
    _atomic_csv(result.backtest, directory / "backtest_predictions.csv", index=False)
    _atomic_csv(metrics, directory / "model_metrics.csv", index=False)
    _atomic_csv(importance, directory / "feature_importance.csv", index=False)
    quality_path = directory / "data_quality.json"
    temporary_quality_path = quality_path.with_suffix(".json.tmp")
    temporary_quality_path.write_text(
        json.dumps(quality, indent=2, default=_json_default), encoding="utf-8"
    )
    temporary_quality_path.replace(quality_path)
    if temporary_quality_path.exists():
        temporary_quality_path.unlink()
    build_dashboard(
        estate,
        weekly,
        forecast,
        metrics,
        quality,
        directory / "forecast_dashboard.html",
    )

    selected = forecast["selected_method"].tolist()
    return {
        "estate": estate,
        "old_average_wape_pct": old_average_wape,
        "new_average_wape_pct": float(forecast["validation_wape_pct"].mean()),
        "selected_methods": selected,
        "weather_selected_horizons": int(sum(method.startswith("Weather + Crop") for method in selected)),
    }


def _promote_candidate(candidate_directory: Path, destination_directory: Path) -> None:
    candidate_models = {path.name for path in (candidate_directory / "models").glob("horizon_*.joblib")}
    destination_model_dir = destination_directory / "models"
    destination_model_dir.mkdir(parents=True, exist_ok=True)
    for old_model in destination_model_dir.glob("horizon_*.joblib"):
        if old_model.name not in candidate_models:
            old_model.unlink()
    for source in sorted(candidate_directory.rglob("*")):
        if not source.is_file():
            continue
        target = destination_directory / source.relative_to(candidate_directory)
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)
        if source.exists():
            source.unlink()
    shutil.rmtree(candidate_directory, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply a confirmed nearest weather station to existing privacy-safe weekly crop checkpoints."
    )
    parser.add_argument(
        "--weather",
        type=Path,
        action="append",
        required=True,
        help="Mapped weather workbook; repeat for later update workbooks from the same station",
    )
    parser.add_argument("--mapping", type=Path, default=Path("config/weather_station_mapping.csv"))
    parser.add_argument("--station-code", required=True)
    parser.add_argument("--outputs-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--estate", action="append", help="Optional estate name; repeat for multiple estates")
    parser.add_argument("--force", action="store_true", help="Re-run estates that already contain weather features")
    args = parser.parse_args()

    mapping = pd.read_csv(args.mapping)
    mapping = mapping[
        (mapping["nearest_station"] == args.station_code)
        & (mapping["station_file_status"] == "valid")
    ]
    if args.estate:
        requested = {name.casefold() for name in args.estate}
        mapping = mapping[mapping["estate"].str.casefold().isin(requested)]
    mapping_by_estate = {row.estate.casefold(): row for row in mapping.itertuples(index=False)}

    weather_daily, weather_quality = load_weather_daily_many(args.weather)
    directories = [path for path in args.outputs_dir.glob("*_provisional") if path.is_dir()]
    if (args.outputs_dir / "data_quality.json").exists():
        directories.append(args.outputs_dir)

    summaries = []
    skipped = []
    for directory in sorted(directories, key=lambda path: path.name.casefold()):
        quality_path = directory / "data_quality.json"
        history_path = directory / "weekly_history.csv"
        if not quality_path.exists() or not history_path.exists():
            continue
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        estate = str(quality["crop"]["estate"])
        mapping_row = mapping_by_estate.get(estate.casefold())
        if mapping_row is None:
            continue
        history = pd.read_csv(history_path, parse_dates=["week_ending"]).set_index("week_ending")
        already_weather = "rainfall_mm" in history.columns
        if already_weather and not args.force:
            skipped.append({"estate": estate, "reason": "weather already present"})
            continue
        weekly, join_quality = _weekly_with_weather(history, weather_daily)
        if len(weekly) < 65:
            skipped.append({"estate": estate, "reason": f"only {len(weekly)} weekly rows"})
            continue
        quality["weather"] = weather_quality
        quality["joined"] = join_quality
        quality["weather_mapping"] = {
            "station_code": mapping_row.nearest_station,
            "estate_distance_km": float(mapping_row.nearest_distance_km),
            "coordinate_basis": mapping_row.coordinate_basis,
            "source_url": mapping_row.source_url,
            "selection_rule": "nearest physical station; retain weather features only if chronological validation wins",
        }
        try:
            # Keep the candidate on the same filesystem as the retained output so
            # Path.replace() remains an atomic promotion instead of a cross-device move.
            with tempfile.TemporaryDirectory(
                prefix=f".weather_candidate_{estate}_",
                dir=args.outputs_dir,
            ) as temporary:
                candidate_directory = Path(temporary) / "outputs"
                candidate_directory.mkdir(parents=True, exist_ok=True)
                summary = _write_result(
                    estate,
                    candidate_directory,
                    weekly,
                    quality,
                    previous_directory=directory,
                )
                old_wape = summary["old_average_wape_pct"]
                new_wape = summary["new_average_wape_pct"]
                accepted = old_wape is None or new_wape <= old_wape + 1e-9
                summary["accepted"] = accepted
                if accepted:
                    _promote_candidate(candidate_directory, directory)
                else:
                    summary["rejection_reason"] = (
                        f"candidate average WAPE {new_wape:.3f}% exceeded retained {old_wape:.3f}%"
                    )
                    retained_quality = json.loads(quality_path.read_text(encoding="utf-8"))
                    retained_quality["weather_candidate_evaluation"] = {
                        "station_code": mapping_row.nearest_station,
                        "candidate_average_wape_pct": new_wape,
                        "retained_average_wape_pct": old_wape,
                        "result": "rejected_crop_only_or_previous_model_retained",
                    }
                    temporary_retained_quality = quality_path.with_suffix(".json.tmp")
                    temporary_retained_quality.write_text(
                        json.dumps(retained_quality, indent=2, default=_json_default),
                        encoding="utf-8",
                    )
                    temporary_retained_quality.replace(quality_path)
                    if temporary_retained_quality.exists():
                        temporary_retained_quality.unlink()
                summaries.append(summary)
        except ValueError as exc:
            skipped.append({"estate": estate, "reason": str(exc)})

    print(json.dumps({"updated": summaries, "skipped": skipped}, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
