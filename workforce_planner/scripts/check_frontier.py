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
from allocator.frontier import build_coverage_frontier
from allocator.optimizer import optimize_allocate, optimizer_available


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the v0.9 coverage frontier")
    parser.add_argument("--time-limit", type=float, default=3.0)
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
        time_limit_seconds=max(1.0, args.time_limit),
        warm_start_plan=warm,
    )
    frontier = build_coverage_frontier(
        data,
        scenario,
        current,
        time_limit_seconds=args.time_limit,
    )
    result = {
        "ready": frontier["ready"],
        "current_coverage_pct": frontier.get("current_coverage_pct"),
        "best_option": frontier.get("best_option"),
        "best_coverage_pct": frontier.get("best_coverage_pct"),
        "best_improvement_pct_points": frontier.get("best_improvement_pct_points"),
        "options": frontier.get("options", []),
        "best_plan_constraint_violations": (
            frontier.get("best_plan", {}).get("metrics", {}).get("constraint_violations")
            if frontier.get("best_plan") else None
        ),
    }
    print(json.dumps(result, indent=2))
    if not result["ready"] or result["best_plan_constraint_violations"] != 0:
        return 1
    if result["best_coverage_pct"] < result["current_coverage_pct"]:
        return 1
    print("COVERAGE FRONTIER READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
