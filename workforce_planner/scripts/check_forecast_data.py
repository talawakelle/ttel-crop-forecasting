from __future__ import annotations

from pathlib import Path
import argparse
import csv
import gzip
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.forecast import FEATURE_COLUMNS, FEATURE_SCHEMA_VERSION, read_json, sha256_file  # noqa: E402
from allocator.weather import weather_prefix_sha256  # noqa: E402


FORBIDDEN_COLUMNS = {
    "employee_name",
    "employee_no",
    "employee_number",
    "employee_id_source",
    "epf",
    "nic",
    "gender",
    "image_name",
    "alias_map",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate privacy-safe forecast training files")
    parser.add_argument("--dataset", type=Path, default=ROOT / "data" / "productivity_training.csv.gz")
    parser.add_argument("--state", type=Path, default=ROOT / "data" / "productivity_state.json.gz")
    parser.add_argument("--metadata", type=Path, default=ROOT / "data" / "productivity_dataset_metadata.json")
    parser.add_argument("--profile", type=Path, default=ROOT / "data" / "workforce_profile.json")
    parser.add_argument("--weather-daily", type=Path, default=ROOT / "data" / "weather_daily.csv.gz")
    parser.add_argument("--weather-metadata", type=Path, default=ROOT / "data" / "weather_metadata.json")
    args = parser.parse_args()
    for path in (
        args.dataset,
        args.state,
        args.metadata,
        args.profile,
        args.weather_daily,
        args.weather_metadata,
    ):
        if not path.exists():
            raise FileNotFoundError(f"Required file is missing: {path}")
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    state = read_json(args.state)
    weather_metadata = json.loads(args.weather_metadata.read_text(encoding="utf-8"))
    expected = profile["metadata"].get("source_sha256")
    checks = {
        "profile_fingerprint_matches": bool(expected and metadata.get("source_sha256") == expected),
        "state_fingerprint_matches": state.get("metadata", {}).get("source_sha256") == expected,
        "dataset_hash_matches": metadata.get("dataset_sha256") == sha256_file(args.dataset),
        "state_hash_matches": metadata.get("state_sha256") == sha256_file(args.state),
        "feature_schema_matches": metadata.get("feature_schema_version") == FEATURE_SCHEMA_VERSION,
        "feature_columns_match": metadata.get("feature_columns") == list(FEATURE_COLUMNS),
        "weather_training_prefix_matches": metadata.get("weather_training_sha256") == weather_prefix_sha256(
            args.weather_daily, metadata.get("weather_training_cutoff") or metadata.get("date_max")
        ),
        "weather_internal_hash_matches": weather_metadata.get("daily_sha256") == sha256_file(args.weather_daily),
        "weather_pre_shift_rule_present": "before 06:00" in metadata.get("leakage_control", ""),
    }
    with gzip.open(args.dataset, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        first_rows = [next(reader, None) for _ in range(20)]
    normalized = {value.strip().lower() for value in header}
    checks["forbidden_columns_absent"] = normalized.isdisjoint(FORBIDDEN_COLUMNS)
    employee_index = header.index("employee_id")
    checks["employee_ids_are_aliases"] = all(
        row is not None and row[employee_index].startswith("EMP-")
        for row in first_rows
    )
    checks["split_rows_reconcile"] = sum(metadata.get("split_rows", {}).values()) == metadata.get(
        "aggregated_employee_field_day_rows"
    )
    result = {
        "ready": all(checks.values()),
        "checks": checks,
        "source_sha256": expected,
        "date_min": metadata.get("date_min"),
        "date_max": metadata.get("date_max"),
        "rows": metadata.get("aggregated_employee_field_day_rows"),
        "split_rows": metadata.get("split_rows"),
        "targets_clipped_above_cap": metadata.get("targets_clipped_above_cap"),
        "dataset_mb": round(args.dataset.stat().st_size / 1024 / 1024, 2),
        "state_mb": round(args.state.stat().st_size / 1024 / 1024, 2),
        "weather_station": weather_metadata.get("station_label"),
        "weather_date_min": weather_metadata.get("date_min"),
        "weather_date_max": weather_metadata.get("date_max"),
        "weather_workday_join_coverage_pct": (weather_metadata.get("clarendon_join") or {}).get(
            "workday_join_coverage_pct"
        ),
        "weather_daily_mb": round(args.weather_daily.stat().st_size / 1024 / 1024, 2),
    }
    print(json.dumps(result, indent=2))
    print("FORECAST DATA READY" if result["ready"] else "FORECAST DATA INVALID")
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
