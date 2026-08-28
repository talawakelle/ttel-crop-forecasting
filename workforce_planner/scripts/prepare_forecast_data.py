from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import groupby
from pathlib import Path
from typing import Any
import argparse
import csv
import gzip
import io
import json
import math
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.forecast import (  # noqa: E402
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    FEATURE_SCHEMA_VERSION,
    PREDICTION_MAX_KG,
    sha256_file,
)
from allocator.weather import WeatherHistory, weather_prefix_sha256  # noqa: E402
from prepare_data import anonymous_aliases, load_source_rows  # noqa: E402


EWMA_ALPHA = 0.15


@dataclass
class RunningStat:
    count: int = 0
    total: float = 0.0
    ewma: float = 0.0
    last_date: str | None = None

    def mean(self, default: float) -> float:
        return self.total / self.count if self.count else float(default)

    def ewma_value(self, default: float) -> float:
        return self.ewma if self.count else float(default)

    def update(self, value: float, record_date: str) -> None:
        value = float(value)
        self.ewma = value if self.count == 0 else EWMA_ALPHA * value + (1.0 - EWMA_ALPHA) * self.ewma
        self.count += 1
        self.total += value
        self.last_date = record_date

    def export(self, default: float = 10.0) -> dict[str, Any]:
        return {
            "count": self.count,
            "mean_kg": round(self.mean(default), 6),
            "ewma_kg": round(self.ewma_value(default), 6),
            "last_date": self.last_date,
        }


def deterministic_gzip_text(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = path.open("wb")
    compressed = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0)
    return io.TextIOWrapper(compressed, encoding="utf-8", newline="")


def days_since(last_value: str | None, current: date, default: float = 365.0) -> float:
    if not last_value:
        return default
    return max(0.0, min(730.0, float((current - date.fromisoformat(last_value)).days)))


def mode_division(counts: Counter[str]) -> str:
    if not counts:
        return "UNK"
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def split_name(record_date: str, train_end: str, validation_end: str) -> str:
    if record_date <= train_end:
        return "train"
    if record_date <= validation_end:
        return "validation"
    return "test"


def make_feature_values(
    *,
    employee_id: str,
    field_id: str,
    field_division: str,
    record_date: str,
    date_min: str,
    global_stat: RunningStat,
    employee_stat: RunningStat,
    pair_stat: RunningStat,
    division_stat: RunningStat,
    field_stat: RunningStat,
    home_division: str,
    weather_history: WeatherHistory,
) -> tuple[list[Any], float]:
    current = date.fromisoformat(record_date)
    start = date.fromisoformat(date_min)
    global_mean = global_stat.mean(10.0)
    employee_mean = employee_stat.mean(global_mean)
    employee_ewma = employee_stat.ewma_value(employee_mean)
    pair_mean = pair_stat.mean(employee_mean)
    pair_ewma = pair_stat.ewma_value(pair_mean)
    division_mean = division_stat.mean(employee_mean)
    division_ewma = division_stat.ewma_value(division_mean)
    field_mean = field_stat.mean(global_mean)
    field_ewma = field_stat.ewma_value(field_mean)
    day_of_year = current.timetuple().tm_yday
    angle = 2.0 * math.pi * day_of_year / 365.25
    cross_division = home_division not in {"UNK", field_division}

    values = [
        employee_id,
        field_id,
        home_division,
        field_division,
        float(current.month),
        float(current.weekday()),
        math.sin(angle),
        math.cos(angle),
        max(0.0, (current - start).days / 365.25),
        float(cross_division),
        math.log1p(employee_stat.count),
        employee_mean,
        employee_ewma,
        math.log1p(pair_stat.count),
        pair_mean,
        pair_ewma,
        math.log1p(division_stat.count),
        division_mean,
        division_ewma,
        math.log1p(field_stat.count),
        field_mean,
        field_ewma,
        days_since(employee_stat.last_date, current),
        days_since(pair_stat.last_date, current),
    ]
    values.extend(weather_history.features_for_date(current).values)

    if division_stat.count:
        division_value = (
            division_stat.count * division_mean + 3.0 * employee_mean
        ) / (division_stat.count + 3.0)
    else:
        division_value = employee_mean * (0.82 if cross_division else 1.0)
    if pair_stat.count:
        baseline = (pair_stat.count * pair_mean + 4.0 * division_value) / (pair_stat.count + 4.0)
    else:
        baseline = division_value * 0.92
    if cross_division:
        baseline *= 0.88
    return values, max(0.5, min(PREDICTION_MAX_KG, baseline))


def build_forecast_dataset(
    source: Path,
    dataset_path: Path,
    state_path: Path,
    metadata_path: Path,
    *,
    train_end: str,
    validation_end: str,
    target_cap_kg: float,
    weather_daily_path: Path,
    weather_metadata_path: Path,
) -> dict[str, Any]:
    weather_history = WeatherHistory.load(weather_daily_path, weather_metadata_path)
    weather_metadata = json.loads(weather_metadata_path.read_text(encoding="utf-8"))
    if weather_metadata.get("daily_sha256") != sha256_file(weather_daily_path):
        raise ValueError("Weather metadata does not match the prepared daily file")
    raw_rows, source_metadata = load_source_rows(source)
    if not raw_rows:
        raise ValueError("The source produced no usable plucking records")
    aliases = anonymous_aliases({row[0] for row in raw_rows})
    aggregated: dict[tuple[str, str, str, str], float] = defaultdict(float)
    for employee_key, record_date, division, field_id, _code, _home, kilos, _work in raw_rows:
        aggregated[(record_date, aliases[employee_key], division, field_id)] += float(kilos)
    del raw_rows, aliases
    records = sorted((*key, kilos) for key, kilos in aggregated.items())
    del aggregated
    date_min = records[0][0]
    date_max = records[-1][0]
    if not (date_min <= train_end < validation_end < date_max):
        raise ValueError(
            f"Invalid temporal split for data range {date_min} to {date_max}: "
            f"train_end={train_end}, validation_end={validation_end}"
        )

    global_stat = RunningStat()
    employee_stats: dict[str, RunningStat] = defaultdict(RunningStat)
    pair_stats: dict[tuple[str, str], RunningStat] = defaultdict(RunningStat)
    division_stats: dict[tuple[str, str], RunningStat] = defaultdict(RunningStat)
    field_stats: dict[str, RunningStat] = defaultdict(RunningStat)
    employee_division_counts: dict[str, Counter[str]] = defaultdict(Counter)
    split_counts: Counter[str] = Counter()
    clipped_high = 0
    target_total = 0.0

    headers = ["date", "split", *FEATURE_COLUMNS, "baseline_prediction_kg", "target_kg"]
    with deterministic_gzip_text(dataset_path) as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(headers)
        for record_date, day_group in groupby(records, key=lambda item: item[0]):
            day_rows = list(day_group)
            prepared = []
            for _day, employee_id, division, field_id, raw_target in day_rows:
                home_division = mode_division(employee_division_counts[employee_id])
                features, baseline = make_feature_values(
                    employee_id=employee_id,
                    field_id=field_id,
                    field_division=division,
                    record_date=record_date,
                    date_min=date_min,
                    global_stat=global_stat,
                    employee_stat=employee_stats[employee_id],
                    pair_stat=pair_stats[(employee_id, field_id)],
                    division_stat=division_stats[(employee_id, division)],
                    field_stat=field_stats[field_id],
                    home_division=home_division,
                    weather_history=weather_history,
                )
                target = max(0.5, min(float(target_cap_kg), float(raw_target)))
                clipped_high += int(raw_target > target_cap_kg)
                split = split_name(record_date, train_end, validation_end)
                split_counts[split] += 1
                target_total += target
                writer.writerow([
                    record_date,
                    split,
                    *(
                        value if name in CATEGORICAL_FEATURES else round(float(value), 6)
                        for name, value in zip(FEATURE_COLUMNS, features)
                    ),
                    round(baseline, 6),
                    round(target, 6),
                ])
                prepared.append((employee_id, division, field_id, target))

            # Update only after every row for the date was featurized. This is the
            # core leakage barrier: no row can use its own target or a same-day target.
            for employee_id, division, field_id, target in prepared:
                global_stat.update(target, record_date)
                employee_stats[employee_id].update(target, record_date)
                pair_stats[(employee_id, field_id)].update(target, record_date)
                division_stats[(employee_id, division)].update(target, record_date)
                field_stats[field_id].update(target, record_date)
                employee_division_counts[employee_id][division] += 1

    state = {
        "metadata": {
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "source_name": source_metadata["source_name"],
            "source_sha256": source_metadata["source_sha256"],
            "date_min": date_min,
            "state_as_of": date_max,
            "target_cap_kg": target_cap_kg,
            "feature_columns": list(FEATURE_COLUMNS),
            "weather_daily_sha256": sha256_file(weather_daily_path),
            "weather_source_sha256": weather_metadata.get("source_sha256"),
            "weather_date_max": weather_metadata.get("date_max"),
            "weather_training_cutoff": date_max,
            "weather_training_sha256": weather_prefix_sha256(weather_daily_path, date_max),
            "privacy": (
                "Only deterministic employee aliases, field codes and aggregated historical statistics are stored. "
                "Names, EPF numbers, source employee identifiers and the alias map are excluded."
            ),
        },
        "global": global_stat.export(),
        "employees": {
            employee_id: {
                **stat.export(global_stat.mean(10.0)),
                "home_division": mode_division(employee_division_counts[employee_id]),
            }
            for employee_id, stat in sorted(employee_stats.items())
        },
        "employee_fields": {
            employee_id: {
                field_id: pair_stats[(employee_id, field_id)].export(employee_stats[employee_id].mean(10.0))
                for pair_employee, field_id in sorted(pair_stats)
                if pair_employee == employee_id
            }
            for employee_id in sorted(employee_stats)
        },
        "employee_divisions": {
            employee_id: {
                division: division_stats[(employee_id, division)].export(employee_stats[employee_id].mean(10.0))
                for pair_employee, division in sorted(division_stats)
                if pair_employee == employee_id
            }
            for employee_id in sorted(employee_stats)
        },
        "fields": {
            field_id: stat.export(global_stat.mean(10.0))
            for field_id, stat in sorted(field_stats.items())
        },
    }
    with deterministic_gzip_text(state_path) as handle:
        json.dump(state, handle, sort_keys=True, separators=(",", ":"))

    metadata = {
        "dataset_schema_version": 1,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "source_name": source_metadata["source_name"],
        "source_kind": source_metadata["source_kind"],
        "source_sha256": source_metadata["source_sha256"],
        "source_rows_scanned": source_metadata["source_rows_scanned"],
        "source_rows_used": source_metadata["source_rows_used"],
        "aggregated_employee_field_day_rows": len(records),
        "date_min": date_min,
        "date_max": date_max,
        "train_end": train_end,
        "validation_start": (date.fromisoformat(train_end) + timedelta(days=1)).isoformat(),
        "validation_end": validation_end,
        "test_start": (date.fromisoformat(validation_end) + timedelta(days=1)).isoformat(),
        "split_rows": dict(sorted(split_counts.items())),
        "target_cap_kg": target_cap_kg,
        "targets_clipped_above_cap": clipped_high,
        "clipped_target_total_kg": round(target_total, 3),
        "feature_columns": list(FEATURE_COLUMNS),
        "categorical_features": list(CATEGORICAL_FEATURES),
        "weather_daily_file": weather_daily_path.name,
        "weather_daily_sha256": sha256_file(weather_daily_path),
        "weather_metadata_file": weather_metadata_path.name,
        "weather_metadata_sha256": sha256_file(weather_metadata_path),
        "weather_source_name": weather_metadata.get("source_name"),
        "weather_source_sha256": weather_metadata.get("source_sha256"),
        "weather_date_min": weather_metadata.get("date_min"),
        "weather_date_max": weather_metadata.get("date_max"),
        "weather_training_cutoff": date_max,
        "weather_training_sha256": weather_prefix_sha256(weather_daily_path, date_max),
        "weather_join": weather_metadata.get("clarendon_join"),
        "dataset_file": dataset_path.name,
        "dataset_sha256": sha256_file(dataset_path),
        "state_file": state_path.name,
        "state_sha256": sha256_file(state_path),
        "leakage_control": (
            "Rows are ordered by date. Productivity features for a workday use only earlier workdays; "
            "all productivity-state updates occur after every row for that day is written. Weather "
            "lag features use station dates strictly earlier than the target date; same-day weather features "
            "use only station readings timestamped before 06:00 local time."
        ),
        "privacy": state["metadata"]["privacy"],
    }
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="Build privacy-safe, leakage-controlled forecast features")
    parser.add_argument("source", type=Path)
    parser.add_argument("--dataset", type=Path, default=ROOT / "data" / "productivity_training.csv.gz")
    parser.add_argument("--state", type=Path, default=ROOT / "data" / "productivity_state.json.gz")
    parser.add_argument("--metadata", type=Path, default=ROOT / "data" / "productivity_dataset_metadata.json")
    parser.add_argument("--train-end", default="2025-12-31")
    parser.add_argument("--validation-end", default="2026-03-31")
    parser.add_argument("--target-cap-kg", type=float, default=PREDICTION_MAX_KG)
    parser.add_argument("--weather-daily", type=Path, default=ROOT / "data" / "weather_daily.csv.gz")
    parser.add_argument("--weather-metadata", type=Path, default=ROOT / "data" / "weather_metadata.json")
    args = parser.parse_args()
    metadata = build_forecast_dataset(
        args.source,
        args.dataset,
        args.state,
        args.metadata,
        train_end=args.train_end,
        validation_end=args.validation_end,
        target_cap_kg=args.target_cap_kg,
        weather_daily_path=args.weather_daily,
        weather_metadata_path=args.weather_metadata,
    )
    print(json.dumps(metadata, indent=2))
    print("FORECAST DATA READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
