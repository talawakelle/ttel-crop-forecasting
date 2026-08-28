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
from allocator.goal import analyze_coverage_goal
from allocator.optimizer import optimize_allocate, optimizer_available


def parse_args():
    parser = argparse.ArgumentParser(description="Validate the 85% coverage-goal planner")
    parser.add_argument("--goal", type=float, default=85.0)
    parser.add_argument("--time-limit", type=float, default=3.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not optimizer_available():
        print(json.dumps({"ready": False, "error": "OR-Tools CP-SAT is unavailable"}, indent=2))
        return 1
    data = WorkforceData.load(ROOT / "data" / "workforce_profile.json")
    planning_date = (date.fromisoformat(data.metadata["date_max"]) + timedelta(days=1)).isoformat()
    scenario = data.create_scenario(
        template_date=data.metadata["default_template_date"],
        planning_date=planning_date,
        attendance_rate=0.9,
        demand_multiplier=1.0,
        same_division_only=True,
        seed=42,
    )
    standard = greedy_allocate(data, scenario)
    optimized = optimize_allocate(
        data,
        scenario,
        time_limit_seconds=max(1.0, args.time_limit),
        warm_start_plan=standard,
    )
    goal = analyze_coverage_goal(
        data,
        scenario,
        optimized,
        goal_coverage_pct=args.goal,
        time_limit_seconds=args.time_limit,
    )
    result = {
        "ready": goal["status"] != "analysis_unavailable",
        "goal_coverage_pct": goal["goal_coverage_pct"],
        "current_coverage_pct": goal["current_coverage_pct"],
        "status": goal["status"],
        "minimum_additional_workers": goal.get("minimum_additional_workers"),
        "minimum_additional_workers_proven": goal.get("minimum_additional_workers_proven"),
        "required_attendance_pct": goal.get("required_attendance_pct"),
        "cross_division_required": goal.get("cross_division_required"),
        "goal_plan_constraint_violations": (
            goal.get("goal_plan", {}).get("metrics", {}).get("constraint_violations")
            if goal.get("goal_plan") else None
        ),
    }
    print(json.dumps(result, indent=2))
    valid_statuses = {
        "goal_met",
        "more_attendance_needed",
        "cross_division_needed",
        "capacity_gap",
    }
    if result["status"] not in valid_statuses:
        return 1
    if result["goal_plan_constraint_violations"] not in {None, 0}:
        return 1
    print("COVERAGE GOAL PLANNER READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
