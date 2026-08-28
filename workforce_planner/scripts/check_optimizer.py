from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.baseline import greedy_allocate
from allocator.data import WorkforceData
from allocator.optimizer import optimize_allocate, optimizer_runtime


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the CP-SAT workforce optimizer")
    parser.add_argument("--profile", type=Path, default=ROOT / "data" / "workforce_profile.json")
    parser.add_argument("--time-limit", type=float, default=5.0)
    args = parser.parse_args()

    runtime = optimizer_runtime()
    if not runtime["available"]:
        print(json.dumps(runtime, indent=2))
        print("OPTIMIZER ERROR: OR-Tools is unavailable.", file=sys.stderr)
        return 1

    data = WorkforceData.load(args.profile)
    scenario = data.create_scenario(
        template_date=data.metadata["default_template_date"],
        attendance_rate=0.90,
        demand_multiplier=1.0,
        same_division_only=True,
        seed=42,
    )
    standard = greedy_allocate(data, scenario)
    optimized = optimize_allocate(
        data,
        scenario,
        time_limit_seconds=args.time_limit,
        warm_start_plan=standard,
    )
    summary = {
        "optimizer": runtime,
        "profile_source_sha256": data.metadata.get("source_sha256"),
        "template_date": scenario.template_date,
        "available_workers": len(scenario.employee_ids),
        "active_fields": len(scenario.demand_kg),
        "standard_coverage_pct": standard["metrics"]["coverage_pct"],
        "optimizer_coverage_pct": optimized["metrics"]["coverage_pct"],
        "improvement_pct_points": round(
            optimized["metrics"]["coverage_pct"] - standard["metrics"]["coverage_pct"],
            2,
        ),
        "constraint_violations": optimized["metrics"]["constraint_violations"],
        "optimization": optimized["optimization"],
    }
    print(json.dumps(summary, indent=2))
    valid = (
        summary["constraint_violations"] == 0
        and summary["optimizer_coverage_pct"] >= summary["standard_coverage_pct"]
    )
    if not valid:
        print("OPTIMIZER ERROR: the optimized plan failed its safety comparison.", file=sys.stderr)
        return 1
    print("OPTIMIZER READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

