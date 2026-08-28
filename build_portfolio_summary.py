from __future__ import annotations

import argparse
import html
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd


SOURCE_NOTES = {
    "EildonHall": "2023 and 2024 workbooks contain zero crop; usable records begin 2025-06-06.",
    "Tillicoultry": "2023 and 2024 workbooks contain zero crop; usable records begin 2025-07-07.",
    "Pedro": "Pedro/Nuwara Eliya station mapping is used for the Pedro estate.",
}


def output_directories(outputs_dir: Path) -> list[Path]:
    directories = [p for p in outputs_dir.glob("*_provisional") if p.is_dir()]
    root_quality = outputs_dir / "data_quality.json"
    if root_quality.exists():
        directories.append(outputs_dir)
    return sorted(directories, key=lambda p: p.name.lower())


def load_estate_row(directory: Path, today: date, weather_mapping: dict[str, dict]) -> tuple[dict, pd.DataFrame | None]:
    quality = json.loads((directory / "data_quality.json").read_text(encoding="utf-8"))
    pooled_provisional = bool(quality.get("pooled_model", {}).get("provisional"))
    crop = quality["crop"]
    joined = quality["joined"]
    weather = quality["weather"]
    estate = crop["estate"]
    forecast_path = directory / "forecast.csv"
    metrics_path = directory / "model_metrics.csv"

    forecast = pd.read_csv(forecast_path) if forecast_path.exists() else None
    selected = None
    if metrics_path.exists():
        metrics = pd.read_csv(metrics_path)
        selected_mask = metrics["selected"].astype(str).str.casefold().isin({"true", "1", "yes"})
        selected = metrics.loc[selected_mask].copy()

    trained = forecast is not None and not forecast.empty
    if trained:
        forecast_end = pd.to_datetime(forecast["forecast_week_ending"]).max().date()
        origin = pd.to_datetime(forecast["forecast_origin_week_ending"]).max().date()
        operational_status = "OUTDATED—REFRESH DATA" if forecast_end < today else "FORWARD FORECAST"
        average_wape = float(forecast["validation_wape_pct"].mean())
        if pooled_provisional:
            accuracy_band = "Provisional pooled"
        elif average_wape < 20:
            accuracy_band = "Stronger pilot"
        elif average_wape <= 25:
            accuracy_band = "Moderate pilot"
        else:
            accuracy_band = "High uncertainty"
        history_class = (
            ", ".join(sorted(selected["history_class"].dropna().unique()))
            if selected is not None and "history_class" in selected.columns
            else "standard"
        )
    else:
        forecast_end = None
        origin = None
        operational_status = "NOT TRAINABLE—MORE HISTORY NEEDED"
        average_wape = np.nan
        accuracy_band = "Not available"
        history_class = "insufficient history"

    reconciliations = crop.get("yearly_reconciliation", [])
    differences = [abs(float(r["difference_kg"])) for r in reconciliations if r.get("difference_kg") is not None]
    station_codes = weather.get("center_codes", [])
    mapping_row = weather_mapping.get(estate.casefold(), {})
    mapped_station = str(mapping_row.get("nearest_station", ""))
    mapped_distance = mapping_row.get("nearest_distance_km", np.nan)
    weather_tested = bool(weather.get("raw_rows", 0))
    rejected_weather = quality.get("weather_candidate_evaluation", {}).get("result") == "rejected_crop_only_or_previous_model_retained"
    if pooled_provisional:
        model_mode = "Pooled weather tested" if weather_tested else "Pooled crop only"
    else:
        model_mode = "Weather tested" if weather_tested else ("Weather rejected" if rejected_weather else "Crop only")
    weather_selected_horizons = (
        int(forecast["selected_method"].str.startswith("Weather + Crop").sum())
        if trained and weather_tested
        else 0
    )
    gpu_candidate_tested = bool(
        selected is not None
        and metrics["method"].astype(str).str.contains("GPU CatBoost", regex=False).any()
    )
    gpu_selected_horizons = (
        int(forecast["selected_method"].astype(str).str.contains("GPU CatBoost", regex=False).sum())
        if trained
        else 0
    )
    if weather_tested:
        weather_value_status = f"Selected {weather_selected_horizons}/4 horizons"
    elif rejected_weather:
        weather_value_status = "Tested—previous model retained"
    elif mapping_row.get("station_file_status") == "truncated_xlsx":
        weather_value_status = "Not tested—station file blocked"
    else:
        weather_value_status = "Not tested"

    row = {
        "estate": estate,
        "training_status": ("PROVISIONAL POOLED" if pooled_provisional else "TRAINED") if trained else "NOT TRAINABLE",
        "operational_status": operational_status,
        "model_mode": model_mode,
        "weather_station": ", ".join(station_codes) or mapped_station,
        "nearest_station_distance_km": mapped_distance,
        "weather_value_status": weather_value_status,
        "weather_selected_horizons": weather_selected_horizons,
        "gpu_candidate_tested": gpu_candidate_tested,
        "gpu_selected_horizons": gpu_selected_horizons,
        "crop_date_min": crop.get("date_min"),
        "crop_date_max": crop.get("date_max"),
        "forecast_origin": origin.isoformat() if origin else "",
        "forecast_end": forecast_end.isoformat() if forecast_end else "",
        "raw_crop_rows": crop.get("raw_rows", 0),
        "weekly_rows": joined.get("weekly_rows", 0),
        "division_count": crop.get("division_count", 0),
        "field_count": crop.get("field_count", 0),
        "estate_ids": ", ".join(crop.get("estate_ids", [])),
        "annual_reconciliation_max_abs_difference_kg": max(differences) if differences else 0.0,
        "average_selected_wape_pct": average_wape,
        "accuracy_band": accuracy_band,
        "history_class": history_class,
        "filename_warning_count": len(crop.get("filename_estate_mismatches", [])),
        "source_note": SOURCE_NOTES.get(estate, ""),
    }
    return row, forecast


def build_html(summary: pd.DataFrame, output_path: Path, today: date) -> None:
    trained = int((summary["training_status"] == "TRAINED").sum())
    pooled = int((summary["training_status"] == "PROVISIONAL POOLED").sum())
    not_trainable = int((summary["training_status"] == "NOT TRAINABLE").sum())
    crop_weather = int(summary["model_mode"].isin(["Weather tested", "Weather rejected", "Pooled weather tested"]).sum())
    rows = []
    for _, item in summary.sort_values(["training_status", "estate"], ascending=[False, True]).iterrows():
        wape = "—" if pd.isna(item.average_selected_wape_pct) else f"{item.average_selected_wape_pct:.1f}%"
        status_class = "ok" if item.training_status == "TRAINED" else ("warn" if item.training_status == "PROVISIONAL POOLED" else "bad")
        rows.append(
            "<tr>"
            f"<td><b>{html.escape(str(item.estate))}</b></td>"
            f"<td><span class='pill {status_class}'>{html.escape(str(item.training_status))}</span></td>"
            f"<td>{html.escape(str(item.operational_status))}</td>"
            f"<td>{html.escape(str(item.model_mode))}</td>"
            f"<td>{html.escape(str(item.weather_station))}</td>"
            f"<td>{html.escape(str(item.weather_value_status))}</td>"
            f"<td>{html.escape(str(item.crop_date_max))}</td>"
            f"<td>{item.weekly_rows:,.0f}</td>"
            f"<td>{wape}</td>"
            f"<td>{html.escape(str(item.accuracy_band))}</td>"
            f"<td>{html.escape(str(item.source_note))}</td>"
            "</tr>"
        )

    document = f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Plantation Forecasting Portfolio</title><style>
:root{{--green:#0b5c3b;--lime:#a8c53a;--ink:#163229;--muted:#63766e;--bg:#f3f7f4;--line:#d9e5de;--red:#a43d3d}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px Arial,sans-serif}}main{{max-width:1450px;margin:auto;padding:28px}}
header{{background:linear-gradient(130deg,#073e2a,#0c6a46);color:#fff;border-radius:18px;padding:28px 32px}}h1{{margin:4px 0 8px;font-size:32px}}.sub{{color:#dceae3;max-width:1050px;line-height:1.5}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:18px 0}}.card,.panel{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:18px;box-shadow:0 7px 22px #1632290d}}.card b{{display:block;font-size:28px;margin-top:6px}}.card span{{color:var(--muted)}}
.warning{{border-left:5px solid #d99b28;background:#fff9e9;padding:15px 18px;margin:18px 0;border-radius:10px;line-height:1.5}}.panel{{overflow:auto}}table{{border-collapse:collapse;width:100%;min-width:1200px}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{position:sticky;top:0;background:#f8fbf9;text-transform:uppercase;font-size:11px;color:var(--muted)}}.pill{{display:inline-block;padding:4px 8px;border-radius:99px;font-size:11px;font-weight:700}}.pill.ok{{background:#e4f3e8;color:#1d6b35}}.pill.warn{{background:#fff0c7;color:#805b00}}.pill.bad{{background:#fae8e8;color:var(--red)}}
@media(max-width:850px){{.cards{{grid-template-columns:1fr 1fr}}main{{padding:14px}}}}@media(max-width:520px){{.cards{{grid-template-columns:1fr}}}}
</style></head><body><main><header><div>PLANTATION CROP FORECASTING</div><h1>Multi-estate pilot readiness</h1><div class='sub'>Generated {today.isoformat()}. This dashboard reports training readiness and historical validation. It does not label any estate or manager as “best practice” in advance.</div></header>
<section class='cards'><div class='card'><span>Estate datasets represented</span><b>{len(summary)}</b></div><div class='card'><span>Standard estate models</span><b>{trained}</b></div><div class='card'><span>Provisional pooled models</span><b>{pooled}</b></div><div class='card'><span>No forecast available</span><b>{not_trainable}</b></div></section>
<div class='warning'><b>Operational timing:</b> the supplied crop data generally ends in June 2026, so the generated four-week forecast periods have already ended. Upload crop records through the latest completed week before using forecasts for current estate planning. The valid Pedro replacement workbook is used for Pedro-station tests; the original truncated workbook is retained only as a rejected-source audit record.</div>
<section class='panel'><table><thead><tr><th>Estate</th><th>Training</th><th>Operational status</th><th>Mode</th><th>Nearest/used station</th><th>Weather value</th><th>Crop cutoff</th><th>Weeks</th><th>Avg WAPE</th><th>Accuracy band</th><th>Source note</th></tr></thead><tbody>{''.join(rows)}</tbody></table></section>
</main></body></html>"""
    output_path.write_text(document, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outputs-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    parser.add_argument("--weather-mapping", type=Path, default=Path("config/weather_station_mapping.csv"))
    args = parser.parse_args()

    weather_mapping = {}
    if args.weather_mapping.exists():
        mapping_frame = pd.read_csv(args.weather_mapping)
        weather_mapping = {
            str(row["estate"]).casefold(): row.to_dict()
            for _, row in mapping_frame.iterrows()
        }

    rows = []
    forecasts = []
    for directory in output_directories(args.outputs_dir):
        if not (directory / "data_quality.json").exists():
            continue
        row, forecast = load_estate_row(directory, args.today, weather_mapping)
        rows.append(row)
        if forecast is not None:
            forecasts.append(forecast)

    summary = pd.DataFrame(rows).sort_values("estate")
    summary.to_csv(args.outputs_dir / "portfolio_summary.csv", index=False)
    if forecasts:
        combined_forecasts = pd.concat(forecasts, ignore_index=True)
        combined_forecasts.to_csv(args.outputs_dir / "portfolio_forecasts.csv", index=False)
        pooled_estates = set(
            summary.loc[summary["training_status"].eq("PROVISIONAL POOLED"), "estate"]
        )
        combined_forecasts.loc[combined_forecasts["estate"].isin(pooled_estates)].to_csv(
            args.outputs_dir / "pooled_provisional_forecasts.csv", index=False
        )
    build_html(summary, args.outputs_dir / "portfolio_dashboard.html", args.today)
    print(summary[["estate", "training_status", "operational_status", "model_mode", "weather_value_status", "average_selected_wape_pct"]].to_string(index=False))


if __name__ == "__main__":
    main()
