from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path
import argparse
import json
import statistics
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.data import WorkforceData
from allocator.hybrid import build_candidate_plans
from allocator.version import MODEL_SCHEMA_VERSION


def compatible_model(profile: dict, model_path: Path) -> tuple[Path | None, str | None]:
    metrics_path = model_path.with_name("training_metrics.json")
    if not model_path.exists() or not metrics_path.exists():
        return None, "model or training_metrics.json is missing"
    try:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"training metadata cannot be read: {type(exc).__name__}"
    if metrics.get("profile_source_sha256") != profile["metadata"].get("source_sha256"):
        return None, "model profile fingerprint does not match"
    if metrics.get("model_schema_version") != MODEL_SCHEMA_VERSION:
        return None, "model schema version does not match"
    if metrics.get("rl_constraint_violations") != 0:
        return None, "model failed its constraint evaluation"
    return model_path, None


def mean_or_none(values: list[float]) -> float | None:
    return round(statistics.mean(values), 2) if values else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark hybrid, optimizer, RL and standard allocation")
    parser.add_argument("--episodes", type=int, default=40)
    parser.add_argument("--seed", type=int, default=1042)
    parser.add_argument("--time-limit", type=float, default=5.0)
    parser.add_argument("--profile", type=Path, default=ROOT / "data" / "workforce_profile.json")
    parser.add_argument("--model", type=Path, default=ROOT / "models" / "maskable_ppo_allocator.zip")
    parser.add_argument("--forecast-model", type=Path, default=ROOT / "models" / "productivity_catboost.cbm")
    parser.add_argument("--forecast-metrics", type=Path, default=ROOT / "models" / "productivity_metrics.json")
    parser.add_argument("--forecast-state", type=Path, default=ROOT / "data" / "productivity_state.json.gz")
    parser.add_argument("--planning-date", default=date.today().isoformat())
    parser.add_argument("--output", type=Path, default=ROOT / "models" / "hybrid_benchmark.json")
    args = parser.parse_args()
    if not 1 <= args.episodes <= 200:
        raise ValueError("episodes must be between 1 and 200")

    data = WorkforceData.load(args.profile)
    data.configure_forecaster(
        model_path=args.forecast_model,
        metadata_path=args.forecast_metrics,
        state_path=args.forecast_state,
    )
    model_path, model_error = compatible_model(
        {"metadata": data.metadata},
        args.model,
    )
    dates = data.complete_dates
    rows = []
    selected_counts: Counter[str] = Counter()
    started = time.perf_counter()

    for episode in range(args.episodes):
        date_index = (
            len(dates) - 1
            if args.episodes <= 1
            else round(episode * (len(dates) - 1) / (args.episodes - 1))
        )
        scenario = data.create_scenario(
            template_date=dates[date_index],
            planning_date=args.planning_date,
            attendance_rate=0.72 + (episode % 8) * 0.04,
            demand_multiplier=0.85 + (episode % 7) * 0.05,
            same_division_only=episode % 4 != 0,
            seed=args.seed + episode,
        )
        result = build_candidate_plans(
            data,
            scenario,
            model_path=model_path,
            include_rl=model_path is not None,
            include_optimizer=True,
            optimizer_time_limit_seconds=args.time_limit,
        )
        summaries = result["summaries"]
        selected_counts[result["selected_name"]] += 1
        optimizer_summary = summaries["optimizer"]
        row = {
            "episode": episode + 1,
            "date": scenario.template_date,
            "planning_date": scenario.planning_date,
            "attendance_rate": scenario.attendance_rate,
            "demand_multiplier": scenario.demand_multiplier,
            "same_division_only": scenario.same_division_only,
            "selected_method": result["selected_name"],
            "selected_coverage_pct": result["selected"]["metrics"]["coverage_pct"],
            "standard_coverage_pct": summaries["standard"]["coverage_pct"],
            "rl_coverage_pct": summaries["rl"]["coverage_pct"] if summaries["rl"] else None,
            "optimizer_coverage_pct": optimizer_summary["coverage_pct"] if optimizer_summary else None,
            "optimizer_optimality_proven": (
                optimizer_summary["optimization"]["optimality_proven"]
                if optimizer_summary else False
            ),
            "optimizer_upper_bound_pct": (
                optimizer_summary["optimization"]["coverage_upper_bound_pct"]
                if optimizer_summary else None
            ),
            "optimizer_solve_seconds": (
                optimizer_summary["optimization"]["solve_seconds"]
                if optimizer_summary else None
            ),
            "constraint_violations": result["selected"]["metrics"]["constraint_violations"],
            "errors": result["errors"],
        }
        rows.append(row)
        rl_text = "n/a" if row["rl_coverage_pct"] is None else f"{row['rl_coverage_pct']:.1f}%"
        optimizer_text = (
            "n/a" if row["optimizer_coverage_pct"] is None
            else f"{row['optimizer_coverage_pct']:.1f}%"
        )
        proof = "proven" if row["optimizer_optimality_proven"] else "time-limited"
        print(
            f"[{episode + 1:02d}/{args.episodes:02d}] {scenario.template_date} · "
            f"standard {row['standard_coverage_pct']:.1f}% · RL {rl_text} · "
            f"optimizer {optimizer_text} ({proof}) · selected {result['selected_name']}",
            flush=True,
        )

    standard_values = [float(row["standard_coverage_pct"]) for row in rows]
    rl_values = [float(row["rl_coverage_pct"]) for row in rows if row["rl_coverage_pct"] is not None]
    optimizer_values = [
        float(row["optimizer_coverage_pct"])
        for row in rows if row["optimizer_coverage_pct"] is not None
    ]
    selected_values = [float(row["selected_coverage_pct"]) for row in rows]
    optimizer_differences = [
        float(row["optimizer_coverage_pct"]) - float(row["standard_coverage_pct"])
        for row in rows if row["optimizer_coverage_pct"] is not None
    ]
    rl_differences = [
        float(row["rl_coverage_pct"]) - float(row["standard_coverage_pct"])
        for row in rows if row["rl_coverage_pct"] is not None
    ]
    summary = {
        "evaluation_episodes": args.episodes,
        "evaluation_seed": args.seed,
        "evaluation_scope": (
            "fixed counterfactual scenarios sampled evenly across complete historical workdays "
            f"from {dates[0]} to {dates[-1]}"
        ),
        "standard_mean_coverage_pct": mean_or_none(standard_values),
        "rl_mean_coverage_pct": mean_or_none(rl_values),
        "optimizer_mean_coverage_pct": mean_or_none(optimizer_values),
        "hybrid_selected_mean_coverage_pct": mean_or_none(selected_values),
        "rl_minus_standard_pct_points": mean_or_none(rl_differences),
        "optimizer_minus_standard_pct_points": mean_or_none(optimizer_differences),
        "hybrid_minus_standard_pct_points": round(
            statistics.mean(selected_values) - statistics.mean(standard_values),
            2,
        ),
        "optimizer_wins_vs_standard": sum(value > 0.049 for value in optimizer_differences),
        "optimizer_ties_vs_standard": sum(abs(value) <= 0.049 for value in optimizer_differences),
        "optimizer_losses_vs_standard": sum(value < -0.049 for value in optimizer_differences),
        "optimizer_optimality_proven_episodes": sum(
            bool(row["optimizer_optimality_proven"]) for row in rows
        ),
        "optimizer_available_episodes": len(optimizer_values),
        "selected_method_counts": dict(selected_counts),
        "selected_constraint_violations": sum(int(row["constraint_violations"]) for row in rows),
        "optimizer_total_solve_seconds": round(sum(
            float(row["optimizer_solve_seconds"] or 0.0) for row in rows
        ), 2),
        "benchmark_seconds": round(time.perf_counter() - started, 2),
        "rl_model_used": model_path is not None,
        "rl_model_error": model_error,
        "profile_source_sha256": data.metadata.get("source_sha256"),
        "profile_source_name": data.metadata.get("source_name"),
        "profile_date_min": data.metadata.get("date_min"),
        "profile_date_max": data.metadata.get("date_max"),
        "profile_rows_used": data.metadata.get("source_rows_used"),
        "optimizer_time_limit_seconds": args.time_limit,
        "productivity_forecast": data.forecast_status(args.planning_date),
    }
    report = {"summary": summary, "episodes": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\n=== HYBRID BENCHMARK COMPLETE ===")
    print(json.dumps(summary, indent=2))
    print(f"Benchmark saved to {args.output}")
    return 0 if summary["selected_constraint_violations"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
