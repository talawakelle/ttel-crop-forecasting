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
from .dynamic_training import temporal_three_way_split
from .selective_environment import SelectiveHybridReallocationEnv
from .selective_actions import KEEP_CURRENT
from .selective_policy import (
    DEFAULT_VETO_CONFIDENCE_THRESHOLD,
    VETO_CONFIDENCE_THRESHOLD_GRID,
    conservative_selective_action,
)
from .version import SELECTIVE_HYBRID_MODEL_SCHEMA_VERSION, SELECTIVE_HYBRID_TRAINING_STRATEGY


MIN_GAIN_VS_NO_REPLAN = 0.25
MIN_GAIN_VS_BUDGETED_GREEDY = 0.0
MIN_BOOTSTRAP_LOWER_VS_BUDGETED = -0.10
MIN_P10_VS_BUDGETED = -0.50
MIN_NONINFERIOR_RATE_VS_BUDGETED = 80.0
MIN_GAIN_VS_FULL_GREEDY = -0.50
MAX_REASSIGNMENT_RATE = 0.15
MAX_MEAN_REASSIGNMENTS = 15.0
MIN_EXTREME_GAIN_VS_NO_REPLAN = 0.0
MIN_EXTREME_P10_VS_BUDGETED = -0.75
MIN_VALUE_ADD_GAIN = 0.02
MIN_VALUE_ADD_MOVE_SAVING = 0.50


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _bootstrap_mean_interval(
    values: np.ndarray,
    *,
    seed: int = 991,
    samples: int = 2000,
) -> tuple[float, float]:
    if values.size <= 1:
        value = float(values.mean()) if values.size else 0.0
        return value, value
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, values.size, size=(int(samples), values.size))
    means = values[indices].mean(axis=1)
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def _robust_score(metrics: dict[str, Any]) -> float:
    return (
        1.6 * float(metrics.get("mean_gain_vs_budgeted_dynamic_greedy_pct_points", -100.0))
        + 0.7 * float(metrics.get("mean_gain_vs_no_replan_pct_points", -100.0))
        + 0.020 * float(metrics.get("noninferior_rate_vs_budgeted_dynamic_greedy_pct", 0.0))
        + 0.12 * float(metrics.get("mean_movement_saving_vs_budgeted_greedy", 0.0))
        + 0.20 * min(0.0, float(metrics.get("p10_gain_vs_budgeted_dynamic_greedy_pct_points", -100.0)))
        - 0.50 * max(0.0, float(metrics.get("mean_reassignment_rate", 1.0)) - MAX_REASSIGNMENT_RATE)
    )


def selective_hybrid_approval_gate(metrics: dict[str, Any]) -> dict[str, bool]:
    stress = metrics.get("extreme_stress", {}) or {}
    adds_value = (
        float(metrics.get("mean_gain_vs_budgeted_dynamic_greedy_pct_points", -999.0))
        >= MIN_VALUE_ADD_GAIN
        or float(metrics.get("mean_movement_saving_vs_budgeted_greedy", -999.0))
        >= MIN_VALUE_ADD_MOVE_SAVING
    )
    return {
        "zero_hard_constraint_violations": int(metrics.get("constraint_violations", 999)) == 0,
        "mean_gain_vs_no_replan": float(metrics.get("mean_gain_vs_no_replan_pct_points", -999.0)) >= MIN_GAIN_VS_NO_REPLAN,
        "not_worse_than_budgeted_dynamic_greedy": float(metrics.get("mean_gain_vs_budgeted_dynamic_greedy_pct_points", -999.0)) >= MIN_GAIN_VS_BUDGETED_GREEDY,
        "bootstrap_noninferiority_vs_budgeted_greedy": float(metrics.get("bootstrap_95pct_gain_vs_budgeted_lower", -999.0)) >= MIN_BOOTSTRAP_LOWER_VS_BUDGETED,
        "tail_risk_vs_budgeted_greedy_bounded": float(metrics.get("p10_gain_vs_budgeted_dynamic_greedy_pct_points", -999.0)) >= MIN_P10_VS_BUDGETED,
        "noninferior_rate_vs_budgeted_greedy": float(metrics.get("noninferior_rate_vs_budgeted_dynamic_greedy_pct", 0.0)) >= MIN_NONINFERIOR_RATE_VS_BUDGETED,
        "close_to_full_dynamic_greedy": float(metrics.get("mean_gain_vs_dynamic_greedy_pct_points", -999.0)) >= MIN_GAIN_VS_FULL_GREEDY,
        "reassignment_rate_bounded": float(metrics.get("mean_reassignment_rate", 999.0)) <= MAX_REASSIGNMENT_RATE,
        "mean_reassignments_bounded": float(metrics.get("mean_reassignments", 999.0)) <= MAX_MEAN_REASSIGNMENTS,
        "adds_value_over_budgeted_greedy": adds_value,
        "extreme_stress_mean_nonnegative_vs_no_replan": float(stress.get("mean_gain_vs_no_replan_pct_points", -999.0)) >= MIN_EXTREME_GAIN_VS_NO_REPLAN,
        "extreme_stress_tail_vs_budgeted_bounded": float(stress.get("p10_gain_vs_budgeted_dynamic_greedy_pct_points", -999.0)) >= MIN_EXTREME_P10_VS_BUDGETED,
        "untouched_test_evaluation": bool(metrics.get("untouched_test_evaluation")),
        "safety_fallback_available": bool(metrics.get("safety_fallback_available")),
    }


def make_selective_vector_env(
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
            lambda env_seed=env_seed: SelectiveHybridReallocationEnv(
                data,
                scenario_dates=dates,
                seed=env_seed,
                difficulty=difficulty,
            )
        )
    return VecMonitor(DummyVecEnv(factories))


def evaluate_selective_hybrid_policy(
    data: WorkforceData,
    model: MaskablePPO,
    *,
    dates: list[str],
    episodes: int = 180,
    seed: int = 7021,
    difficulty: str = "full",
    evaluation_label: str = "validation",
    veto_confidence_threshold: float = DEFAULT_VETO_CONFIDENCE_THRESHOLD,
) -> dict[str, Any]:
    selected_coverages: list[float] = []
    raw_coverages: list[float] = []
    no_replan_coverages: list[float] = []
    budgeted_coverages: list[float] = []
    full_greedy_coverages: list[float] = []
    gains_no_replan: list[float] = []
    gains_budgeted: list[float] = []
    gains_full_greedy: list[float] = []
    field_floor_gains: list[float] = []
    changes: list[float] = []
    raw_changes: list[float] = []
    budgeted_changes: list[float] = []
    movement_savings: list[float] = []
    workers: list[float] = []
    decisions: list[float] = []
    vetoes: list[float] = []
    blocked_vetoes: list[float] = []
    fallbacks: list[float] = []
    violations = 0
    raw_policy_vetoes: list[float] = []
    low_confidence_veto_overrides: list[float] = []
    applied_high_confidence_vetoes: list[float] = []

    for episode in range(max(1, int(episodes))):
        env = SelectiveHybridReallocationEnv(
            data,
            scenario_dates=dates,
            seed=seed + episode * 7919,
            difficulty=difficulty,
        )
        observation, _ = env.reset(seed=seed + episode * 104729)
        terminated = False
        episode_raw_vetoes = 0
        episode_overrides = 0
        episode_applied_vetoes = 0
        while not terminated:
            decision = conservative_selective_action(
                model,
                observation,
                env.action_masks(),
                veto_confidence_threshold=veto_confidence_threshold,
            )
            if decision.raw_action == KEEP_CURRENT:
                episode_raw_vetoes += 1
            if decision.low_confidence_veto_overridden:
                episode_overrides += 1
            if decision.applied_action == KEEP_CURRENT:
                episode_applied_vetoes += 1
            observation, _reward, terminated, _truncated, _info = env.step(
                decision.applied_action
            )
        metrics = env.result()["metrics"]
        raw_policy_vetoes.append(float(episode_raw_vetoes))
        low_confidence_veto_overrides.append(float(episode_overrides))
        applied_high_confidence_vetoes.append(float(episode_applied_vetoes))
        selected = float(metrics["actual_simulated_coverage_pct"])
        raw = float(metrics["raw_hybrid_coverage_pct"])
        no_replan = float(metrics["no_replan_coverage_pct"])
        budgeted = float(metrics["budgeted_dynamic_greedy_coverage_pct"])
        full_greedy = float(metrics["dynamic_greedy_coverage_pct"])
        selected_coverages.append(selected)
        raw_coverages.append(raw)
        no_replan_coverages.append(no_replan)
        budgeted_coverages.append(budgeted)
        full_greedy_coverages.append(full_greedy)
        gains_no_replan.append(selected - no_replan)
        gains_budgeted.append(selected - budgeted)
        gains_full_greedy.append(selected - full_greedy)
        field_floor_gains.append(float(metrics["field_floor_gain_vs_no_replan_pct_points"]))
        changes.append(float(metrics["reassignments"]))
        raw_changes.append(float(metrics["raw_reassignments"]))
        budgeted_changes.append(float(metrics["budgeted_dynamic_greedy_reassignments"]))
        movement_savings.append(float(metrics["movement_saving_vs_budgeted_greedy"]))
        workers.append(float(metrics["workers_considered"]))
        decisions.append(float(metrics["selective_decisions"]))
        vetoes.append(float(metrics["rl_vetoes"]))
        blocked_vetoes.append(float(metrics["shield_blocked_vetoes"]))
        fallbacks.append(float(bool(metrics["fallback_triggered"])))
        violations += int(metrics["constraint_violations"])

    gain_no = np.asarray(gains_no_replan, dtype=float)
    gain_budget = np.asarray(gains_budgeted, dtype=float)
    gain_full = np.asarray(gains_full_greedy, dtype=float)
    lower_no, upper_no = _bootstrap_mean_interval(gain_no, seed=seed + 31337)
    lower_budget, upper_budget = _bootstrap_mean_interval(gain_budget, seed=seed + 41339)
    mean_workers = max(1.0, statistics.mean(workers))
    mean_changes = statistics.mean(changes)
    result = {
        "evaluation_episodes": int(episodes),
        "evaluation_difficulty": difficulty,
        "evaluation_label": evaluation_label,
        "held_out_temporal_evaluation": evaluation_label in {"validation", "test"},
        "untouched_test_evaluation": evaluation_label == "test",
        "evaluation_start": dates[0],
        "evaluation_end": dates[-1],
        "hybrid_mean_actual_coverage_pct": round(statistics.mean(selected_coverages), 3),
        "raw_hybrid_mean_actual_coverage_pct": round(statistics.mean(raw_coverages), 3),
        "no_replan_mean_actual_coverage_pct": round(statistics.mean(no_replan_coverages), 3),
        "budgeted_dynamic_greedy_mean_actual_coverage_pct": round(statistics.mean(budgeted_coverages), 3),
        "dynamic_greedy_mean_actual_coverage_pct": round(statistics.mean(full_greedy_coverages), 3),
        "mean_gain_vs_no_replan_pct_points": round(float(gain_no.mean()), 3),
        "median_gain_vs_no_replan_pct_points": round(float(np.median(gain_no)), 3),
        "p10_gain_vs_no_replan_pct_points": round(float(np.quantile(gain_no, 0.10)), 3),
        "bootstrap_95pct_gain_vs_no_replan_lower": round(lower_no, 3),
        "bootstrap_95pct_gain_vs_no_replan_upper": round(upper_no, 3),
        "win_rate_vs_no_replan_pct": round(100.0 * float(np.mean(gain_no > 0.0)), 3),
        "mean_gain_vs_budgeted_dynamic_greedy_pct_points": round(float(gain_budget.mean()), 3),
        "median_gain_vs_budgeted_dynamic_greedy_pct_points": round(float(np.median(gain_budget)), 3),
        "p10_gain_vs_budgeted_dynamic_greedy_pct_points": round(float(np.quantile(gain_budget, 0.10)), 3),
        "bootstrap_95pct_gain_vs_budgeted_lower": round(lower_budget, 3),
        "bootstrap_95pct_gain_vs_budgeted_upper": round(upper_budget, 3),
        "win_rate_vs_budgeted_dynamic_greedy_pct": round(100.0 * float(np.mean(gain_budget > 0.0)), 3),
        "noninferior_rate_vs_budgeted_dynamic_greedy_pct": round(100.0 * float(np.mean(gain_budget >= -0.05)), 3),
        "mean_gain_vs_dynamic_greedy_pct_points": round(float(gain_full.mean()), 3),
        "p10_gain_vs_dynamic_greedy_pct_points": round(float(np.quantile(gain_full, 0.10)), 3),
        "mean_field_floor_gain_pct_points": round(statistics.mean(field_floor_gains), 3),
        "mean_reassignments": round(mean_changes, 3),
        "mean_raw_reassignments": round(statistics.mean(raw_changes), 3),
        "mean_budgeted_dynamic_greedy_reassignments": round(statistics.mean(budgeted_changes), 3),
        "mean_movement_saving_vs_budgeted_greedy": round(statistics.mean(movement_savings), 3),
        "mean_reassignment_rate": round(mean_changes / mean_workers, 4),
        "mean_workers_considered": round(mean_workers, 3),
        "mean_selective_decisions": round(statistics.mean(decisions), 3),
        "mean_rl_vetoes": round(statistics.mean(vetoes), 3),
        "mean_shield_blocked_vetoes": round(statistics.mean(blocked_vetoes), 3),
        "fallback_rate_pct": round(100.0 * statistics.mean(fallbacks), 3),
        "veto_confidence_threshold": round(float(veto_confidence_threshold), 3),
        "mean_raw_policy_vetoes": round(statistics.mean(raw_policy_vetoes), 3),
        "mean_low_confidence_vetoes_overridden": round(
            statistics.mean(low_confidence_veto_overrides), 3
        ),
        "mean_applied_high_confidence_vetoes": round(
            statistics.mean(applied_high_confidence_vetoes), 3
        ),
        "constraint_violations": int(violations),
        "selective_hybrid_model_schema_version": SELECTIVE_HYBRID_MODEL_SCHEMA_VERSION,
        "training_strategy": SELECTIVE_HYBRID_TRAINING_STRATEGY,
        "safety_fallback_available": True,
        "robust_score": 0.0,
        "evaluation_note": (
            "Budgeted dynamic greedy is the default. RL may veto only when its masked action probability exceeds "
            "the calibrated high-confidence threshold; otherwise the greedy decision is kept. Hard movement budgets "
            "and a conservative global fallback remain active. Operational approval still requires shadow mode."
        ),
    }
    result["robust_score"] = round(_robust_score(result), 5)
    return result


def _validation_threshold_is_safe(metrics: dict[str, Any]) -> bool:
    adds_value = (
        float(metrics.get("mean_gain_vs_budgeted_dynamic_greedy_pct_points", -999.0))
        >= MIN_VALUE_ADD_GAIN
        or float(metrics.get("mean_movement_saving_vs_budgeted_greedy", -999.0))
        >= MIN_VALUE_ADD_MOVE_SAVING
    )
    return bool(
        float(metrics.get("mean_gain_vs_budgeted_dynamic_greedy_pct_points", -999.0))
        >= MIN_GAIN_VS_BUDGETED_GREEDY
        and float(metrics.get("bootstrap_95pct_gain_vs_budgeted_lower", -999.0))
        >= MIN_BOOTSTRAP_LOWER_VS_BUDGETED
        and float(metrics.get("p10_gain_vs_budgeted_dynamic_greedy_pct_points", -999.0))
        >= MIN_P10_VS_BUDGETED
        and float(metrics.get("noninferior_rate_vs_budgeted_dynamic_greedy_pct", 0.0))
        >= MIN_NONINFERIOR_RATE_VS_BUDGETED
        and adds_value
    )


def _threshold_selection_key(metrics: dict[str, Any]) -> tuple[float, ...]:
    return (
        float(_validation_threshold_is_safe(metrics)),
        float(metrics.get("noninferior_rate_vs_budgeted_dynamic_greedy_pct", 0.0)),
        float(metrics.get("bootstrap_95pct_gain_vs_budgeted_lower", -999.0)),
        float(metrics.get("mean_gain_vs_budgeted_dynamic_greedy_pct_points", -999.0)),
        float(metrics.get("mean_movement_saving_vs_budgeted_greedy", -999.0)),
        float(metrics.get("robust_score", -999.0)),
        float(metrics.get("veto_confidence_threshold", 0.0)),
    )


def calibrate_veto_confidence_threshold(
    data: WorkforceData,
    model: MaskablePPO,
    *,
    dates: list[str],
    episodes: int,
    seed: int,
    difficulty: str = "full",
) -> tuple[float, dict[str, Any], list[dict[str, Any]]]:
    reports: list[dict[str, Any]] = []
    for index, threshold in enumerate(VETO_CONFIDENCE_THRESHOLD_GRID):
        report = evaluate_selective_hybrid_policy(
            data,
            model,
            dates=dates,
            episodes=max(40, int(episodes)),
            seed=int(seed),
            difficulty=difficulty,
            evaluation_label="validation",
            veto_confidence_threshold=float(threshold),
        )
        reports.append(report)
    selected = max(reports, key=_threshold_selection_key)
    return (
        float(selected["veto_confidence_threshold"]),
        selected,
        reports,
    )


def _candidate_selection_key(report: dict[str, Any]) -> tuple[float, ...]:
    return _threshold_selection_key(report["validation"])


def _new_model(env, *, seed: int, device: str) -> MaskablePPO:
    def learning_rate(progress_remaining: float) -> float:
        return 2.0e-5 + (1.2e-4 - 2.0e-5) * float(progress_remaining)

    return MaskablePPO(
        "MlpPolicy",
        env,
        learning_rate=learning_rate,
        n_steps=2048,
        batch_size=512,
        n_epochs=8,
        gamma=0.995,
        gae_lambda=0.95,
        ent_coef=0.012,
        vf_coef=0.65,
        clip_range=0.16,
        max_grad_norm=0.45,
        normalize_advantage=True,
        target_kl=0.020,
        policy_kwargs={
            "activation_fn": torch.nn.SiLU,
            "ortho_init": False,
            "net_arch": {"pi": [256, 256, 128], "vf": [256, 256, 128]},
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
    first_env = make_selective_vector_env(
        data, training_dates, seed=seed, difficulty="easy", env_count=env_count
    )
    model = _new_model(first_env, seed=seed, device=device)
    best_score = -1e9
    best_path = directory / f"selective_candidate_{seed}_best.zip"
    phase_report: list[dict[str, Any]] = []
    total_steps = 0
    for phase_number, (difficulty, steps) in enumerate(phases, start=1):
        if steps <= 0:
            continue
        environment = make_selective_vector_env(
            data,
            training_dates,
            seed=seed + phase_number * 100_003,
            difficulty=difficulty,
            env_count=env_count,
        )
        model.set_env(environment)
        model.learn(total_timesteps=int(steps), reset_num_timesteps=False, progress_bar=False)
        total_steps += int(steps)
        checkpoint = evaluate_selective_hybrid_policy(
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
    final_env = make_selective_vector_env(
        data, training_dates, seed=seed + 999_983, difficulty="mixed", env_count=env_count
    )
    best_model = MaskablePPO.load(str(best_path), env=final_env, device=device)
    selected_threshold, validation, threshold_calibration = calibrate_veto_confidence_threshold(
        data,
        best_model,
        dates=validation_dates,
        episodes=max(60, int(validation_episodes)),
        seed=seed + 700_001,
        difficulty="full",
    )
    return best_model, {
        "seed": int(seed),
        "total_timesteps": int(total_steps),
        "validation": validation,
        "selected_veto_confidence_threshold": selected_threshold,
        "threshold_calibration": threshold_calibration,
        "phases": phase_report,
        "selected_checkpoint": best_path.name,
    }


def train_selective_hybrid_policy(
    data: WorkforceData,
    output_path: Path,
    *,
    seed: int = 42,
    device: str = "cuda",
    env_count: int = 4,
    easy_steps: int = 100_000,
    medium_steps: int = 150_000,
    full_steps: int = 250_000,
    mixed_steps: int = 200_000,
    validation_days: int = 120,
    test_days: int = 180,
    evaluation_episodes: int = 240,
    stress_episodes: int = 120,
    candidate_seeds: int = 3,
) -> dict[str, Any]:
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but PyTorch cannot access an NVIDIA GPU")
    training_dates, validation_dates, test_dates = temporal_three_way_split(
        data, validation_days=validation_days, test_days=test_days
    )
    if len(training_dates) < 365:
        raise RuntimeError("Selective hybrid RL requires at least one year of training dates")
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
    with tempfile.TemporaryDirectory(prefix="tte-selective-hybrid-") as temp:
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
            key=lambda index: _candidate_selection_key(candidate_reports[index]),
        )
        model = candidate_models[selected_index]
        selected_report = candidate_reports[selected_index]
        selected_threshold = float(
            selected_report.get(
                "selected_veto_confidence_threshold",
                DEFAULT_VETO_CONFIDENCE_THRESHOLD,
            )
        )
        full_test = evaluate_selective_hybrid_policy(
            data,
            model,
            dates=test_dates,
            episodes=evaluation_episodes,
            seed=int(seed) + 9_000_001,
            difficulty="full",
            evaluation_label="test",
            veto_confidence_threshold=selected_threshold,
        )
        extreme_test = evaluate_selective_hybrid_policy(
            data,
            model,
            dates=test_dates,
            episodes=stress_episodes,
            seed=int(seed) + 19_000_003,
            difficulty="extreme",
            evaluation_label="test",
            veto_confidence_threshold=selected_threshold,
        )
        metrics = dict(full_test)
        metrics.update({
            "selected_candidate_index": int(selected_index),
            "selected_candidate_seed": int(selected_report["seed"]),
            "selected_veto_confidence_threshold": selected_threshold,
            "confidence_threshold_calibration": selected_report.get("threshold_calibration", []),
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
            "dynamic_environment_sha256": _sha256_file(Path(__file__).with_name("dynamic_environment.py")),
            "selective_environment_sha256": _sha256_file(Path(__file__).with_name("selective_environment.py")),
            "selective_policy_sha256": _sha256_file(Path(__file__).with_name("selective_policy.py")),
            "selective_training_sha256": _sha256_file(Path(__file__)),
            "shadow_mode_approved": False,
            "architecture": {
                "primary_planner": "budgeted dynamic greedy with CP-SAT morning plan",
                "rl_role": "very-high-confidence veto gate; greedy is kept when RL confidence is below the calibrated threshold",
                "selected_veto_confidence_threshold": selected_threshold,
                "threshold_candidates": list(VETO_CONFIDENCE_THRESHOLD_GRID),
                "maximum_move_rate": 0.15,
                "maximum_total_moves": 15,
                "maximum_moves_per_round": 10,
                "conservative_global_fallback": True,
                "future_reference_metrics_in_observation": False,
            },
        })
        metrics["constraint_violations"] = int(full_test["constraint_violations"]) + int(extreme_test["constraint_violations"])
        metrics["approval_gate"] = selective_hybrid_approval_gate(metrics)
        metrics["approved"] = all(metrics["approval_gate"].values())

        output_path.parent.mkdir(parents=True, exist_ok=True)
        metrics_path = output_path.with_name("selective_hybrid_training_metrics.json")
        rejected_path = output_path.with_name("selective_hybrid_training_rejected.json")
        if metrics["approved"]:
            candidate = output_path.with_name(f"{output_path.stem}.candidate.zip")
            candidate.unlink(missing_ok=True)
            model.save(str(candidate))
            if output_path.exists():
                backup_dir = output_path.parent / "selective-hybrid-backup" / time.strftime("%Y%m%d-%H%M%S")
                backup_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(output_path, backup_dir / output_path.name)
                if metrics_path.exists():
                    shutil.copy2(metrics_path, backup_dir / metrics_path.name)
            os.replace(candidate, output_path)
            metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
            rejected_path.unlink(missing_ok=True)
        else:
            rejected_candidate = output_path.with_name(
                "selective_hybrid_rejected_candidate.zip"
            )
            rejected_candidate.unlink(missing_ok=True)
            model.save(str(rejected_candidate))
            rejected_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        return metrics
