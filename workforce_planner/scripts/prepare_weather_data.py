from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.forecast import sha256_file  # noqa: E402
from allocator.weather import weather_prefix_sha256  # noqa: E402


EXPECTED_COLUMNS = (
    "Center",
    "Date Recorded",
    "Time Recorded",
    "Air Temp (C)",
    "Humidity (%)",
    "Rainfall (mm)",
    "Wind Direction (0-359)",
    "Wind Speed (km/h)",
    "Gust Speed (km/h)",
    "UV Level (uw/sq.cm)",
    "Light Level (Lux)",
    "Sunshine Duration",
    "CO2 (0-5000) ppm",
    "Soil Moisture (%)",
    "Soil Temp (C)",
    "Ammonia Level (ppm)",
)


def deterministic_gzip_text(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = path.open("wb")
    compressed = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0)
    return io.TextIOWrapper(compressed, encoding="utf-8", newline="")


def safe_number(value: Any) -> float | None:
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def in_range(value: Any, low: float, high: float) -> float | None:
    result = safe_number(value)
    return result if result is not None and low <= result <= high else None


def median(values: list[float], default: float) -> float:
    values = sorted(values)
    if not values:
        return float(default)
    middle = len(values) // 2
    if len(values) % 2:
        return float(values[middle])
    return float((values[middle - 1] + values[middle]) / 2.0)


def average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def extract_workbooks(source: Path, destination: Path) -> list[Path]:
    if source.is_dir():
        return sorted(source.rglob("*.xlsx"))
    if source.suffix.lower() == ".xlsx":
        return [source]
    if source.suffix.lower() != ".zip":
        raise ValueError("Weather source must be an XLSX workbook, a folder, or a ZIP archive")
    with zipfile.ZipFile(source) as archive:
        members = []
        for item in archive.infolist():
            member = Path(item.filename)
            if item.is_dir() or member.suffix.lower() != ".xlsx":
                continue
            if member.is_absolute() or ".." in member.parts:
                raise ValueError(f"Unsafe path in weather ZIP: {item.filename}")
            archive.extract(item, destination)
            members.append(destination / member)
    return sorted(members)


def read_observations(paths: list[Path]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError("openpyxl is required to read the weather workbooks") from exc

    by_timestamp: dict[str, dict[str, Any]] = {}
    workbook_rows: dict[str, int] = {}
    raw_rows = 0
    for path in paths:
        workbook = load_workbook(path, read_only=True, data_only=True)
        count = 0
        for sheet in workbook.worksheets:
            rows = sheet.iter_rows(values_only=True)
            header = next(rows, None)
            if header is None:
                continue
            columns = tuple(str(value).strip() if value is not None else "" for value in header)
            if columns[: len(EXPECTED_COLUMNS)] != EXPECTED_COLUMNS:
                raise ValueError(f"Unexpected weather columns in {path.name}/{sheet.title}")
            for values in rows:
                item = dict(zip(columns, values))
                day_text = str(item.get("Date Recorded") or "").strip()
                time_text = str(item.get("Time Recorded") or "").strip()
                try:
                    stamp = f"{date.fromisoformat(day_text).isoformat()} {time_text}"
                except ValueError:
                    continue
                raw_rows += 1
                count += 1
                # Sorted paths make the dated update workbook authoritative for exact duplicates.
                by_timestamp[stamp] = item
        workbook_rows[path.name] = count
        workbook.close()
    return by_timestamp, {
        "raw_rows_read": raw_rows,
        "unique_timestamps": len(by_timestamp),
        "duplicate_timestamps_removed": raw_rows - len(by_timestamp),
        "workbook_rows": workbook_rows,
    }


def aggregate_daily(observations: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    from collections import defaultdict
    from datetime import datetime

    grouped: dict[str, list[tuple[datetime, dict[str, Any]]]] = defaultdict(list)
    for stamp, item in observations.items():
        parsed = datetime.fromisoformat(stamp)
        grouped[parsed.date().isoformat()].append((parsed, item))

    invalid = Counter()
    daily_rows = []
    for day, records in sorted(grouped.items()):
        records.sort(key=lambda item: item[0])
        temperatures: list[float] = []
        humidity: list[float] = []
        rainfall: list[float] = []
        wind: list[float] = []
        morning_temperatures: list[float] = []
        morning_humidity: list[float] = []
        morning_rainfall: list[float] = []
        morning_wind: list[float] = []
        morning_count = 0
        for stamp, item in records:
            checks = (
                ("temperature", in_range(item.get("Air Temp (C)"), 5.0, 40.0), temperatures),
                ("humidity", in_range(item.get("Humidity (%)"), 1.0, 100.0), humidity),
                ("rainfall", in_range(item.get("Rainfall (mm)"), 0.0, 150.0), rainfall),
                ("wind", in_range(item.get("Wind Speed (km/h)"), 0.0, 150.0), wind),
            )
            for name, value, target in checks:
                if value is None:
                    invalid[name] += 1
                else:
                    target.append(value)
            if stamp.hour < 6:
                morning_count += 1
                for value, target in (
                    (checks[0][1], morning_temperatures),
                    (checks[1][1], morning_humidity),
                    (checks[2][1], morning_rainfall),
                    (checks[3][1], morning_wind),
                ):
                    if value is not None:
                        target.append(value)
        coverage_hours = (records[-1][0] - records[0][0]).total_seconds() / 3600.0
        usable = len(records) >= 12 and coverage_hours >= 6.0
        row = {
            "date": day,
            "observation_count": len(records),
            "coverage_hours": round(coverage_hours, 3),
            "quality_usable": int(usable),
            "air_temp_mean_c": average(temperatures),
            "air_temp_min_c": min(temperatures) if temperatures else None,
            "air_temp_max_c": max(temperatures) if temperatures else None,
            "humidity_mean_pct": average(humidity),
            # The station rainfall channel is a cumulative counter. Daily maximum is the total.
            "rainfall_mm": max(rainfall) if rainfall else None,
            "wind_speed_mean_kmh": average(wind),
            "wind_speed_max_kmh": max(wind) if wind else None,
            "morning_available": int(morning_count >= 8),
            "morning_observation_count": morning_count,
            "morning_air_temp_mean_c": average(morning_temperatures),
            "morning_humidity_mean_pct": average(morning_humidity),
            "morning_rainfall_mm": max(morning_rainfall) if morning_rainfall else None,
            "morning_wind_speed_mean_kmh": average(morning_wind),
        }
        daily_rows.append(row)
    return daily_rows, dict(invalid)


def write_daily(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = (
        "date",
        "observation_count",
        "coverage_hours",
        "quality_usable",
        "air_temp_mean_c",
        "air_temp_min_c",
        "air_temp_max_c",
        "humidity_mean_pct",
        "rainfall_mm",
        "wind_speed_mean_kmh",
        "wind_speed_max_kmh",
        "morning_available",
        "morning_observation_count",
        "morning_air_temp_mean_c",
        "morning_humidity_mean_pct",
        "morning_rainfall_mm",
        "morning_wind_speed_mean_kmh",
    )
    with deterministic_gzip_text(path) as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                name: "" if row.get(name) is None else (
                    round(float(row[name]), 4) if isinstance(row.get(name), float) else row[name]
                )
                for name in columns
            })


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and aggregate estate weather-station history")
    parser.add_argument("source", type=Path)
    parser.add_argument("--daily", type=Path, default=ROOT / "data" / "weather_daily.csv.gz")
    parser.add_argument("--metadata", type=Path, default=ROOT / "data" / "weather_metadata.json")
    parser.add_argument("--productivity-dataset", type=Path, default=ROOT / "data" / "productivity_training.csv.gz")
    parser.add_argument("--station", default="TRI-TW")
    parser.add_argument("--station-label", default="TRI Thalawakelle")
    args = parser.parse_args()
    source = args.source.resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    source_hash = sha256_file(source) if source.is_file() else None

    with TemporaryDirectory(prefix="tte-weather-") as temporary:
        paths = extract_workbooks(source, Path(temporary))
        if not paths:
            raise ValueError("No XLSX weather workbooks were found")
        observations, read_stats = read_observations(paths)
    rows, invalid_counts = aggregate_daily(observations)
    if not rows:
        raise ValueError("Weather source produced no daily rows")
    write_daily(args.daily, rows)

    usable = [row for row in rows if row["quality_usable"]]
    calendar_days = (date.fromisoformat(rows[-1]["date"]) - date.fromisoformat(rows[0]["date"])).days + 1
    join = None
    if args.productivity_dataset.exists():
        with gzip.open(args.productivity_dataset, "rt", encoding="utf-8", newline="") as handle:
            productivity_dates = {item["date"] for item in csv.DictReader(handle)}
        weather_dates = {row["date"] for row in rows}
        covered = productivity_dates & weather_dates
        join = {
            "clarendon_workdays": len(productivity_dates),
            "weather_covered_workdays": len(covered),
            "workday_join_coverage_pct": round(100.0 * len(covered) / len(productivity_dates), 2),
            "missing_workdays": len(productivity_dates - weather_dates),
        }
        productivity_cutoff = max(productivity_dates)
    else:
        productivity_cutoff = None

    def metric_values(name: str) -> list[float]:
        return [float(row[name]) for row in usable if row.get(name) is not None]

    metadata = {
        "weather_schema_version": 1,
        "station": args.station,
        "station_label": args.station_label,
        "source_name": source.name,
        "source_sha256": source_hash,
        "source_bytes": source.stat().st_size if source.is_file() else None,
        "workbooks": read_stats["workbook_rows"],
        "raw_rows_read": read_stats["raw_rows_read"],
        "unique_timestamps": read_stats["unique_timestamps"],
        "duplicate_timestamps_removed": read_stats["duplicate_timestamps_removed"],
        "date_min": rows[0]["date"],
        "date_max": rows[-1]["date"],
        "calendar_days": calendar_days,
        "observed_days": len(rows),
        "usable_days": len(usable),
        "calendar_day_coverage_pct": round(100.0 * len(rows) / calendar_days, 2),
        "usable_observed_day_pct": round(100.0 * len(usable) / len(rows), 2),
        "invalid_sensor_readings": invalid_counts,
        "daily_file": args.daily.name,
        "daily_sha256": sha256_file(args.daily),
        "training_cutoff": productivity_cutoff,
        "training_prefix_sha256": (
            weather_prefix_sha256(args.daily, productivity_cutoff) if productivity_cutoff else None
        ),
        "daily_aggregation": {
            "deduplication": "Exact timestamps are deduplicated; the June update workbook wins exact overlaps.",
            "rainfall": "The cumulative station rainfall counter is converted to one daily value using its maximum. Readings above 150 mm are rejected as sensor errors.",
            "physical_ranges": {
                "air_temp_c": [5.0, 40.0],
                "humidity_pct": [1.0, 100.0],
                "rainfall_counter_mm": [0.0, 150.0],
                "wind_speed_kmh": [0.0, 150.0],
            },
            "usable_day": "At least 12 readings spanning at least 6 hours.",
        },
        "forecast_rule": (
            "Lag features use dates strictly earlier than the target date. Same-day features use only "
            "station readings timestamped before 06:00 local time."
        ),
        "feature_defaults": {
            "rainfall_mm": 0.0,
            "air_temp_mean_c": round(median(metric_values("air_temp_mean_c"), 18.5), 4),
            "air_temp_range_c": round(median([
                float(row["air_temp_max_c"]) - float(row["air_temp_min_c"])
                for row in usable
                if row.get("air_temp_min_c") is not None and row.get("air_temp_max_c") is not None
            ], 6.0), 4),
            "humidity_mean_pct": round(median(metric_values("humidity_mean_pct"), 85.0), 4),
            "wind_speed_mean_kmh": round(median(metric_values("wind_speed_mean_kmh"), 2.0), 4),
            "morning_air_temp_mean_c": round(median(metric_values("morning_air_temp_mean_c"), 16.5), 4),
            "morning_humidity_mean_pct": round(median(metric_values("morning_humidity_mean_pct"), 95.0), 4),
            "morning_rainfall_mm": 0.0,
            "morning_wind_speed_mean_kmh": round(
                median(metric_values("morning_wind_speed_mean_kmh"), 0.5), 4
            ),
        },
        "clarendon_join": join,
        "limitations": [
            f"{args.station} is a regional station and may not capture every estate field microclimate.",
            "Weather improves productivity prediction only if it wins the untouched temporal test.",
            "A future plan uses the weather model only when observations are recent; otherwise the no-weather model or historical fallback is used.",
        ],
    }
    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    args.metadata.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2))
    print("WEATHER DATA READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
