from __future__ import annotations

from pathlib import Path
import argparse
import csv
import gzip
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.forecast import sha256_file  # noqa: E402
from allocator.weather import WEATHER_FEATURE_COLUMNS, WeatherHistory  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate prepared TRI-TW daily weather history")
    parser.add_argument("--daily", type=Path, default=ROOT / "data" / "weather_daily.csv.gz")
    parser.add_argument("--metadata", type=Path, default=ROOT / "data" / "weather_metadata.json")
    args = parser.parse_args()
    for path in (args.daily, args.metadata):
        if not path.exists():
            raise FileNotFoundError(path)
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    history = WeatherHistory.load(args.daily, args.metadata)
    with gzip.open(args.daily, "rt", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    dates = [row["date"] for row in rows]
    probe = history.features_for_date("2026-06-16")
    checks = {
        "daily_hash_matches": metadata.get("daily_sha256") == sha256_file(args.daily),
        "station_is_tri_tw": metadata.get("station") == "TRI-TW",
        "dates_are_sorted_unique": dates == sorted(set(dates)),
        "row_count_matches": len(rows) == metadata.get("observed_days"),
        "date_range_matches": bool(dates and dates[0] == metadata.get("date_min") and dates[-1] == metadata.get("date_max")),
        "source_fingerprint_present": bool(metadata.get("source_sha256")),
        "feature_count_matches": len(probe.values) == len(WEATHER_FEATURE_COLUMNS),
        "strict_past_probe": probe.last_observation_date is None or probe.last_observation_date < "2026-06-16",
    }
    result = {
        "ready": all(checks.values()),
        "checks": checks,
        "station": metadata.get("station_label"),
        "source_name": metadata.get("source_name"),
        "source_sha256": metadata.get("source_sha256"),
        "date_min": metadata.get("date_min"),
        "date_max": metadata.get("date_max"),
        "raw_rows_read": metadata.get("raw_rows_read"),
        "unique_timestamps": metadata.get("unique_timestamps"),
        "duplicate_timestamps_removed": metadata.get("duplicate_timestamps_removed"),
        "observed_days": metadata.get("observed_days"),
        "usable_days": metadata.get("usable_days"),
        "clarendon_join": metadata.get("clarendon_join"),
        "invalid_sensor_readings": metadata.get("invalid_sensor_readings"),
    }
    print(json.dumps(result, indent=2))
    print("WEATHER DATA READY" if result["ready"] else "WEATHER DATA INVALID")
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
