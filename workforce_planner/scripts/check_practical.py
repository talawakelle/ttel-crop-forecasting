from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import argparse
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.baseline import greedy_allocate
from allocator.data import WorkforceData
from allocator.optimizer import optimize_allocate, optimizer_available
from allocator.practical import build_practical_plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the v1.0 practical morning planner")
    parser.add_argument("--additional-workers", type=int, default=10)
    parser.add_argument("--max-transfers", type=int, default=40)
    parser.add_argument("--goal", type=float, default=85.0)
    parser.add_argument("--time-limit", type=float, default=10.0)
    args = parser.parse_args()
    if not optimizer_available():
        print(json.dumps({"ready": False, "error": "OR-Tools CP-SAT is unavailable"}, indent=2))
        return 1

    data = WorkforceData.load(ROOT / "data" / "workforce_profile.json")
    planning_date = (
        date.fromisoformat(data.metadata["date_max"]) + timedelta(days=1)
    ).isoformat()
    scenario = data.create_scenario(
        template_date=data.metadata["default_template_date"],
        planning_date=planning_date,
        attendance_rate=0.9,
        demand_multiplier=1.0,
        same_division_only=True,
        seed=42,
    )
    warm = greedy_allocate(data, scenario)
    current = optimize_allocate(
        data,
        scenario,
        time_limit_seconds=5,
        warm_start_plan=warm,
    )
    result = build_practical_plan(
        data,
        scenario,
        current,
        max_additional_workers=args.additional_workers,
        max_cross_division_assignments=args.max_transfers,
        goal_coverage_pct=args.goal,
        time_limit_seconds=args.time_limit,
    )
    summary = {
        key: result.get(key)
        for key in (
            "ready",
            "status",
            "goal_coverage_pct",
            "current_coverage_pct",
            "coverage_pct",
            "improvement_pct_points",
            "goal_reached",
            "gap_to_goal_pct_points",
            "baseline_expected_workers",
            "template_day_worker_pool",
            "requested_additional_worker_limit",
            "additional_workers_used",
            "requested_transfer_limit",
            "transfers_used",
            "constraint_violations",
            "optimality_proven",
            "coverage_upper_bound_pct",
            "solve_seconds",
        )
    }
    summary["additional_employee_ids"] = [
        item["employee_id"] for item in result.get("additional_workers", [])
    ]
    print(json.dumps(summary, indent=2))
    if not result.get("ready"):
        return 1
    if result["constraint_violations"] != 0:
        return 1
    if result["additional_workers_used"] > max(0, args.additional_workers):
        return 1
    if result["transfers_used"] > max(0, args.max_transfers):
        return 1
    print("PRACTICAL OPERATIONS PLANNER READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
