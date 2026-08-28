from __future__ import annotations

from pathlib import Path
import argparse
import json
import statistics
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.baseline import greedy_allocate
from allocator.data import WorkforceData
from allocator.frontier import build_coverage_frontier
from allocator.optimizer import optimize_allocate, optimizer_available


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark coverage-improvement operating levers")
    parser.add_argument("--episodes", type=int, default=40)
    parser.add_argument("--seed", type=int, default=1042)
    parser.add_argument("--time-limit", type=float, default=3.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "models" / "coverage_frontier_benchmark.json",
    )
    args = parser.parse_args()
    if not optimizer_available():
        raise RuntimeError("OR-Tools CP-SAT is unavailable")
    if not 1 <= args.episodes <= 100:
        raise ValueError("episodes must be between 1 and 100")

    data = WorkforceData.load(ROOT / "data" / "workforce_profile.json")
    dates = data.complete_dates
    rows = []
    started = time.perf_counter()
    for episode in range(args.episodes):
        date_index = (
            len(dates) - 1
            if args.episodes == 1
            else round(episode * (len(dates) - 1) / (args.episodes - 1))
        )
        scenario = data.create_scenario(
            template_date=dates[date_index],
            planning_date="2026-06-16",
            attendance_rate=0.72 + (episode % 8) * 0.04,
            demand_multiplier=0.85 + (episode % 7) * 0.05,
            same_division_only=episode % 4 != 0,
            seed=args.seed + episode,
        )
        warm = greedy_allocate(data, scenario)
        current = optimize_allocate(
            data,
            scenario,
            time_limit_seconds=args.time_limit,
            warm_start_plan=warm,
        )
        frontier = build_coverage_frontier(
            data,
            scenario,
            current,
            time_limit_seconds=args.time_limit,
        )
        if not frontier["ready"]:
            raise RuntimeError(frontier["error"])
        options = {item["name"]: item for item in frontier["options"]}
        rows.append({
            "episode": episode + 1,
            "template_date": scenario.template_date,
            "attendance_rate": scenario.attendance_rate,
            "demand_multiplier": scenario.demand_multiplier,
            "same_division_only": scenario.same_division_only,
            "options": options,
        })
        print(
            f"[{episode + 1:02d}/{args.episodes:02d}] "
            f"current {options['current']['coverage_pct']:.1f}% · "
            f"divisions {options['flexible_divisions']['coverage_pct']:.1f}% · "
            f"attendance {options['full_attendance']['coverage_pct']:.1f}% · "
            f"combined {options['full_attendance_flexible']['coverage_pct']:.1f}%",
            flush=True,
        )

    names = ("current", "flexible_divisions", "full_attendance", "full_attendance_flexible")
    strict_mean = statistics.mean(row["options"]["current"]["coverage_pct"] for row in rows)
    summary = {}
    for name in names:
        values = [float(row["options"][name]["coverage_pct"]) for row in rows]
        summary[name] = {
            "mean_coverage_pct": round(statistics.mean(values), 2),
            "improvement_over_current_points": round(statistics.mean(values) - strict_mean, 2),
            "scenarios_at_or_above_85_pct": sum(value >= 85.0 for value in values),
            "optimality_proven_scenarios": sum(
                bool(row["options"][name]["optimality_proven"]) for row in rows
            ),
            "constraint_violations": sum(
                int(row["options"][name]["constraint_violations"]) for row in rows
            ),
        }
    report = {
        "evaluation_episodes": args.episodes,
        "evaluation_seed": args.seed,
        "prediction_method": "historical median fallback for reproducible reference",
        "evaluation_scope": (
            "fixed counterfactual scenarios sampled evenly across complete historical workdays "
            f"from {dates[0]} to {dates[-1]}"
        ),
        "summary": summary,
        "rows": rows,
        "benchmark_seconds": round(time.perf_counter() - started, 2),
        "profile_source_sha256": data.metadata.get("source_sha256"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Benchmark saved to {args.output}")
    return 0 if all(item["constraint_violations"] == 0 for item in summary.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
