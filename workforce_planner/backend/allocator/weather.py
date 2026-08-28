from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from bisect import bisect_left
import csv
import gzip
import json
import math
import hashlib


WEATHER_FEATURE_COLUMNS = (
    "weather_days_7d",
    "weather_age_days",
    "rain_lag1_mm",
    "rain_lag1_available",
    "rain_7d_mm",
    "rain_days_7d",
    "rain_30d_mm",
    "temp_mean_7d_c",
    "temp_range_7d_c",
    "humidity_mean_7d_pct",
    "wind_mean_7d_kmh",
    "morning_weather_available",
    "morning_temp_mean_c",
    "morning_humidity_mean_pct",
    "morning_rainfall_mm",
    "morning_wind_mean_kmh",
)


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _average(values: list[float], default: float) -> float:
    return sum(values) / len(values) if values else float(default)


@dataclass(frozen=True)
class WeatherFeatureResult:
    values: tuple[float, ...]
    last_observation_date: str | None
    age_days: int
    observed_days_7d: int
    morning_available: bool

    @property
    def operationally_fresh(self) -> bool:
        return self.age_days <= 2 and self.observed_days_7d >= 4 and self.morning_available


def weather_prefix_sha256(path: Path | str, cutoff: str) -> str:
    """Hash deterministic daily rows through a model-training cutoff date."""

    path = Path(path)
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    digest = hashlib.sha256()
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        header = handle.readline()
        digest.update(header.encode("utf-8"))
        for line in handle:
            row_date = line.split(",", 1)[0]
            if row_date <= cutoff:
                digest.update(line.encode("utf-8"))
    return digest.hexdigest()


class WeatherHistory:
    """Daily station history used only through the day before a prediction date."""

    def __init__(self, rows: dict[date, dict[str, float]], metadata: dict[str, Any]):
        self.rows = rows
        self.metadata = metadata
        self._usable_dates = sorted(
            day for day, row in rows.items() if row.get("quality_usable", 0.0) >= 0.5
        )
        self._feature_cache: dict[date, WeatherFeatureResult] = {}
        defaults = metadata.get("feature_defaults") or {}
        self.defaults = {
            "rainfall_mm": float(defaults.get("rainfall_mm", 0.0)),
            "air_temp_mean_c": float(defaults.get("air_temp_mean_c", 18.5)),
            "air_temp_range_c": float(defaults.get("air_temp_range_c", 6.0)),
            "humidity_mean_pct": float(defaults.get("humidity_mean_pct", 85.0)),
            "wind_speed_mean_kmh": float(defaults.get("wind_speed_mean_kmh", 2.0)),
            "morning_air_temp_mean_c": float(defaults.get("morning_air_temp_mean_c", 16.5)),
            "morning_humidity_mean_pct": float(defaults.get("morning_humidity_mean_pct", 95.0)),
            "morning_rainfall_mm": float(defaults.get("morning_rainfall_mm", 0.0)),
            "morning_wind_speed_mean_kmh": float(defaults.get("morning_wind_speed_mean_kmh", 0.5)),
        }

    @classmethod
    def load(cls, daily_path: Path | str, metadata_path: Path | str) -> "WeatherHistory":
        daily_path = Path(daily_path)
        metadata_path = Path(metadata_path)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        opener = gzip.open if daily_path.suffix.lower() == ".gz" else open
        rows: dict[date, dict[str, float]] = {}
        with opener(daily_path, "rt", encoding="utf-8", newline="") as handle:
            for item in csv.DictReader(handle):
                try:
                    day = date.fromisoformat(str(item.get("date")))
                except ValueError:
                    continue
                rows[day] = {
                    name: value
                    for name in (
                        "quality_usable",
                        "rainfall_mm",
                        "air_temp_mean_c",
                        "air_temp_min_c",
                        "air_temp_max_c",
                        "humidity_mean_pct",
                        "wind_speed_mean_kmh",
                        "morning_available",
                        "morning_air_temp_mean_c",
                        "morning_humidity_mean_pct",
                        "morning_rainfall_mm",
                        "morning_wind_speed_mean_kmh",
                    )
                    if (value := _number(item.get(name))) is not None
                }
        if not rows:
            raise ValueError("Weather history contains no valid daily rows")
        return cls(rows, metadata)

    @property
    def date_min(self) -> str:
        return min(self.rows).isoformat()

    @property
    def date_max(self) -> str:
        return max(self.rows).isoformat()

    def features_for_date(self, target: str | date) -> WeatherFeatureResult:
        current = date.fromisoformat(target) if isinstance(target, str) else target
        cached = self._feature_cache.get(current)
        if cached is not None:
            return cached
        position = bisect_left(self._usable_dates, current)
        last_day = self._usable_dates[position - 1] if position else None
        age = min(365, (current - last_day).days) if last_day else 365

        days_7 = [current - timedelta(days=offset) for offset in range(1, 8)]
        days_30 = [current - timedelta(days=offset) for offset in range(1, 31)]
        rows_7 = [
            self.rows[day] for day in days_7
            if day in self.rows and self.rows[day].get("quality_usable", 0.0) >= 0.5
        ]
        rows_30 = [
            self.rows[day] for day in days_30
            if day in self.rows and self.rows[day].get("quality_usable", 0.0) >= 0.5
        ]

        previous = self.rows.get(current - timedelta(days=1), {})
        previous_usable = previous.get("quality_usable", 0.0) >= 0.5
        previous_rain = _number(previous.get("rainfall_mm")) if previous_usable else None
        rain_7 = [
            value for row in rows_7
            if (value := _number(row.get("rainfall_mm"))) is not None
        ]
        rain_30 = [
            value for row in rows_30
            if (value := _number(row.get("rainfall_mm"))) is not None
        ]
        temperatures = [
            value for row in rows_7
            if (value := _number(row.get("air_temp_mean_c"))) is not None
        ]
        temperature_ranges = []
        for row in rows_7:
            minimum = _number(row.get("air_temp_min_c"))
            maximum = _number(row.get("air_temp_max_c"))
            if minimum is not None and maximum is not None and maximum >= minimum:
                temperature_ranges.append(maximum - minimum)
        humidity = [
            value for row in rows_7
            if (value := _number(row.get("humidity_mean_pct"))) is not None
        ]
        wind = [
            value for row in rows_7
            if (value := _number(row.get("wind_speed_mean_kmh"))) is not None
        ]
        current_row = self.rows.get(current, {})
        morning_available = current_row.get("morning_available", 0.0) >= 0.5
        morning_temp = _number(current_row.get("morning_air_temp_mean_c")) if morning_available else None
        morning_humidity = _number(current_row.get("morning_humidity_mean_pct")) if morning_available else None
        morning_rain = _number(current_row.get("morning_rainfall_mm")) if morning_available else None
        morning_wind = _number(current_row.get("morning_wind_speed_mean_kmh")) if morning_available else None

        values = (
            float(len(rows_7)),
            float(age),
            float(previous_rain if previous_rain is not None else self.defaults["rainfall_mm"]),
            float(previous_rain is not None),
            float(sum(rain_7)),
            float(sum(value >= 1.0 for value in rain_7)),
            float(sum(rain_30)),
            _average(temperatures, self.defaults["air_temp_mean_c"]),
            _average(temperature_ranges, self.defaults["air_temp_range_c"]),
            _average(humidity, self.defaults["humidity_mean_pct"]),
            _average(wind, self.defaults["wind_speed_mean_kmh"]),
            float(morning_available),
            float(morning_temp if morning_temp is not None else self.defaults["morning_air_temp_mean_c"]),
            float(morning_humidity if morning_humidity is not None else self.defaults["morning_humidity_mean_pct"]),
            float(morning_rain if morning_rain is not None else self.defaults["morning_rainfall_mm"]),
            float(morning_wind if morning_wind is not None else self.defaults["morning_wind_speed_mean_kmh"]),
        )
        result = WeatherFeatureResult(
            values=values,
            last_observation_date=last_day.isoformat() if last_day else None,
            age_days=age,
            observed_days_7d=len(rows_7),
            morning_available=morning_available,
        )
        self._feature_cache[current] = result
        return result
