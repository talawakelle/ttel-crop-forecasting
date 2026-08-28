from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import json
import os
import shutil
import statistics
import time

import numpy as np
from sb3_contrib import MaskablePPO
from stable_baselines3.common.callbacks import BaseCallback
import torch

from .baseline import greedy_allocate
from .data import WorkforceData
from .environment import WorkforceAllocationEnv
from .policy import rollout_plan
from .version import MODEL_SCHEMA_VERSION, TRAINING_STRATEGY


MIN_MEAN_GAIN_PCT_POINTS = 0.10
MIN_WIN_RATE_PCT = 52.0
MIN_P10_DIFFERENCE_PCT_POINTS = -3.0


def _policy_rank(metrics: dict) -> tuple:
    return (
        -int(metrics["rl_constraint_violations"]),
        bool(metrics.get("approved")),
        float(metrics["rl_minus_greedy_pct_points"]),
        float(metrics.get("rl_win_rate_pct", 0.0)),
        float(metrics["rl_mean_coverage_pct"]),
    )


def _planning_date(data: WorkforceData, offset: int) -> str:
    state_as_of = data.forecast_status().get("state_as_of")
    try:
        start = date.fromisoformat(str(state_as_of)) + timedelta(days=1)
    except ValueError:
        start = date.today()
    return (start + timedelta(days=int(offset) % 60)).isoformat()


def forecast_training_fingerprint(data: WorkforceData) -> dict:
    status = data.forecast_status(_planning_date(data, 1))
    forecaster = data.forecaster
    metadata = getattr(forecaster, "metadata", None) or {}
    return {
        "forecast_ready_during_training": bool(status.get("ready")),
        "forecast_eligible_during_training": bool(status.get("eligible_for_planning_date")),
        "forecast_method_during_training": status.get("method"),
        "forecast_profile_source_sha256": metadata.get("profile_source_sha256"),
        "forecast_base_model_sha256": metadata.get("base_model_sha256") or metadata.get("model_sha256"),
        "forecast_metrics_state_sha256": metadata.get("state_sha256"),
        "forecast_feature_schema_version": metadata.get("feature_schema_version"),
        "forecast_test_mae_kg": status.get("test_mae_kg"),
        "forecast_baseline_test_mae_kg": status.get("baseline_test_mae_kg"),
        "forecast_mae_improvement_pct": status.get("mae_improvement_pct"),
    }


def approval_gate(metrics: dict) -> dict[str, bool]:
    return {
        "zero_hard_constraint_violations": int(metrics["rl_constraint_violations"]) == 0,
        "mean_coverage_beats_greedy": float(metrics["rl_minus_greedy_pct_points"]) >= MIN_MEAN_GAIN_PCT_POINTS,
        "paired_win_rate": float(metrics.get("rl_win_rate_pct", 0.0)) >= MIN_WIN_RATE_PCT,
        "tail_underperformance_bounded": float(metrics.get("difference_p10_pct_points", -999.0)) >= MIN_P10_DIFFERENCE_PCT_POINTS,
        "forecast_active": bool(metrics.get("forecast_ready_during_training"))
        and bool(metrics.get("forecast_eligible_during_training")),
    }


class CoverageCheckpointCallback(BaseCallback):
    """Keep the strongest periodic policy on fixed forecast-aware scenarios."""

    def __init__(
        self,
        data: WorkforceData,
        checkpoint_path: Path,
        eval_freq: int,
        evaluation_seed: int,
    ):
        super().__init__(verbose=0)
        self.data = data
        self.checkpoint_path = checkpoint_path
        self.eval_freq = max(1, int(eval_freq))
        self.evaluation_seed = int(evaluation_seed)
        self.next_evaluation = self.eval_freq
        self.best_metrics: dict | None = None

    def _on_step(self) -> bool:
        if self.num_timesteps < self.next_evaluation:
            return True
        metrics = evaluate_policy(
            self.data,
            self.model,
            episodes=16,
            seed=self.evaluation_seed,
            rollouts=8,
        )
        print(json.dumps({"checkpoint_timesteps": self.num_timesteps, **metrics}, indent=2), flush=True)
        if self.best_metrics is None or _policy_rank(metrics) > _policy_rank(self.best_metrics):
            self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            self.model.save(str(self.checkpoint_path))
            self.best_metrics = {"timesteps": self.num_timesteps, **metrics}
        while self.next_evaluation <= self.num_timesteps:
            self.next_evaluation += self.eval_freq
        return True


def train_policy(
    data: WorkforceData,
    model_path: Path,
    timesteps: int = 200_000,
    seed: int = 42,
    device: str = "auto",
    evaluation_seed: int = 1042,
    evaluation_episodes: int = 60,
    evaluation_rollouts: int = 32,
) -> dict:
    if data.forecaster is None or not data.forecast_status(_planning_date(data, 1)).get("eligible_for_planning_date"):
        raise RuntimeError(
            "Forecast-aware RL training requires an approved CatBoost model. "
            "Train or restore productivity_catboost.cbm and productivity_metrics.json first."
        )
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA training was requested, but PyTorch cannot access an NVIDIA GPU. "
            "Run setup_gpu_windows.ps1 and verify the NVIDIA driver."
        )
    resolved_device = "cuda" if device == "cuda" else device
    environment = WorkforceAllocationEnv(data, seed=seed)

    def learning_rate(progress_remaining: float) -> float:
        return 2e-5 + (2.5e-4 - 2e-5) * float(progress_remaining)

    def clip_range(progress_remaining: float) -> float:
        return 0.08 + (0.20 - 0.08) * float(progress_remaining)

    model = MaskablePPO(
        "MlpPolicy",
        environment,
        learning_rate=learning_rate,
        clip_range=clip_range,
        n_steps=8192,
        batch_size=1024,
        n_epochs=10,
        gamma=0.997,
        gae_lambda=0.98,
        ent_coef=0.006,
        vf_coef=0.70,
        max_grad_norm=0.50,
        normalize_advantage=True,
        policy_kwargs={"net_arch": {"pi": [384, 256, 128], "vf": [384, 256, 128]}},
        seed=seed,
        verbose=1,
        device=resolved_device,
    )
    started = time.time()
    checkpoint_path = model_path.with_name(f"{model_path.stem}_best_checkpoint.zip")
    checkpoint_path.unlink(missing_ok=True)
    checkpoint = CoverageCheckpointCallback(
        data,
        checkpoint_path,
        eval_freq=max(50_000, int(timesteps) // 6),
        evaluation_seed=evaluation_seed,
    )
    model.learn(total_timesteps=int(timesteps), progress_bar=False, callback=checkpoint)
    final_metrics = evaluate_policy(
        data,
        model,
        episodes=evaluation_episodes,
        seed=evaluation_seed,
        rollouts=evaluation_rollouts,
    )
    selected_model = model
    selected_metrics = final_metrics
    selection_details: dict[str, object] = {
        "selected": "final policy",
        "final_difference_pct_points": final_metrics["rl_minus_greedy_pct_points"],
    }
    if checkpoint_path.exists():
        checkpoint_model = MaskablePPO.load(str(checkpoint_path), env=environment, device=resolved_device)
        checkpoint_metrics = evaluate_policy(
            data,
            checkpoint_model,
            episodes=evaluation_episodes,
            seed=evaluation_seed,
            rollouts=evaluation_rollouts,
        )
        selection_details.update({
            "checkpoint_timesteps": checkpoint.best_metrics.get("timesteps") if checkpoint.best_metrics else None,
            "checkpoint_difference_pct_points": checkpoint_metrics["rl_minus_greedy_pct_points"],
        })
        if _policy_rank(checkpoint_metrics) > _policy_rank(final_metrics):
            selected_model = checkpoint_model
            selected_metrics = checkpoint_metrics
            selection_details["selected"] = "best periodic checkpoint"

    metrics = dict(selected_metrics)
    metrics.update(forecast_training_fingerprint(data))
    gate = approval_gate(metrics)
    approved = all(gate.values())
    metrics.update({
        "approved": approved,
        "approval_gate": gate,
        "minimum_mean_gain_pct_points": MIN_MEAN_GAIN_PCT_POINTS,
        "minimum_win_rate_pct": MIN_WIN_RATE_PCT,
        "minimum_p10_difference_pct_points": MIN_P10_DIFFERENCE_PCT_POINTS,
        "timesteps": int(timesteps),
        "seed": seed,
        "training_seconds": round(time.time() - started, 2),
        "model_path": model_path.name if approved else None,
        "training_device": str(model.device),
        "gpu_name": torch.cuda.get_device_name(0) if str(model.device).startswith("cuda") else None,
        "pytorch_version": torch.__version__,
        "profile_source_sha256": data.metadata.get("source_sha256"),
        "profile_source_name": data.metadata.get("source_name"),
        "profile_date_min": data.metadata.get("date_min"),
        "profile_date_max": data.metadata.get("date_max"),
        "profile_rows_used": data.metadata.get("source_rows_used"),
        "model_schema_version": MODEL_SCHEMA_VERSION,
        "training_strategy": TRAINING_STRATEGY,
        "evaluation_seed": int(evaluation_seed),
        "within_seed_selection": selection_details,
        "safety_note": (
            "A model is activated only when it has zero hard-constraint violations, "
            "beats the greedy policy on paired scenarios, and uses the approved forecast fingerprint."
        ),
    })

    model_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path = model_path.with_name("training_metrics.json")
    rejected_path = model_path.with_name("training_rejected_metrics.json")
    if approved:
        candidate_path = model_path.with_name(f"{model_path.stem}.candidate.zip")
        candidate_path.unlink(missing_ok=True)
        selected_model.save(str(candidate_path))
        if model_path.exists():
            backup_dir = model_path.parent / "rl-backup" / time.strftime("%Y%m%d-%H%M%S")
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(model_path, backup_dir / model_path.name)
            if metadata_path.exists():
                shutil.copy2(metadata_path, backup_dir / metadata_path.name)
        os.replace(candidate_path, model_path)
        metadata_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        rejected_path.unlink(missing_ok=True)
    else:
        rejected_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    checkpoint_path.unlink(missing_ok=True)
    return metrics


def evaluate_policy(
    data: WorkforceData,
    model: MaskablePPO,
    episodes: int = 100,
    seed: int = 1042,
    rollouts: int = 32,
) -> dict:
    rl_coverages: list[float] = []
    greedy_coverages: list[float] = []
    rl_violations = 0
    greedy_violations = 0
    evaluation_dates = data.complete_dates
    for episode in range(int(episodes)):
        if episodes <= 1:
            date_index = len(evaluation_dates) - 1
        else:
            date_index = round(episode * (len(evaluation_dates) - 1) / (int(episodes) - 1))
        scenario = data.create_scenario(
            template_date=evaluation_dates[date_index],
            planning_date=_planning_date(data, episode),
            attendance_rate=0.68 + (episode % 9) * 0.04,
            demand_multiplier=0.80 + (episode % 9) * 0.06,
            same_division_only=episode % 4 != 0,
            seed=seed + episode,
        )
        rl_plan = rollout_plan(data, scenario, model, rollouts=rollouts)
        greedy_plan = greedy_allocate(data, scenario)
        rl_coverages.append(float(rl_plan["metrics"]["coverage_pct"]))
        greedy_coverages.append(float(greedy_plan["metrics"]["coverage_pct"]))
        rl_violations += int(rl_plan["metrics"]["constraint_violations"])
        greedy_violations += int(greedy_plan["metrics"]["constraint_violations"])
    differences = np.asarray([rl - greedy for rl, greedy in zip(rl_coverages, greedy_coverages)], dtype=float)
    forecast = forecast_training_fingerprint(data)
    result = {
        "evaluation_episodes": int(episodes),
        "rl_mean_coverage_pct": round(statistics.mean(rl_coverages), 2),
        "greedy_mean_coverage_pct": round(statistics.mean(greedy_coverages), 2),
        "rl_minus_greedy_pct_points": round(float(differences.mean()), 2),
        "rl_median_difference_pct_points": round(float(np.median(differences)), 2),
        "difference_p10_pct_points": round(float(np.quantile(differences, 0.10)), 2),
        "difference_p90_pct_points": round(float(np.quantile(differences, 0.90)), 2),
        "worst_difference_pct_points": round(float(differences.min()), 2),
        "rl_win_rate_pct": round(100.0 * float(np.mean(differences > 0.0)), 2),
        "rl_tie_or_win_rate_pct": round(100.0 * float(np.mean(differences >= 0.0)), 2),
        "rl_constraint_violations": rl_violations,
        "greedy_constraint_violations": greedy_violations,
        "evaluation_scope": (
            "paired forecast-aware counterfactual scenarios sampled evenly across complete historical workdays "
            f"from {evaluation_dates[0]} to {evaluation_dates[-1]}"
        ),
        "rl_inference": f"best of {max(1, int(rollouts))} deterministic masked-policy rollouts",
        "model_schema_version": MODEL_SCHEMA_VERSION,
        **forecast,
    }
    gate = approval_gate(result)
    result["approval_gate"] = gate
    result["approved"] = all(gate.values())
    return result
