from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


OUTPUTS = Path("outputs")


def estate_directories():
    directories = [p for p in OUTPUTS.glob("*_provisional") if (p / "forecast.csv").exists()]
    if (OUTPUTS / "forecast.csv").exists():
        directories.append(OUTPUTS)
    return sorted(directories)


def circular_seasonality(history: pd.DataFrame) -> pd.Series:
    crop = history["crop_net_kg"].astype(float)
    rolling_level = crop.rolling(52, min_periods=min(26, max(8, len(crop) // 3))).mean()
    fallback = float(crop.tail(min(52, len(crop))).mean())
    rolling_level = rolling_level.fillna(fallback).replace(0, np.nan)
    ratio = (crop / rolling_level).replace([np.inf, -np.inf], np.nan)
    weeks = history.index.isocalendar().week.astype(int)
    factors = ratio.groupby(weeks).median().reindex(range(1, 54))
    factors = factors.interpolate(limit_direction="both").fillna(1.0).clip(0.25, 2.5)
    factors /= factors.mean()
    return factors


def projection_for_estate(directory: Path) -> pd.DataFrame:
    forecast = pd.read_csv(directory / "forecast.csv", parse_dates=[
        "forecast_origin_week_ending", "forecast_week_ending"
    ])
    history = pd.read_csv(directory / "weekly_history.csv", parse_dates=["week_ending"]).set_index("week_ending")
    estate = str(forecast["estate"].iloc[0])
    origin = pd.Timestamp(forecast["forecast_origin_week_ending"].iloc[0]).normalize()
    start = origin + pd.Timedelta(days=1)
    end = origin + pd.DateOffset(years=5)
    dates = pd.date_range(start, end, freq="D")
    week_endings = dates + pd.to_timedelta((6 - dates.weekday) % 7, unit="D")
    unique_week_endings = pd.DatetimeIndex(sorted(set(week_endings)))

    factors = circular_seasonality(history)
    crop = history["crop_net_kg"].astype(float)
    recent_level = float(crop.tail(min(26, len(crop))).mean())
    if len(crop) >= 104:
        recent_year = float(crop.iloc[-52:].mean())
        previous_year = float(crop.iloc[-104:-52].mean())
        annual_trend = np.clip(recent_year / previous_year - 1, -0.05, 0.05) if previous_year else 0.0
    else:
        annual_trend = 0.0
    selected_wape = float(forecast["validation_wape_pct"].mean()) / 100
    base_error = float(np.clip(selected_wape, 0.12, 0.40))
    planned_crop_days = int(np.clip(round(float(history["crop_days"].tail(min(26, len(history))).median())), 1, 7))
    validated = forecast.set_index("forecast_week_ending")

    weekly_rows = []
    for week_ending in unique_week_endings:
        horizon_weeks = max(1, int(round((week_ending - origin).days / 7)))
        if week_ending in validated.index:
            row = validated.loc[week_ending]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            point = float(row["forecast_kg"])
            lower = float(row["lower_80_kg"])
            upper = float(row["upper_80_kg"])
            method = str(row["selected_method"])
            tier = "Validated 1–4 week forecast"
        else:
            week_number = int(week_ending.isocalendar().week)
            year_fraction = horizon_weeks / 52.1775
            trend_factor = (1 + annual_trend) ** min(year_fraction, 3.0)
            point = max(0.0, recent_level * float(factors.loc[week_number]) * trend_factor)
            uncertainty = min(0.85, base_error * np.sqrt(1 + horizon_weeks / 52.1775))
            lower = max(0.0, point * (1 - uncertainty))
            upper = point * (1 + uncertainty)
            method = "Estate seasonal level with capped, three-year trend"
            if horizon_weeks <= 52:
                tier = "Year-1 tactical planning projection"
            elif horizon_weeks <= 156:
                tier = "Years 2–3 seasonal planning projection"
            else:
                tier = "Years 4–5 strategic scenario"
        weekly_rows.append((week_ending, horizon_weeks, point, lower, upper, method, tier))
    weekly = pd.DataFrame(weekly_rows, columns=[
        "week_ending", "horizon_weeks", "weekly_kg", "weekly_lower_80_kg",
        "weekly_upper_80_kg", "projection_method", "projection_tier"
    ]).set_index("week_ending")

    daily_rows = []
    for day, week_ending in zip(dates, week_endings):
        weekly_row = weekly.loc[week_ending]
        is_planned_crop_day = day.weekday() < planned_crop_days
        share = 1 / planned_crop_days if is_planned_crop_day else 0.0
        daily_rows.append({
            "estate": estate,
            "date": day.date().isoformat(),
            "forecast_origin": origin.date().isoformat(),
            "current_practice_kg": float(weekly_row.weekly_kg * share),
            "current_lower_80_kg": float(weekly_row.weekly_lower_80_kg * share),
            "current_upper_80_kg": float(weekly_row.weekly_upper_80_kg * share),
            "best_practice_kg": np.nan,
            "actual_kg": np.nan,
            "projection_tier": weekly_row.projection_tier,
            "projection_method": weekly_row.projection_method,
            "daily_allocation_basis": f"Weekly forecast allocated equally across {planned_crop_days} planned crop days",
            "data_status": "PLANNING PROJECTION—REFRESH CROP AND WEATHER DATA",
        })
    return pd.DataFrame(daily_rows)


def main():
    frames = [projection_for_estate(directory) for directory in estate_directories()]
    combined = pd.concat(frames, ignore_index=True).sort_values(["estate", "date"])
    output = OUTPUTS / "five_year_daily_projection.csv"
    combined.to_csv(output, index=False)
    print({
        "output": str(output.resolve()),
        "estates": int(combined["estate"].nunique()),
        "rows": int(len(combined)),
        "date_min": combined["date"].min(),
        "date_max": combined["date"].max(),
        "best_practice_status": "awaiting field/practice data; no values fabricated",
    })


if __name__ == "__main__":
    main()
