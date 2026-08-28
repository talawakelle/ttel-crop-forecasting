from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.data import WorkforceData


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the merged estate crop forecast")
    parser.add_argument("--planning-date")
    parser.add_argument("--require-current", action="store_true")
    args = parser.parse_args()
    data = WorkforceData.load(ROOT / "data" / "workforce_profile.json")
    status = data.configure_crop_forecaster(ROOT / "data" / "crop_forecast_clarendon.json")
    if args.planning_date:
        status = data.crop_forecast_status(args.planning_date)
    print(json.dumps(status, indent=2))
    if not status.get("ready"):
        raise SystemExit("Crop forecast is not readable")
    if args.require_current and not status.get("eligible_today"):
        raise SystemExit("Crop forecast is loaded but does not cover today. Import a refreshed workbook.")
    if args.planning_date and not status.get("eligible_for_planning_date"):
        raise SystemExit(f"Crop forecast does not cover {args.planning_date}")


if __name__ == "__main__":
    main()
