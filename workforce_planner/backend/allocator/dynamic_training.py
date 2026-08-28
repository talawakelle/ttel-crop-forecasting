from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib
import json
import os
import shutil
import statistics
import tempfile
import time

import numpy as np
import torch
from sb3_contrib import MaskablePPO
from stable_baselines3.common.vec_env import DummyVecEnv, VecMonitor

from .data import WorkforceData
from .dynamic_environment import DynamicReallocationEnv
from .version import DYNAMIC_MODEL_SCHEMA_VERSION, DYNAMIC_TRAINING_STRATEGY


MIN_GAIN_VS_NO_REPLAN = 0.50
MIN_WIN_RATE_VS_NO_REPLAN = 60.0
MIN_P10_VS_NO_REPLAN = -1.50
MIN_BOOTSTRAP_LOWER_GAIN = 0.0
MIN_FIELD_FLOOR_GAIN = 0.25
MIN_MEAN_VS_DYNAMIC_GREEDY = -0.15
MIN_STRESS_GAIN = 0.0
MIN_STRESS_P10 = -3.0
MAX_MEAN_REASSIGNMENTS_PER_WORKER = 0.45


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def temporal_three_way_split(
    data: WorkforceData,
    *,
    validation_days: int = 120,
    test_days: int = 180,
) -> tuple[list[str], list[str], list[str]]:
    dates = list(data.complete_dates)
    test_count = max(60, min(int(test_days), max(60, len(dates) // 4)))
    validation_count = max(60, min(int(validation_days), max(60, len(dates) // 5)))
    if len(dates) - test_count - validation_count < 365:
        available = max(120, len(dates) - 365)
        test_count = max(60, min(test_count, available // 2))
        validation_count = max(60, min(validation_count, available - test_count))
    train_end = len(dates) - validation_count - test_count
    validation_end = len(dates) - test_count
    return dates[:train_end], dates[train_end:validation_end], dates[validation_end:]


def _bootstrap_mean_interval(values: np.ndarray, seed: int = 991, samples: int = 2000) -> tuple[float, float]:
    if values.size <= 1:
        value = float(values.mean()) if values.size else 0.0
        return value, value
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, values.size, size=(int(samples), values.size))
    means = values[indices].mean(axis=1)
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def _robust_score(metrics: dict[str, Any]) -> float:
    return (
        float(metrics.get("mean_gain_vs_no_replan_pct_points", -100.0))
        + 0.35 * float(metrics.get("mean_field_floor_gain_pct_points", -100.0))
        + 0.015 * float(metrics.get("win_rate_vs_no_replan_pct", 0.0))
        + 0.25 * float(metrics.get("mean_gain_vs_dynamic_greedy_pct_points", -100.0))
        + 0.20 * min(0.0, float(metrics.get("p10_gain_vs_no_replan_pct_points", -100.0)))
    )


def dynamic_approval_gate(metrics: dict[str, Any]) -> dict[str, bool]:
    worker_count = max(1.0, float(metrics.get("mean_workers_considered", 1.0)))
    reassignment_rate = float(metrics.get("mean_reassignments", 999.0)) / worker_count
    stress = metrics.get("extreme_stress", {}) or {}
    return {
        "zero_hard_constraint_violations": int(metrics.get("constraint_violations", 999)) == 0,
        "mean_gain_vs_no_replan": float(metrics.get("mean_gain_vs_no_replan_pct_points", -999.0)) >= MIN_GAIN_VS_NO_REPLAN,
        "win_rate_vs_no_replan": float(metrics.get("win_rate_vs_no_replan_pct", 0.0)) >= MIN_WIN_RATE_VS_NO_REPLAN,
        "tail_risk_bounded": float(metrics.get("p10_gain_vs_no_replan_pct_points", -999.0)) >= MIN_P10_VS_NO_REPLAN,
        "bootstrap_gain_positive": float(metrics.get("bootstrap_95pct_mean_gain_lower", -999.0)) >= MIN_BOOTSTRAP_LOWER_GAIN,
        "field_floor_improved": float(metrics.get("mean_field_floor_gain_pct_points", -999.0)) >= MIN_FIELD_FLOOR_GAIN,
        "not_materially_worse_than_dynamic_greedy": float(metrics.get("mean_gain_vs_dynamic_greedy_pct_points", -999.0)) >= MIN_MEAN_VS_DYNAMIC_GREEDY,
        "extreme_stress_mean_nonnegative": float(stress.get("mean_gain_vs_no_replan_pct_points", -999.0)) >= MIN_STRESS_GAIN,
        "extreme_stress_tail_bounded": float(stress.get("p10_gain_vs_no_replan_pct_points", -999.0)) >= MIN_STRESS_P10,
        "reassignment_rate_bounded": reassignment_rate <= MAX_MEAN_REASSIGNMENTS_PER_WORKER,
        "untouched_test_evaluation": bool(metrics.get("untouched_test_evaluation")),
    }


def make_vector_env(
    data: WorkforceData,
    dates: list[str],
    *,
    seed: int,
    difficulty: str,
    env_count: int,
):
    factories = []
    for index in range(max(1, int(env_count))):
        env_seed = int(seed) + index * 1009
        factories.append(
            lambda env_seed=env_seed: DynamicReallocationEnv(
                data,
                scenario_dates=dates,
                seed=env_seed,
                difficulty=difficulty,
            )
        )
    return VecMonitor(DummyVecEnv(factories))


def evaluate_dynamic_policy(
    data: WorkforceData,
    model: MaskablePPO,
    *,
    dates: list[str],
    episodes: int = 180,
    seed: int = 7021,
    difficulty: str = "full",
    evaluation_label: str = "validation",
) -> dict[str, Any]:
    gains_no_replan: list[float] = []
    gains_greedy: list[float] = []
    field_floor_gains: list[float] = []
    rl_coverages: list[float] = []
    no_replan_coverages: list[float] = []
    greedy_coverages: list[float] = []
    perfect_info_references: list[float] = []
    critical_fields: list[float] = []
    violations = 0
    changes: list[float] = []
    transfers: list[float] = []
    workers: list[float] = []
    for episode in range(max(1, int(episodes))):
        env = DynamicReallocationEnv(
            data,
            scenario_dates=dates,
            seed=seed + episode * 7919,
            difficulty=difficulty,
        )
        observation, _ = env.reset(seed=seed + episode * 104729)
        terminated = False
        while not terminated:
            action, _ = model.predict(
                observation,
                action_masks=env.action_masks(),
                deterministic=True,
            )
            observation, _reward, terminated, _truncated, _info = env.step(action)
        result = env.result()
        metrics = result["metrics"]
        rl = float(metrics["actual_simulated_coverage_pct"])
        no_replan = float(metrics["no_replan_coverage_pct"])
        greedy = float(metrics["dynamic_greedy_coverage_pct"])
        rl_coverages.append(rl)
        no_replan_coverages.append(no_replan)
        greedy_coverages.append(greedy)
        perfect_info_references.append(float(metrics["perfect_information_greedy_reference_pct"]))
        gains_no_replan.append(rl - no_replan)
        gains_greedy.append(rl - greedy)
        field_floor_gains.append(float(metrics["field_floor_gain_vs_no_replan_pct_points"]))
        critical_fields.append(float(metrics["critical_fields_below_75_pct"]))
        violations += int(metrics["constraint_violations"])
        changes.append(float(metrics["reassignments"]))
        transfers.append(float(metrics["cross_division_assignments"]))
        workers.append(float(metrics["workers_considered"]))
    gains = np.asarray(gains_no_replan, dtype=float)
    greedy_gains = np.asarray(gains_greedy, dtype=float)
    floors = np.asarray(field_floor_gains, dtype=float)
    lower, upper = _bootstrap_mean_interval(gains, seed=seed + 31337)
    result = {
        "evaluation_episodes": int(episodes),
        "evaluation_difficulty": difficulty,
        "evaluation_label": evaluation_label,
        "held_out_temporal_evaluation": evaluation_label in {"validation", "test"},
        "untouched_test_evaluation": evaluation_label == "test",
        "evaluation_start": dates[0],
        "evaluation_end": dates[-1],
        "rl_mean_actual_coverage_pct": round(statistics.mean(rl_coverages), 3),
        "no_replan_mean_actual_coverage_pct": round(statistics.mean(no_replan_coverages), 3),
        "dynamic_greedy_mean_actual_coverage_pct": round(statistics.mean(greedy_coverages), 3),
        "perfect_information_greedy_reference_mean_pct": round(statistics.mean(perfect_info_references), 3),
        "remaining_gap_to_perfect_information_greedy_reference_pct_points": round(
            statistics.mean(perfect_info_references) - statistics.mean(rl_coverages), 3
        ),
        "perfect_information_reference_is_certified_upper_bound": False,
        "mean_gain_vs_no_replan_pct_points": round(float(gains.mean()), 3),
        "median_gain_vs_no_replan_pct_points": round(float(np.median(gains)), 3),
        "p10_gain_vs_no_replan_pct_points": round(float(np.quantile(gains, 0.10)), 3),
        "p05_gain_vs_no_replan_pct_points": round(float(np.quantile(gains, 0.05)), 3),
        "worst_gain_vs_no_replan_pct_points": round(float(gains.min()), 3),
        "bootstrap_95pct_mean_gain_lower": round(lower, 3),
        "bootstrap_95pct_mean_gain_upper": round(upper, 3),
        "win_rate_vs_no_replan_pct": round(100.0 * float(np.mean(gains > 0.0)), 3),
        "mean_gain_vs_dynamic_greedy_pct_points": round(float(greedy_gains.mean()), 3),
        "win_rate_vs_dynamic_greedy_pct": round(100.0 * float(np.mean(greedy_gains > 0.0)), 3),
        "mean_field_floor_gain_pct_points": round(float(floors.mean()), 3),
        "p10_field_floor_gain_pct_points": round(float(np.quantile(floors, 0.10)), 3),
        "mean_critical_fields_below_75_pct": round(statistics.mean(critical_fields), 3),
        "mean_reassignments": round(statistics.mean(changes), 3),
        "mean_cross_division_assignments": round(statistics.mean(transfers), 3),
        "mean_workers_considered": round(statistics.mean(workers), 3),
        "constraint_violations": int(violations),
        "dynamic_model_schema_version": DYNAMIC_MODEL_SCHEMA_VERSION,
        "training_strategy": DYNAMIC_TRAINING_STRATEGY,
        "robust_score": 0.0,
        "evaluation_note": (
            "Outcomes use paired simulated disruptions and realized output. The policy never observes comparator "
            "coverage or future realized output. Operational approval still requires actual shadow-mode outcomes."
        ),
    }
    result["robust_score"] = round(_robust_score(result), 5)
    return result


def _new_model(env, *, seed: int, device: str) -> MaskablePPO:
    def learning_rate(progress_remaining: float) -> float:
        return 2.5e-5 + (1.8e-4 - 2.5e-5) * float(progress_remaining)

    return MaskablePPO(
        "MlpPolicy",
        env,
        learning_rate=learning_rate,
        n_steps=3072,
        batch_size=768,
        n_epochs=8,
        gamma=0.997,
        gae_lambda=0.96,
        ent_coef=0.010,
        vf_coef=0.70,
        clip_range=0.18,
        max_grad_norm=0.45,
        normalize_advantage=True,
        target_kl=0.025,
        policy_kwargs={
            "activation_fn": torch.nn.SiLU,
            "ortho_init": False,
            "net_arch": {"pi": [512, 512, 256], "vf": [512, 512, 256]},
        },
        seed=seed,
        verbose=1,
        device=device,
        stats_window_size=100,
    )


def _train_candidate(
    data: WorkforceData,
    *,
    training_dates: list[str],
    validation_dates: list[str],
    seed: int,
    device: str,
    env_count: int,
    phases: list[tuple[str, int]],
    validation_episodes: int,
    directory: Path,
) -> tuple[MaskablePPO, dict[str, Any]]:
    first_env = make_vector_env(data, training_dates, seed=seed, difficulty="easy", env_count=env_count)
    model = _new_model(first_env, seed=seed, device=device)
    best_score = -1e9
    best_path = directory / f"candidate_{seed}_best.zip"
    phase_report: list[dict[str, Any]] = []
    total_steps = 0
    for phase_number, (difficulty, steps) in enumerate(phases, start=1):
        if steps <= 0:
            continue
        environment = make_vector_env(
            data,
            training_dates,
            seed=seed + phase_number * 100_003,
            difficulty=difficulty,
            env_count=env_count,
        )
        model.set_env(environment)
        model.learn(total_timesteps=int(steps), reset_num_timesteps=False, progress_bar=False)
        total_steps += int(steps)
        checkpoint = evaluate_dynamic_policy(
            data,
            model,
            dates=validation_dates,
            episodes=max(40, int(validation_episodes)),
            seed=seed + total_steps + 11_111,
            difficulty="full",
            evaluation_label="validation",
        )
        score = float(checkpoint["robust_score"])
        improved = score > best_score
        if improved:
            best_score = score
            model.save(str(best_path))
        phase_report.append({
            "phase": phase_number,
            "difficulty": difficulty,
            "steps": int(steps),
            "total_steps": total_steps,
            "validation": checkpoint,
            "best_checkpoint_so_far": improved,
        })
    if not best_path.exists():
        model.save(str(best_path))
    final_env = make_vector_env(data, training_dates, seed=seed + 999_983, difficulty="mixed", env_count=env_count)
    best_model = MaskablePPO.load(str(best_path), env=final_env, device=device)
    validation = evaluate_dynamic_policy(
        data,
        best_model,
        dates=validation_dates,
        episodes=max(80, int(validation_episodes) * 2),
        seed=seed + 700_001,
        difficulty="full",
        evaluation_label="validation",
    )
    report = {
        "seed": int(seed),
        "total_timesteps": int(total_steps),
        "validation": validation,
        "phases": phase_report,
        "selected_checkpoint": str(best_path.name),
    }
    return best_model, report


def train_dynamic_policy(
    data: WorkforceData,
    output_path: Path,
    *,
    seed: int = 42,
    device: str = "cuda",
    env_count: int = 4,
    easy_steps: int = 150_000,
    medium_steps: int = 250_000,
    full_steps: int = 400_000,
    mixed_steps: int = 300_000,
    validation_days: int = 120,
    test_days: int = 180,
    evaluation_episodes: int = 240,
    stress_episodes: int = 120,
    candidate_seeds: int = 3,
) -> dict[str, Any]:
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but PyTorch cannot access an NVIDIA GPU")
    training_dates, validation_dates, test_dates = temporal_three_way_split(
        data,
        validation_days=validation_days,
        test_days=test_days,
    )
    if len(training_dates) < 365:
        raise RuntimeError("Dynamic RL requires at least one year of training dates")
    started = time.time()
    phases = [
        ("easy", int(easy_steps)),
        ("medium", int(medium_steps)),
        ("full", int(full_steps)),
        ("mixed", int(mixed_steps)),
    ]
    candidate_count = max(1, min(5, int(candidate_seeds)))
    candidate_reports: list[dict[str, Any]] = []
    candidate_models: list[MaskablePPO] = []
    with tempfile.TemporaryDirectory(prefix="tte-dynamic-rl-") as temp:
        temp_dir = Path(temp)
        for candidate_index in range(candidate_count):
            candidate_seed = int(seed) + candidate_index * 100_000_007
            model, report = _train_candidate(
                data,
                training_dates=training_dates,
                validation_dates=validation_dates,
                seed=candidate_seed,
                device=device,
                env_count=env_count,
                phases=phases,
                validation_episodes=max(40, evaluation_episodes // 6),
                directory=temp_dir,
            )
            candidate_models.append(model)
            candidate_reports.append(report)
        selected_index = max(
            range(len(candidate_reports)),
            key=lambda index: float(candidate_reports[index]["validation"]["robust_score"]),
        )
        model = candidate_models[selected_index]
        selected_report = candidate_reports[selected_index]

        full_test = evaluate_dynamic_policy(
            data,
            model,
            dates=test_dates,
            episodes=evaluation_episodes,
            seed=int(seed) + 9_000_001,
            difficulty="full",
            evaluation_label="test",
        )
        extreme_test = evaluate_dynamic_policy(
            data,
            model,
            dates=test_dates,
            episodes=stress_episodes,
            seed=int(seed) + 19_000_003,
            difficulty="extreme",
            evaluation_label="test",
        )
        metrics = dict(full_test)
        metrics.update({
            "selected_candidate_index": int(selected_index),
            "selected_candidate_seed": int(selected_report["seed"]),
            "candidate_count": int(candidate_count),
            "candidate_tournament": candidate_reports,
            "extreme_stress": extreme_test,
            "seed": int(seed),
            "device": str(model.device),
            "gpu_name": torch.cuda.get_device_name(0) if str(model.device).startswith("cuda") else None,
            "training_dates_start": training_dates[0],
            "training_dates_end": training_dates[-1],
            "validation_dates_start": validation_dates[0],
            "validation_dates_end": validation_dates[-1],
            "test_dates_start": test_dates[0],
            "test_dates_end": test_dates[-1],
            "training_date_count": len(training_dates),
            "validation_date_count": len(validation_dates),
            "test_date_count": len(test_dates),
            "total_timesteps_per_candidate": sum(steps for _difficulty, steps in phases),
            "total_timesteps_all_candidates": sum(steps for _difficulty, steps in phases) * candidate_count,
            "environment_count": int(env_count),
            "training_seconds": round(time.time() - started, 2),
            "profile_source_sha256": data.metadata.get("source_sha256"),
            "productivity_forecast": data.forecast_status(),
            "forecast_base_model_sha256": (getattr(data.forecaster, "metadata", None) or {}).get("base_model_sha256"),
            "crop_forecast_source_sha256": data.crop_forecast_status().get("source_sha256"),
            "crop_forecast_error_assumption": (
                data.crop_forecaster.representative_wape() if data.crop_forecaster is not None else 0.15
            ),
            "dynamic_environment_sha256": _sha256_file(Path(__file__).with_name("dynamic_environment.py")),
            "dynamic_training_sha256": _sha256_file(Path(__file__)),
            "shadow_mode_approved": False,
            "environment_design": {
                "morning_fraction": 0.35,
                "replanning_rounds": 2,
                "decision_fractions": [0.35, 0.30],
                "future_reference_metrics_in_observation": False,
                "domain_randomisation": True,
                "late_absence_and_demand_updates": True,
                "repeat_move_mask": True,
            },
        })
        metrics["constraint_violations"] = int(full_test["constraint_violations"]) + int(extreme_test["constraint_violations"])
        metrics["approval_gate"] = dynamic_approval_gate(metrics)
        metrics["approved"] = all(metrics["approval_gate"].values())

        output_path.parent.mkdir(parents=True, exist_ok=True)
        metrics_path = output_path.with_name("dynamic_training_metrics.json")
        rejected_path = output_path.with_name("dynamic_training_rejected.json")
        if metrics["approved"]:
            candidate = output_path.with_name(f"{output_path.stem}.candidate.zip")
            candidate.unlink(missing_ok=True)
            model.save(str(candidate))
            if output_path.exists():
                backup_dir = output_path.parent / "dynamic-rl-backup" / time.strftime("%Y%m%d-%H%M%S")
                backup_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(output_path, backup_dir / output_path.name)
                if metrics_path.exists():
                    shutil.copy2(metrics_path, backup_dir / metrics_path.name)
            os.replace(candidate, output_path)
            metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
            rejected_path.unlink(missing_ok=True)
        else:
            rejected_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        return metrics
