from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import pandas as pd

from src.modeling import train_direct_forecasts
from src.pipeline import (
    build_weekly_crop_only_dataset,
    build_weekly_dataset,
    extend_crop_daily_with_prompt_actuals,
    load_crop_daily,
    load_weather_daily_many,
)


def _json_default(value):
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(type(value).__name__)


def build_dashboard(estate, history, forecast, model_metrics, quality, output_path):
    pooled = quality.get("pooled_model", {})
    direct_model = quality.get("direct_model", {})
    is_pooled_provisional = bool(pooled.get("provisional"))
    is_direct_provisional = bool(direct_model.get("provisional"))
    history_points = [
        {"week": idx.date().isoformat(), "kg": round(float(row.crop_net_kg), 1)}
        for idx, row in history.tail(78).iterrows()
    ]
    forecast_points = [
        {
            "start": pd.Timestamp(row.forecast_week_starting).date().isoformat(),
            "end": pd.Timestamp(row.forecast_week_ending).date().isoformat(),
            "kg": round(float(row.forecast_kg), 1),
            "low": round(float(row.lower_80_kg), 1),
            "high": round(float(row.upper_80_kg), 1),
            "method": row.selected_method,
            "wape": round(float(row.validation_wape_pct), 1),
        }
        for _, row in forecast.iterrows()
    ]
    selected = model_metrics[model_metrics["selected"]].copy()
    station_label = ", ".join(quality["weather"].get("center_codes", []))
    crop_cutoff = quality["crop"].get("date_max", "unknown")
    weather_cutoff = quality["weather"].get("date_max") or "not supplied"
    origin_cutoff = pd.Timestamp(forecast["forecast_origin_week_ending"].iloc[0]).date().isoformat()
    cutoff_warning = (
        f"Data status: crop records end {crop_cutoff}; weather records end {weather_cutoff}; "
        f"forecast origin is {origin_cutoff}. Treat the result as current only to that crop cutoff."
    )
    cards = "".join(
        f'''<article class="card"><div class="eyebrow">Week {i + 1}</div><div class="number">{p['kg']:,.0f} kg</div>
        <div>{p['start']} to {p['end']}</div><div class="range">80% range: {p['low']:,.0f}–{p['high']:,.0f} kg</div></article>'''
        for i, p in enumerate(forecast_points)
    )
    metrics_rows = "".join(
        f"<tr><td>{int(r.horizon_weeks)}</td><td>{r.method}</td><td>{r.mae_kg:,.0f}</td><td>{r.rmse_kg:,.0f}</td><td>{r.wape_pct:.1f}%</td></tr>"
        for _, r in selected.iterrows()
    )
    payload = json.dumps({"history": history_points, "forecast": forecast_points})
    if is_pooled_provisional:
        donors = ", ".join(pooled.get("donor_estates", []))
        forecast_description = (
            f"Four-week provisional pooled green-leaf forecast using the estate's available history, "
            f"{station_label} weather and comparable plantation peers."
        )
        scope_warning = (
            f"PROVISIONAL POOLED MODEL—SHORT ESTATE HISTORY. Donors: {donors}. "
            "Donors were selected by plantation ID and weather station, not because of high crop. "
            "Use for interim planning only; replace it with the standard estate-specific model when sufficient history is available."
        )
        dashboard_kicker = "Short-history provisional pooled forecast"
    elif is_direct_provisional:
        forecast_description = (
            f"Four-week short-history provisional green-leaf forecast using crop history and {station_label} weather observations."
            if station_label
            else "Four-week short-history provisional green-leaf forecast using crop history only."
        )
        scope_warning = (
            "PROVISIONAL SHORT-HISTORY MODEL. Incomplete crop weeks remain excluded. "
            "Use for interim model development only and replace with the standard gate when more history is available."
        )
        dashboard_kicker = "Short-history estate-specific provisional forecast"
    else:
        forecast_description = (
            f"Four-week green-leaf forecast using crop history and {station_label} weather observations."
            if station_label
            else "Four-week green-leaf forecast using crop history only; no representative weather mapping was supplied."
        )
        scope_warning = "Pilot scope only: the group forecast requires confirmed estate-to-weather-station mappings and clean historical files for every estate."
        dashboard_kicker = "Plantation crop forecasting pilot"
    html = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{estate} Crop Forecast</title><style>
:root{{--green:#0c5b3c;--lime:#a8c53a;--ink:#17332a;--muted:#65776f;--bg:#f3f7f4;--line:#d9e5de;}}
*{{box-sizing:border-box}}body{{margin:0;font-family:Arial,sans-serif;background:var(--bg);color:var(--ink)}}
.shell{{max-width:1180px;margin:auto;padding:32px}}header{{background:linear-gradient(130deg,#073e2a,#0c6a46);color:white;border-radius:18px;padding:30px 34px;box-shadow:0 14px 40px #17332a22}}
h1{{margin:5px 0;font-size:34px}}h2{{margin-top:0}}.kicker,.eyebrow{{text-transform:uppercase;letter-spacing:.12em;font-weight:700;font-size:12px;color:var(--lime)}}
.warning{{margin-top:14px;color:#e8f2ed;max-width:900px;line-height:1.45}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:20px 0}}
.card,.panel{{background:white;border:1px solid var(--line);border-radius:14px;padding:20px;box-shadow:0 8px 24px #17332a0c}}.number{{font-size:27px;font-weight:800;margin:8px 0}}.range{{margin-top:8px;color:var(--muted);font-size:13px}}
.panel{{margin-top:18px}}svg{{width:100%;height:330px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:11px 10px;border-bottom:1px solid var(--line);text-align:left}}th{{font-size:12px;text-transform:uppercase;color:var(--muted)}}
.facts{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.fact b{{display:block;font-size:22px}}.fact span{{color:var(--muted);font-size:13px}}
@media(max-width:850px){{.grid,.facts{{grid-template-columns:1fr 1fr}}}}@media(max-width:520px){{.grid,.facts{{grid-template-columns:1fr}}.shell{{padding:14px}}}}
</style></head><body><main class="shell"><header><div class="kicker">{dashboard_kicker}</div><h1>{estate}</h1>
<div>{forecast_description}</div><div class="warning">{cutoff_warning} {scope_warning}</div></header>
<section class="grid">{cards}</section><section class="panel"><h2>Weekly crop history and forecast</h2><svg id="chart" viewBox="0 0 1080 330" role="img" aria-label="Weekly crop history and forecast"></svg></section>
<section class="panel"><h2>Selected method by forecast horizon</h2><table><thead><tr><th>Horizon (weeks)</th><th>Method</th><th>MAE (kg)</th><th>RMSE (kg)</th><th>WAPE</th></tr></thead><tbody>{metrics_rows}</tbody></table></section>
<section class="panel"><h2>Data readiness</h2><div class="facts"><div class="fact"><b>{quality['crop']['raw_rows']:,}</b><span>crop weighing records</span></div><div class="fact"><b>{quality['weather']['raw_rows']:,}</b><span>weather readings</span></div><div class="fact"><b>{quality['joined']['weekly_rows']}</b><span>complete weekly observations</span></div><div class="fact"><b>{quality['weather']['coverage_pct']:.1f}%</b><span>weather-day coverage</span></div></div></section>
</main><script>const data={payload};const svg=document.getElementById('chart');const all=[...data.history.map(d=>({{x:d.week,y:d.kg,t:'Actual'}})),...data.forecast.map(d=>({{x:d.end,y:d.kg,t:'Forecast'}}))];
const W=1080,H=330,p={{l:65,r:25,t:20,b:45}},max=Math.max(...all.map(d=>d.y))*1.12,min=0,step=(W-p.l-p.r)/(all.length-1);const sx=i=>p.l+i*step,sy=v=>p.t+(H-p.t-p.b)*(1-v/max);
let g='';for(let i=0;i<=4;i++){{let y=p.t+i*(H-p.t-p.b)/4,val=max*(1-i/4);g+=`<line x1="${{p.l}}" y1="${{y}}" x2="${{W-p.r}}" y2="${{y}}" stroke="#d9e5de"/><text x="${{p.l-8}}" y="${{y+4}}" text-anchor="end" fill="#65776f" font-size="11">${{Math.round(val/1000)}}k</text>`}}
const split=data.history.length;const hist=all.slice(0,split).map((d,i)=>`${{sx(i)}},${{sy(d.y)}}`).join(' ');const fc=all.slice(split-1).map((d,j)=>`${{sx(split-1+j)}},${{sy(d.y)}}`).join(' ');
g+=`<polyline points="${{hist}}" fill="none" stroke="#0c5b3c" stroke-width="2.5"/><polyline points="${{fc}}" fill="none" stroke="#a8c53a" stroke-width="3.5" stroke-dasharray="8 5"/>`;
for(let j=split;j<all.length;j++)g+=`<circle cx="${{sx(j)}}" cy="${{sy(all[j].y)}}" r="5" fill="#a8c53a"/>`;g+=`<text x="${{p.l}}" y="${{H-12}}" fill="#65776f" font-size="11">${{all[0].x}}</text><text x="${{W-p.r}}" y="${{H-12}}" text-anchor="end" fill="#65776f" font-size="11">${{all[all.length-1].x}}</text>`;svg.innerHTML=g;</script></body></html>'''
    Path(output_path).write_text(html, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Train a leakage-controlled four-week plantation crop forecast.")
    parser.add_argument(
        "--weather",
        action="append",
        help="Optional mapped sub-daily weather .xlsx file; repeat for later station update workbooks",
    )
    parser.add_argument("--crop", required=True, help="Crop .xlsx, folder, or ZIP archive")
    parser.add_argument("--estate", required=True, help="Estate name")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument(
        "--actuals",
        help="Optional privacy-safe prompt_daily_actuals.csv; only completed dates before today are used",
    )
    parser.add_argument(
        "--accelerator", choices=("cpu", "gpu"), default="cpu",
        help="Run CPU candidates only, or add GPU CatBoost candidates for every horizon",
    )
    parser.add_argument(
        "--allow-missing-actuals", action="store_true",
        help=("When this estate has no completed PROMPT rows, continue with the historical "
              "crop archive and label the output provisional instead of failing."),
    )
    parser.add_argument(
        "--short-history-provisional", action="store_true",
        help=("Use the guarded short-history thresholds: at least 26 training weeks and "
              "8 chronological validation weeks. The result is labelled provisional."),
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    model_dir = output_dir / "models"
    model_dir.mkdir(parents=True, exist_ok=True)

    crop_daily, crop_quality = load_crop_daily(args.crop, args.estate)
    if args.actuals:
        crop_daily, crop_quality = extend_crop_daily_with_prompt_actuals(
            crop_daily, crop_quality, args.actuals, args.estate,
            allow_missing_actuals=args.allow_missing_actuals,
        )
    if args.weather:
        weather_daily, weather_quality = load_weather_daily_many(args.weather)
        weekly, join_quality = build_weekly_dataset(crop_daily, weather_daily)
        use_weather = True
    else:
        weather_quality = {
            "source_file": None,
            "center_codes": [],
            "raw_rows": 0,
            "date_min": None,
            "date_max": None,
            "observed_days": 0,
            "calendar_days": 0,
            "missing_calendar_days": 0,
            "coverage_pct": 0.0,
            "mode": "crop_only",
        }
        weekly, join_quality = build_weekly_crop_only_dataset(crop_daily)
        use_weather = False
    quality = {
        "crop": crop_quality,
        "weather": weather_quality,
        "joined": join_quality,
        "training_accelerator": args.accelerator.upper(),
        "gpu_candidate_policy": (
            "GPU CatBoost is tested for every horizon and selected only when chronological WAPE is lowest"
            if args.accelerator == "gpu"
            else "CPU candidates only"
        ),
    }
    if args.short_history_provisional:
        quality["direct_model"] = {
            "provisional": True,
            "training_mode": "short-history estate-specific provisional",
            "minimum_training_weeks": 26,
            "minimum_validation_weeks": 8,
            "warning": (
                "Use for interim model development only. The standard 52-week training plus "
                "13-week validation gate was not available after incomplete crop weeks were excluded."
            ),
        }
    (output_dir / "data_quality.json").write_text(
        json.dumps(quality, indent=2, default=_json_default), encoding="utf-8"
    )
    result = train_direct_forecasts(
        weekly,
        model_dir=model_dir,
        use_weather=use_weather,
        accelerator=args.accelerator,
        validation_weeks=(13 if args.short_history_provisional else 26),
        minimum_training_weeks=(26 if args.short_history_provisional else 52),
        minimum_validation_weeks=(8 if args.short_history_provisional else 13),
        history_class_override=(
            "short-history estate-specific provisional"
            if args.short_history_provisional else None
        ),
    )

    forecast = result.forecast.copy()
    forecast.insert(0, "estate", args.estate)
    metrics_df = pd.DataFrame(result.model_rows)
    importance_rows = []
    for model_path in sorted(model_dir.glob("horizon_*.joblib")):
        bundle = joblib.load(model_path)
        model = bundle["model"]
        if hasattr(model, "feature_importances_"):
            for feature, importance in zip(bundle["features"], model.feature_importances_):
                importance_rows.append({
                    "horizon_weeks": bundle["horizon_weeks"],
                    "selected_method": bundle["selected_method"],
                    "feature": feature,
                    "importance": float(importance),
                })
    importance_df = pd.DataFrame(importance_rows)
    weekly.to_csv(output_dir / "weekly_history.csv", index_label="week_ending")
    forecast.to_csv(output_dir / "forecast.csv", index=False)
    result.backtest.to_csv(output_dir / "backtest_predictions.csv", index=False)
    metrics_df.to_csv(output_dir / "model_metrics.csv", index=False)
    importance_df.to_csv(output_dir / "feature_importance.csv", index=False)
    build_dashboard(args.estate, weekly, forecast, metrics_df, quality, output_dir / "forecast_dashboard.html")
    print(json.dumps({
        "estate": args.estate,
        "forecast_origin": forecast["forecast_origin_week_ending"].iloc[0].isoformat(),
        "forecast_rows": forecast.to_dict(orient="records"),
        "output_dir": str(output_dir.resolve()),
    }, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
