from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import pandas as pd

from src.pipeline import (
    build_weekly_dataset,
    extend_crop_daily_with_prompt_actuals,
    load_crop_daily,
    load_weather_daily_many,
)
from src.pooled_modeling import train_pooled_forecasts
from train import _json_default, build_dashboard


def main():
    parser = argparse.ArgumentParser(
        description="Train a clearly labelled pooled provisional forecast for one short-history estate."
    )
    parser.add_argument("--estate", required=True)
    parser.add_argument("--crop", required=True)
    parser.add_argument("--weather", action="append", required=True)
    parser.add_argument("--donor-output", action="append", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--weather-mapping", default="config/weather_station_mapping.csv")
    parser.add_argument("--actuals")
    parser.add_argument(
        "--allow-missing-actuals", action="store_true",
        help=("When this estate has no completed PROMPT rows, continue with the historical "
              "crop archive and label the output provisional instead of failing."),
    )
    parser.add_argument("--accelerator", choices=("cpu", "gpu"), default="cpu")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    model_dir = output_dir / "models"
    output_dir.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)
    for old_model in model_dir.glob("horizon_*.joblib"):
        old_model.unlink()
    for temporary in model_dir.glob("*.tmp"):
        temporary.unlink()

    crop_daily, crop_quality = load_crop_daily(args.crop, args.estate)
    if args.actuals:
        crop_daily, crop_quality = extend_crop_daily_with_prompt_actuals(
            crop_daily, crop_quality, args.actuals, args.estate,
            allow_missing_actuals=args.allow_missing_actuals,
        )
    weather_daily, weather_quality = load_weather_daily_many(args.weather)
    target_weekly, join_quality = build_weekly_dataset(crop_daily, weather_daily)
    estate_weekly = {args.estate: target_weekly}

    donor_estates = []
    donor_rows = []
    target_plantations = set(crop_quality.get("plantation_ids", []))
    mapping = pd.read_csv(args.weather_mapping)
    mapping_lookup = {str(r.estate).casefold(): r for _, r in mapping.iterrows()}
    target_map = mapping_lookup.get(args.estate.casefold())

    for donor_path_text in args.donor_output:
        donor_path = Path(donor_path_text)
        quality = json.loads((donor_path / "data_quality.json").read_text(encoding="utf-8"))
        donor = quality["crop"]["estate"]
        donor_plantations = set(quality["crop"].get("plantation_ids", []))
        if target_plantations and donor_plantations != target_plantations:
            raise ValueError(
                f"Donor {donor} plantation IDs {sorted(donor_plantations)} do not match "
                f"target {args.estate} IDs {sorted(target_plantations)}."
            )
        weekly = pd.read_csv(donor_path / "weekly_history.csv", parse_dates=["week_ending"]).set_index("week_ending")
        estate_weekly[donor] = weekly
        donor_estates.append(donor)
        donor_map = mapping_lookup.get(donor.casefold())
        if target_map is not None and donor_map is not None and donor_map.nearest_station != target_map.nearest_station:
            raise ValueError(f"Donor {donor} uses {donor_map.nearest_station}, not target station {target_map.nearest_station}.")
        donor_rows.append({
            "target_estate": args.estate,
            "donor_estate": donor,
            "selection_basis": "same plantation_id and same nearest weather station",
            "plantation_ids": ", ".join(sorted(donor_plantations)),
            "nearest_station": donor_map.nearest_station if donor_map is not None else "",
            "nearest_station_distance_km": donor_map.nearest_distance_km if donor_map is not None else "",
            "crop_date_min": quality["crop"].get("date_min"),
            "crop_date_max": quality["crop"].get("date_max"),
            "weekly_rows": quality["joined"].get("weekly_rows"),
            "field_count": quality["crop"].get("field_count"),
            "division_count": quality["crop"].get("division_count"),
        })

    donor_estates = sorted(donor_estates)
    if len(donor_estates) < 3:
        raise ValueError("At least three comparable donor estates are required for a pooled provisional model.")

    pooled_quality = {
        "provisional": True,
        "training_mode": "short-history pooled provisional",
        "target_estate": args.estate,
        "donor_estates": donor_estates,
        "donor_selection_basis": "same plantation_id 7 and same nearest weather station TRI-TW; not selected by crop performance",
        "normalization": "estate crop is normalized by its trailing 13-week mean before pooling",
        "target_validation": "last 13 target-estate observations held out chronologically for each horizon",
        "warning": "Use for interim planning only until the estate has enough history for its own standard model.",
    }
    quality = {
        "crop": crop_quality,
        "weather": weather_quality,
        "joined": join_quality,
        "pooled_model": pooled_quality,
        "training_accelerator": args.accelerator.upper(),
    }

    result = train_pooled_forecasts(
        estate_weekly=estate_weekly,
        target_estate=args.estate,
        donor_estates=donor_estates,
        model_dir=model_dir,
        accelerator=args.accelerator,
    )
    target_weekly.to_csv(output_dir / "weekly_history.csv", index_label="week_ending")
    result.forecast.to_csv(output_dir / "forecast.csv", index=False)
    result.metrics.to_csv(output_dir / "model_metrics.csv", index=False)
    result.backtest.to_csv(output_dir / "backtest_predictions.csv", index=False)
    result.importance.to_csv(output_dir / "feature_importance.csv", index=False)
    pd.DataFrame(donor_rows).sort_values("donor_estate").to_csv(output_dir / "pooled_donor_audit.csv", index=False)
    (output_dir / "data_quality.json").write_text(
        json.dumps(quality, indent=2, default=_json_default), encoding="utf-8"
    )
    (output_dir / "pooled_model.json").write_text(
        json.dumps(pooled_quality, indent=2), encoding="utf-8"
    )
    build_dashboard(
        args.estate,
        target_weekly,
        result.forecast,
        result.metrics,
        quality,
        output_dir / "forecast_dashboard.html",
    )

    loaded = []
    for model_path in sorted(model_dir.glob("horizon_*.joblib")):
        bundle = joblib.load(model_path)
        loaded.append({
            "horizon": bundle["horizon_weeks"],
            "method": bundle["selected_method"],
        })
    print(json.dumps({
        "estate": args.estate,
        "training_mode": pooled_quality["training_mode"],
        "donor_estates": donor_estates,
        "forecast_rows": result.forecast.to_dict(orient="records"),
        "models_reloaded": loaded,
        "output_dir": str(output_dir.resolve()),
    }, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
