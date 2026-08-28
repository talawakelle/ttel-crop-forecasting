from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import argparse
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.data import WorkforceData  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the approved productivity forecast")
    parser.add_argument("--profile", type=Path, default=ROOT / "data" / "workforce_profile.json")
    parser.add_argument("--model", type=Path, default=ROOT / "models" / "productivity_catboost.cbm")
    parser.add_argument("--metrics", type=Path, default=ROOT / "models" / "productivity_metrics.json")
    parser.add_argument("--state", type=Path, default=ROOT / "data" / "productivity_state.json.gz")
    parser.add_argument("--planning-date")
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    data = WorkforceData.load(args.profile)
    data.configure_forecaster(
        model_path=args.model,
        metadata_path=args.metrics,
        state_path=args.state,
    )
    planning_date = args.planning_date or (
        date.fromisoformat(data.metadata["date_max"]) + timedelta(days=1)
    ).isoformat()
    status = data.forecast_status(planning_date)
    if status["ready"]:
        employee_id = data.employees[0].id
        field_id = data.fields[0].id
        prediction = data.predict_kg(employee_id, field_id, planning_date)
        status["smoke_prediction"] = {
            "employee_id": employee_id,
            "field_id": field_id,
            "predicted_kg": prediction,
        }
        status["prediction_in_range"] = 0.5 <= prediction <= 45.0
    print(json.dumps(status, indent=2))
    if status["ready"] and status.get("prediction_in_range"):
        print("FORECAST MODEL READY")
        return 0
    print("FORECAST MODEL NOT ACTIVE; HISTORICAL MEDIAN FALLBACK IS SAFE")
    return 1 if args.require_ready else 0


if __name__ == "__main__":
    raise SystemExit(main())
