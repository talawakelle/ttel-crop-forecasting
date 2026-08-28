from __future__ import annotations

from pathlib import Path
import argparse
import json
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.data import WorkforceData
from allocator.training import evaluate_policy, train_policy
from sb3_contrib import MaskablePPO


def configured_data(profile: Path) -> WorkforceData:
    data = WorkforceData.load(profile)
    status = data.configure_forecaster(
        model_path=ROOT / "models" / "productivity_catboost.cbm",
        weather_model_path=ROOT / "models" / "productivity_weather_catboost.cbm",
        metadata_path=ROOT / "models" / "productivity_metrics.json",
        state_path=ROOT / "data" / "productivity_state.json.gz",
        weather_daily_path=ROOT / "data" / "weather_daily.csv.gz",
        weather_metadata_path=ROOT / "data" / "weather_metadata.json",
    )
    if not status.get("ready"):
        raise RuntimeError(f"Approved CatBoost forecast is required before RL training: {status.get('error')}")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train multiple forecast-aware RL candidates and activate only a policy that passes the safety gate"
    )
    parser.add_argument("--timesteps-per-seed", type=int, default=400_000)
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 2026, 3407])
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="cuda")
    parser.add_argument("--evaluation-episodes", type=int, default=80)
    parser.add_argument("--evaluation-rollouts", type=int, default=32)
    parser.add_argument("--evaluation-seed", type=int, default=9042)
    parser.add_argument("--profile", type=Path, default=ROOT / "data" / "workforce_profile.json")
    parser.add_argument("--output-model", type=Path, default=ROOT / "models" / "maskable_ppo_allocator.zip")
    args = parser.parse_args()

    if args.timesteps_per_seed < 50_000:
        raise ValueError("Strong forecast-aware training requires at least 50,000 steps per seed")
    if len(set(args.seeds)) != len(args.seeds):
        raise ValueError("Every training seed must be unique")

    data = configured_data(args.profile)
    candidate_results = []
    for index, seed in enumerate(args.seeds, start=1):
        candidate_dir = ROOT / "models" / "candidates" / f"seed_{seed}"
        candidate_model = candidate_dir / "maskable_ppo_allocator.zip"
        print(f"\n=== Candidate {index}/{len(args.seeds)} · seed {seed} ===", flush=True)
        metrics = train_policy(
            data,
            candidate_model,
            timesteps=args.timesteps_per_seed,
            seed=seed,
            device=args.device,
            evaluation_seed=args.evaluation_seed,
            evaluation_episodes=args.evaluation_episodes,
            evaluation_rollouts=args.evaluation_rollouts,
        )
        candidate_results.append({
            "seed": seed,
            "model": str(candidate_model),
            "metrics": metrics,
        })
        print(json.dumps(metrics, indent=2), flush=True)

    approved = [
        candidate for candidate in candidate_results
        if candidate["metrics"].get("approved") and Path(candidate["model"]).exists()
    ]
    if not approved:
        report = {
            "approved": False,
            "reason": "No RL candidate beat the greedy policy while passing every safety gate.",
            "candidates": [
                {
                    "seed": item["seed"],
                    "approval_gate": item["metrics"].get("approval_gate"),
                    "difference_pct_points": item["metrics"].get("rl_minus_greedy_pct_points"),
                    "win_rate_pct": item["metrics"].get("rl_win_rate_pct"),
                }
                for item in candidate_results
            ],
        }
        (ROOT / "models" / "strong_training_rejected.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        raise RuntimeError(report["reason"])

    best = max(
        approved,
        key=lambda candidate: (
            candidate["metrics"]["rl_minus_greedy_pct_points"],
            candidate["metrics"]["rl_win_rate_pct"],
            candidate["metrics"]["difference_p10_pct_points"],
            candidate["metrics"]["rl_mean_coverage_pct"],
        ),
    )

    args.output_model.parent.mkdir(parents=True, exist_ok=True)
    selected_metrics = dict(best["metrics"])
    benchmark_model = MaskablePPO.load(str(best["model"]), device=args.device)
    benchmark_metrics = evaluate_policy(data, benchmark_model, episodes=100, seed=1042, rollouts=32)
    if not benchmark_metrics.get("approved"):
        raise RuntimeError(
            "The selected candidate failed the independent final benchmark. "
            "Any previously approved production model was preserved."
        )
    metrics_path = args.output_model.with_name("training_metrics.json")
    if args.output_model.exists():
        from datetime import datetime
        backup_dir = args.output_model.parent / "rl-backup" / datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.output_model, backup_dir / args.output_model.name)
        if metrics_path.exists():
            shutil.copy2(metrics_path, backup_dir / metrics_path.name)
    shutil.copy2(best["model"], args.output_model)
    selected_metrics.update({f"final_{key}": value for key, value in benchmark_metrics.items()})
    selected_metrics["evaluation_seed"] = 1042
    selected_metrics["model_path"] = args.output_model.name
    selected_metrics["total_candidate_training_seconds"] = round(
        sum(candidate["metrics"]["training_seconds"] for candidate in candidate_results), 2
    )
    selected_metrics["selection"] = {
        "method": "highest approved forecast-aware paired gain over greedy",
        "selected_seed": best["seed"],
        "candidate_count": len(candidate_results),
        "timesteps_per_seed": args.timesteps_per_seed,
        "candidate_evaluation_seed": args.evaluation_seed,
        "final_benchmark_seed": 1042,
        "candidates": [
            {
                "seed": candidate["seed"],
                "approved": candidate["metrics"].get("approved"),
                "rl_mean_coverage_pct": candidate["metrics"].get("rl_mean_coverage_pct"),
                "greedy_mean_coverage_pct": candidate["metrics"].get("greedy_mean_coverage_pct"),
                "difference_pct_points": candidate["metrics"].get("rl_minus_greedy_pct_points"),
                "win_rate_pct": candidate["metrics"].get("rl_win_rate_pct"),
                "p10_difference_pct_points": candidate["metrics"].get("difference_p10_pct_points"),
                "constraint_violations": candidate["metrics"].get("rl_constraint_violations"),
            }
            for candidate in candidate_results
        ],
    }
    metrics_path.write_text(json.dumps(selected_metrics, indent=2), encoding="utf-8")
    (ROOT / "models" / "strong_training_rejected.json").unlink(missing_ok=True)
    print("\n=== APPROVED MODEL SELECTED ===")
    print(json.dumps(selected_metrics, indent=2))


if __name__ == "__main__":
    main()
