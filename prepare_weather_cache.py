from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.pipeline import load_weather_daily_many


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare one reusable daily weather cache")
    parser.add_argument("--weather", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    daily, quality = load_weather_daily_many(args.weather)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    daily.to_csv(args.output, index_label="date")
    quality_path = args.output.with_suffix(".quality.json")
    quality_path.write_text(json.dumps(quality, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "output": str(args.output.resolve()),
        "quality": str(quality_path.resolve()),
        "date_min": quality["date_min"],
        "date_max": quality["date_max"],
        "observed_days": quality["observed_days"],
        "centers": quality.get("center_codes", []),
    }, indent=2))


if __name__ == "__main__":
    main()

