from __future__ import annotations

import tempfile
import zipfile
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import load_workbook


def _as_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_date(value):
    if value is None:
        return None
    return pd.to_datetime(value, errors="coerce").normalize()


def load_weather_daily(path: str | Path) -> tuple[pd.DataFrame, dict]:
    """Convert sub-daily sensor readings into one auditable row per day.

    Rainfall and sunshine are treated as cumulative sensor counters and use the
    daily maximum. Summing the raw readings would materially overstate rainfall.
    """
    path = Path(path)
    if path.suffix.casefold() == ".csv":
        daily = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
        required_daily = {"rainfall_mm"}
        missing = required_daily.difference(daily.columns)
        if missing:
            raise ValueError(f"Prepared weather cache is missing columns: {sorted(missing)}")
        # Only rainfall is mandatory for a prepared station cache.  Older or
        # externally prepared caches may not contain every optional sensor
        # field.  Preserve a stable schema so one absent sensor cannot abort an
        # otherwise valid overnight portfolio run.
        optional_daily = [
            "air_temp_mean", "air_temp_min", "air_temp_max",
            "humidity_mean", "humidity_min", "humidity_max",
            "wind_speed_mean", "gust_speed_max", "uv_max", "light_mean",
            "sunshine_duration", "soil_moisture_mean", "soil_temp_mean",
            "ammonia_mean",
        ]
        for column in optional_daily:
            if column not in daily.columns:
                daily[column] = np.nan
        if "weather_records" not in daily.columns:
            daily["weather_records"] = 1
        companion = path.with_suffix(".quality.json")
        if companion.exists():
            import json
            quality = json.loads(companion.read_text(encoding="utf-8"))
        else:
            span = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
            quality = {
                "source_file": path.name,
                "center_codes": [],
                "raw_rows": int(daily["weather_records"].fillna(0).sum()),
                "date_min": daily.index.min().date().isoformat(),
                "date_max": daily.index.max().date().isoformat(),
                "observed_days": int(len(daily)),
                "calendar_days": int(len(span)),
                "missing_calendar_days": int(len(span) - len(daily)),
                "coverage_pct": round(100 * len(daily) / len(span), 2),
            }
        quality = {**quality, "prepared_daily_cache": True, "cache_file": path.name}
        return daily, quality
    wb = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    required = ["Date Recorded", "Air Temp (C)", "Humidity (%)", "Rainfall (mm)"]
    candidate_sheets = [wb["All Records"]] if "All Records" in wb.sheetnames else list(wb.worksheets)
    ws = None
    header = None
    for candidate in candidate_sheets:
        candidate_header = [
            str(v).strip() if v is not None else ""
            for v in next(candidate.iter_rows(min_row=1, max_row=1, values_only=True))
        ]
        if set(required).issubset(candidate_header):
            ws = candidate
            header = candidate_header
            break
    if ws is None or header is None:
        wb.close()
        raise ValueError(
            f"No worksheet contains the required weather columns: {required}. "
            f"Available sheets: {wb.sheetnames}"
        )
    idx = {name: i for i, name in enumerate(header)}
    missing_required = [c for c in required if c not in idx]
    if missing_required:
        raise ValueError(f"Missing required weather columns: {missing_required}")

    fields = {
        "air_temp": "Air Temp (C)",
        "humidity": "Humidity (%)",
        "rainfall": "Rainfall (mm)",
        "wind_speed": "Wind Speed (km/h)",
        "gust_speed": "Gust Speed (km/h)",
        "uv": "UV Level (uw/sq.cm)",
        "light": "Light Level (Lux)",
        "sunshine": "Sunshine Duration",
        "soil_moisture": "Soil Moisture (%)",
        "soil_temp": "Soil Temp (C)",
        "ammonia": "Ammonia Level (ppm)",
    }
    available = {key: idx[col] for key, col in fields.items() if col in idx}
    by_day = defaultdict(lambda: {"records": 0, **{key: [] for key in available}})
    centers = set()
    rows = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        rows += 1
        day = _as_date(row[idx["Date Recorded"]])
        if pd.isna(day):
            continue
        if "Center" in idx and row[idx["Center"]] is not None:
            centers.add(str(row[idx["Center"]]))
        rec = by_day[day]
        rec["records"] += 1
        for key, col_idx in available.items():
            val = _as_float(row[col_idx])
            if val is not None:
                rec[key].append(val)
    wb.close()

    records = []
    for day, values in by_day.items():
        def stat(key, reducer):
            observations = values.get(key, [])
            return reducer(observations) if observations else np.nan

        row = {
            "date": day,
            "weather_records": values["records"],
            "air_temp_mean": stat("air_temp", np.mean),
            "air_temp_min": stat("air_temp", np.min),
            "air_temp_max": stat("air_temp", np.max),
            "humidity_mean": stat("humidity", np.mean),
            "humidity_min": stat("humidity", np.min),
            "humidity_max": stat("humidity", np.max),
            "rainfall_mm": stat("rainfall", np.max),
            "wind_speed_mean": stat("wind_speed", np.mean),
            "gust_speed_max": stat("gust_speed", np.max),
            "uv_max": stat("uv", np.max),
            "light_mean": stat("light", np.mean),
            "sunshine_duration": stat("sunshine", np.max),
            "soil_moisture_mean": stat("soil_moisture", np.mean),
            "soil_temp_mean": stat("soil_temp", np.mean),
            "ammonia_mean": stat("ammonia", np.mean),
        }
        records.append(row)
    daily = pd.DataFrame(records).sort_values("date").set_index("date")
    span = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    quality = {
        "source_file": path.name,
        "source_sheet": ws.title,
        "center_codes": sorted(centers),
        "raw_rows": int(rows),
        "date_min": daily.index.min().date().isoformat(),
        "date_max": daily.index.max().date().isoformat(),
        "observed_days": int(len(daily)),
        "calendar_days": int(len(span)),
        "missing_calendar_days": int(len(span) - len(daily)),
        "coverage_pct": round(100 * len(daily) / len(span), 2),
    }
    return daily, quality


def load_weather_daily_many(paths: list[str | Path]) -> tuple[pd.DataFrame, dict]:
    """Merge a station's base workbook and later update workbooks.

    Files are applied in command-line order, so a later update replaces an
    overlapping daily record from the base history.
    """
    if not paths:
        raise ValueError("At least one weather workbook is required.")
    frames = []
    source_qualities = []
    for path in paths:
        frame, quality = load_weather_daily(path)
        frames.append(frame)
        source_qualities.append(quality)
    combined = pd.concat(frames)
    combined = combined.loc[~combined.index.duplicated(keep="last")].sort_index()
    span = pd.date_range(combined.index.min(), combined.index.max(), freq="D")
    centers = sorted(
        {
            center
            for quality in source_qualities
            for center in quality.get("center_codes", [])
        }
    )
    quality = {
        "source_file": " + ".join(q["source_file"] for q in source_qualities),
        "source_files": [q["source_file"] for q in source_qualities],
        "source_sheets": [q.get("source_sheet") for q in source_qualities],
        "center_codes": centers,
        "raw_rows": int(sum(q["raw_rows"] for q in source_qualities)),
        "date_min": combined.index.min().date().isoformat(),
        "date_max": combined.index.max().date().isoformat(),
        "observed_days": int(len(combined)),
        "calendar_days": int(len(span)),
        "missing_calendar_days": int(len(span) - len(combined)),
        "coverage_pct": round(100 * len(combined) / len(span), 2),
        "individual_sources": source_qualities,
    }
    return combined, quality


def _crop_files(source: Path, work_dir: Path) -> list[Path]:
    if source.is_dir():
        return sorted(source.glob("*.xlsx"))
    if source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as archive:
            members = [m for m in archive.namelist() if m.lower().endswith(".xlsx")]
            archive.extractall(work_dir, members)
        return sorted(work_dir.rglob("*.xlsx"))
    if source.suffix.lower() == ".xlsx":
        return [source]
    raise ValueError("Crop source must be an .xlsx file, a folder of .xlsx files, or a .zip archive.")


def load_crop_daily(source: str | Path, estate_name: str) -> tuple[pd.DataFrame, dict]:
    """Aggregate employee-level weighing records without retaining personal data."""
    source = Path(source)
    totals = defaultdict(lambda: {"crop_net_kg": 0.0, "crop_gross_kg": 0.0, "crop_records": 0})
    raw_rows = 0
    duplicate_ids = 0
    zero_net_rows = 0
    negative_net_rows = 0
    status_counts = defaultdict(int)
    divisions = set()
    fields = set()
    estate_ids = set()
    plantation_ids = set()
    workbook_files = []
    filename_estate_mismatches = []
    yearly_reconciliation = []

    normalized_estate = re.sub(r"[^a-z0-9]", "", estate_name.lower())

    with tempfile.TemporaryDirectory(prefix="crop_ingest_") as tmp:
        files = _crop_files(source, Path(tmp))
        if not files:
            raise ValueError("No .xlsx crop files were found.")
        for path in files:
            workbook_files.append(path.name)
            normalized_stem = re.sub(r"[^a-z0-9]", "", path.stem.lower())
            if normalized_estate and normalized_estate not in normalized_stem:
                filename_estate_mismatches.append(path.name)
            wb = load_workbook(path, read_only=True, data_only=True, keep_links=False)
            if "All Records" not in wb.sheetnames:
                wb.close()
                continue
            ws = wb["All Records"]
            header = [str(v).strip() if v is not None else "" for v in next(ws.iter_rows(min_row=1, max_row=1, values_only=True))]
            idx = {name: i for i, name in enumerate(header)}
            required = ["date", "weighing_id", "original_weight", "net_weight"]
            missing_required = [c for c in required if c not in idx]
            if missing_required:
                wb.close()
                raise ValueError(f"{path.name} is missing crop columns: {missing_required}")
            seen_ids = set()
            file_net = 0.0
            for row in ws.iter_rows(min_row=2, values_only=True):
                raw_rows += 1
                day = _as_date(row[idx["date"]])
                if pd.isna(day):
                    continue
                status = str(row[idx["w_status"]]) if "w_status" in idx and row[idx["w_status"]] is not None else "(blank)"
                status_counts[status] += 1
                weighing_id = row[idx["weighing_id"]]
                if weighing_id in seen_ids:
                    duplicate_ids += 1
                    continue
                seen_ids.add(weighing_id)
                gross = _as_float(row[idx["original_weight"]]) or 0.0
                net = _as_float(row[idx["net_weight"]])
                if net is None:
                    continue
                if net == 0:
                    zero_net_rows += 1
                if net < 0:
                    negative_net_rows += 1
                file_net += net
                rec = totals[day]
                rec["crop_net_kg"] += net
                rec["crop_gross_kg"] += gross
                rec["crop_records"] += 1
                if "division_name" in idx and row[idx["division_name"]] is not None:
                    divisions.add(str(row[idx["division_name"]]))
                if "field_name" in idx and row[idx["field_name"]] is not None:
                    fields.add(str(row[idx["field_name"]]))
                if "estate_id" in idx and row[idx["estate_id"]] is not None:
                    estate_ids.add(str(row[idx["estate_id"]]))
                if "plantation_id" in idx and row[idx["plantation_id"]] is not None:
                    plantation_ids.add(str(row[idx["plantation_id"]]))

            summary_net = None
            if "Monthly Summary" in wb.sheetnames:
                sws = wb["Monthly Summary"]
                summary_net = 0.0
                for r in range(2, sws.max_row + 1):
                    label = sws.cell(r, 1).value
                    if isinstance(label, str) and label.endswith(" - Net Kg"):
                        summary_net += _as_float(sws.cell(r, 35).value) or 0.0
            wb.close()
            yearly_reconciliation.append({
                "file": path.name,
                "computed_net_kg": round(file_net, 2),
                "summary_net_kg": round(summary_net, 2) if summary_net is not None else None,
                "difference_kg": round(file_net - summary_net, 2) if summary_net is not None else None,
            })

    daily = pd.DataFrame([{"date": day, **values} for day, values in totals.items()]).sort_values("date").set_index("date")
    observed_days = len(daily)
    full_index = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(full_index)
    daily.index.name = "date"
    daily["has_crop_records"] = daily["crop_records"].notna().astype(int)
    daily[["crop_net_kg", "crop_gross_kg", "crop_records"]] = daily[["crop_net_kg", "crop_gross_kg", "crop_records"]].fillna(0)
    daily["estate"] = estate_name
    quality = {
        "source_file": source.name,
        "estate": estate_name,
        "raw_rows": int(raw_rows),
        "date_min": daily.index.min().date().isoformat(),
        "date_max": daily.index.max().date().isoformat(),
        "observed_crop_days": int(observed_days),
        "calendar_days": int(len(daily)),
        "non_record_days_treated_as_zero": int(len(daily) - observed_days),
        "duplicate_weighing_ids_removed": int(duplicate_ids),
        "zero_net_rows": int(zero_net_rows),
        "negative_net_rows": int(negative_net_rows),
        "division_count": int(len(divisions)),
        "field_count": int(len(fields)),
        "estate_ids": sorted(estate_ids),
        "plantation_ids": sorted(plantation_ids),
        "workbook_files": workbook_files,
        "filename_estate_mismatches": filename_estate_mismatches,
        "status_counts": dict(status_counts),
        "yearly_reconciliation": yearly_reconciliation,
    }
    return daily, quality


def extend_crop_daily_with_prompt_actuals(
    crop_daily: pd.DataFrame,
    crop_quality: dict,
    actuals_path: str | Path,
    estate_name: str,
    as_of: pd.Timestamp | None = None,
    allow_missing_actuals: bool = False,
) -> tuple[pd.DataFrame, dict]:
    """Append privacy-safe completed PROMPT estate/day totals to training data.

    Values dated today or later are excluded because the current day can be
    incomplete at the 7:00 AM refresh. Overlapping completed dates are replaced
    by the reconciled PROMPT estate/day total.
    """
    actuals_path = Path(actuals_path)
    if not actuals_path.exists():
        raise FileNotFoundError(f"PROMPT actuals file not found: {actuals_path}")
    actuals = pd.read_csv(actuals_path)
    required = {"estate", "date", "actual_kg"}
    missing = required.difference(actuals.columns)
    if missing:
        raise ValueError(f"PROMPT actuals are missing columns: {sorted(missing)}")
    actuals["date"] = pd.to_datetime(actuals["date"], errors="coerce").dt.normalize()
    actuals["actual_kg"] = pd.to_numeric(actuals["actual_kg"], errors="coerce")
    cutoff = (as_of or pd.Timestamp.today()).normalize()
    normalized = re.sub(r"[^a-z0-9]", "", estate_name.casefold())
    estate_actuals = actuals.loc[
        actuals["estate"].astype(str).map(
            lambda value: re.sub(r"[^a-z0-9]", "", value.casefold())
        ).eq(normalized)
        & actuals["date"].notna()
        & actuals["date"].lt(cutoff)
        & actuals["actual_kg"].notna()
        & actuals["actual_kg"].ge(0),
        ["date", "actual_kg"],
    ].copy()
    if estate_actuals.empty:
        if not allow_missing_actuals:
            raise ValueError(
                f"No completed PROMPT actual rows were found for {estate_name} before {cutoff.date()}"
            )
        quality = dict(crop_quality)
        quality["prompt_actual_extension"] = {
            "status": "SKIPPED_NO_MATCHING_COMPLETED_ROWS",
            "source_file": actuals_path.name,
            "rows_used": 0,
            "completed_day_cutoff_exclusive": cutoff.date().isoformat(),
            "fallback": "historical crop archive only",
            "provisional": True,
            "personal_identifiers_retained": False,
        }
        return crop_daily, quality
    if estate_actuals["date"].duplicated().any():
        estate_actuals = estate_actuals.groupby("date", as_index=False)["actual_kg"].sum()

    daily = crop_daily.copy()
    last_date = max(daily.index.max(), estate_actuals["date"].max())
    daily = daily.reindex(pd.date_range(daily.index.min(), last_date, freq="D"))
    daily.index.name = "date"
    for column in ["crop_net_kg", "crop_gross_kg", "crop_records", "has_crop_records"]:
        if column not in daily:
            daily[column] = 0.0
    daily[["crop_net_kg", "crop_gross_kg", "crop_records", "has_crop_records"]] = daily[
        ["crop_net_kg", "crop_gross_kg", "crop_records", "has_crop_records"]
    ].fillna(0)
    for row in estate_actuals.itertuples(index=False):
        daily.loc[row.date, "crop_net_kg"] = float(row.actual_kg)
        daily.loc[row.date, "crop_gross_kg"] = float(row.actual_kg)
        daily.loc[row.date, "crop_records"] = max(1.0, float(daily.loc[row.date, "crop_records"]))
        daily.loc[row.date, "has_crop_records"] = 1
    daily["estate"] = estate_name

    quality = dict(crop_quality)
    quality["date_max"] = daily.index.max().date().isoformat()
    quality["calendar_days"] = int(len(daily))
    quality["observed_crop_days"] = int((daily["has_crop_records"] > 0).sum())
    quality["non_record_days_treated_as_zero"] = int((daily["has_crop_records"] == 0).sum())
    quality["prompt_actual_extension"] = {
        "source_file": actuals_path.name,
        "rows_used": int(len(estate_actuals)),
        "date_min": estate_actuals["date"].min().date().isoformat(),
        "date_max": estate_actuals["date"].max().date().isoformat(),
        "completed_day_cutoff_exclusive": cutoff.date().isoformat(),
        "overlap_policy": "PROMPT estate/day total replaces the same completed date",
        "personal_identifiers_retained": False,
    }
    return daily, quality


def build_weekly_dataset(crop_daily: pd.DataFrame, weather_daily: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    boundary = crop_daily.index.max()
    start = crop_daily.index.min()
    daily = crop_daily.loc[start:boundary].join(weather_daily, how="left")
    weather_cols = [c for c in weather_daily.columns if c != "weather_records"]
    daily[weather_cols] = daily[weather_cols].interpolate(limit=2, limit_direction="both")
    daily["has_weather"] = daily["weather_records"].notna().astype(int)

    weekly = pd.DataFrame(index=daily.resample("W-SUN").size().index)
    weekly["crop_net_kg"] = daily["crop_net_kg"].resample("W-SUN").sum()
    weekly["crop_records"] = daily["crop_records"].resample("W-SUN").sum()
    weekly["crop_days"] = daily["has_crop_records"].resample("W-SUN").sum()
    weekly["weather_days"] = daily["has_weather"].resample("W-SUN").sum()
    weekly["rainfall_mm"] = daily["rainfall_mm"].resample("W-SUN").sum(min_count=1)
    for col in [c for c in weather_cols if c != "rainfall_mm"]:
        weekly[col] = daily[col].resample("W-SUN").mean()

    incomplete_crop_week = weekly["crop_days"] < 3
    weekly.loc[incomplete_crop_week, "crop_net_kg"] = np.nan

    last_complete_sunday = boundary - pd.Timedelta(days=(boundary.weekday() + 1) % 7)
    weekly = weekly.loc[weekly.index <= last_complete_sunday]
    quality = {
        "join_start": start.date().isoformat(),
        "join_end": boundary.date().isoformat(),
        "weekly_rows": int(len(weekly)),
        "weeks_with_7_weather_days": int((weekly["weather_days"] == 7).sum()),
        "weeks_with_less_than_5_weather_days": int((weekly["weather_days"] < 5).sum()),
        "last_complete_week_ending": weekly.index.max().date().isoformat(),
        "incomplete_crop_weeks_excluded_from_training": int(incomplete_crop_week.sum()),
        "minimum_crop_days_for_training_week": 3,
    }
    return weekly, quality


def build_weekly_crop_only_dataset(crop_daily: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Build weekly crop features when no representative weather mapping exists."""
    boundary = crop_daily.index.max()
    start = crop_daily.index.min()
    weekly = pd.DataFrame(index=crop_daily.resample("W-SUN").size().index)
    weekly["crop_net_kg"] = crop_daily["crop_net_kg"].resample("W-SUN").sum()
    weekly["crop_records"] = crop_daily["crop_records"].resample("W-SUN").sum()
    weekly["crop_days"] = crop_daily["has_crop_records"].resample("W-SUN").sum()
    weekly["weather_days"] = 0

    incomplete_crop_week = weekly["crop_days"] < 3
    weekly.loc[incomplete_crop_week, "crop_net_kg"] = np.nan

    last_complete_sunday = boundary - pd.Timedelta(days=(boundary.weekday() + 1) % 7)
    weekly = weekly.loc[weekly.index <= last_complete_sunday]
    quality = {
        "mode": "crop_only",
        "join_start": start.date().isoformat(),
        "join_end": boundary.date().isoformat(),
        "weekly_rows": int(len(weekly)),
        "weeks_with_7_weather_days": 0,
        "weeks_with_less_than_5_weather_days": int(len(weekly)),
        "last_complete_week_ending": weekly.index.max().date().isoformat(),
        "incomplete_crop_weeks_excluded_from_training": int(incomplete_crop_week.sum()),
        "minimum_crop_days_for_training_week": 3,
    }
    return weekly, quality
