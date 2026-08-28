from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import random
import shutil
import tempfile
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn


VERSION = "10.0.0"
FEATURE_COUNT = 10
OPERATIONAL_STATUS = "DEVELOPMENT_TRAINING_ONLY"


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(clean(value).replace(",", ""))
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def integer(value: Any, default: int = 0) -> int:
    return int(round(number(value, float(default))))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


class QNetwork(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(FEATURE_COUNT, 64),
            nn.ReLU(),
            nn.LayerNorm(64),
            nn.Linear(64, 64),
            nn.ReLU(),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
        )

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.network(features).squeeze(-1)


def safe_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered = [
        action
        for action in actions
        if clean(action.get("safe_action")).upper() == "YES"
    ]
    if not any(
        clean(action.get("action_type")).upper() == "NO_OP"
        for action in filtered
    ):
        filtered.append({
            "action_id": "NO_OP",
            "action_type": "NO_OP",
            "safe_action": "YES",
            "projected_reward": 0.0,
            "projected_under_change_kg": 0.0,
            "projected_over_change_kg": 0.0,
        })
    return filtered


def action_features(
    state: dict[str, Any],
    action: dict[str, Any],
    max_moves: int,
) -> np.ndarray:
    target = max(number(state.get("total_target_crop_kg")), 1.0)
    action_type = clean(action.get("action_type")).upper()
    scenario = clean(state.get("scenario")).upper()

    source = clean(action.get("source_field_uid"))
    target_field = clean(action.get("target_field_uid"))

    return np.asarray([
        number(state.get("total_under_kg")) / target,
        number(state.get("total_over_kg")) / target,
        number(state.get("move_count")) / max(max_moves, 1),
        number(action.get("projected_reward")) / target,
        number(action.get("projected_under_change_kg")) / target,
        number(action.get("projected_over_change_kg")) / target,
        1.0 if action_type == "NO_OP" else 0.0,
        1.0 if action_type == "MOVE" else 0.0,
        1.0 if source and target_field and source != target_field else 0.0,
        1.0 if scenario == "CONSERVATIVE" else 0.0,
    ], dtype=np.float32)


def attach_features(
    state: dict[str, Any],
    actions: list[dict[str, Any]],
    max_moves: int,
) -> list[tuple[dict[str, Any], np.ndarray]]:
    return [
        (action, action_features(state, action, max_moves))
        for action in safe_actions(actions)
    ]


def model_values(
    model: QNetwork,
    featured_actions: list[tuple[dict[str, Any], np.ndarray]],
    device: torch.device,
) -> torch.Tensor:
    feature_matrix = np.stack(
        [features for _, features in featured_actions]
    )
    tensor = torch.from_numpy(feature_matrix).float().to(device)
    with torch.no_grad():
        return model(tensor)


def greedy_action(
    featured_actions: list[tuple[dict[str, Any], np.ndarray]],
) -> tuple[dict[str, Any], np.ndarray]:
    positive = [
        item
        for item in featured_actions
        if clean(item[0].get("action_type")).upper() != "NO_OP"
        and number(item[0].get("projected_reward")) > 0.0
    ]
    if positive:
        return max(
            positive,
            key=lambda item: number(
                item[0].get("projected_reward")
            ),
        )
    return next(
        item
        for item in featured_actions
        if clean(item[0].get("action_type")).upper() == "NO_OP"
    )


def choose_training_action(
    model: QNetwork,
    featured_actions: list[tuple[dict[str, Any], np.ndarray]],
    device: torch.device,
    epsilon: float,
    rng: random.Random,
) -> tuple[dict[str, Any], np.ndarray]:
    if rng.random() < epsilon:
        return rng.choice(featured_actions)

    values = model_values(model, featured_actions, device)
    return featured_actions[int(torch.argmax(values).item())]


def safe_env_step(
    env: Any,
    action_id: str,
) -> tuple[dict[str, Any], float, bool, dict[str, Any]]:
    """Support NO_OP when an older v9 environment does not expose it."""

    if clean(action_id).upper() == "NO_OP":
        if hasattr(env, "terminated"):
            env.terminated = True

        state = env.state()

        return (
            state,
            0.0,
            True,
            {
                "accepted": True,
                "reason": "TRAINER_NO_OP_TERMINATED",
            },
        )

    return env.step(action_id)


def run_policy(
    env: Any,
    episode_id: str,
    shock_id: str,
    policy: str,
    model: QNetwork,
    device: torch.device,
    max_moves: int,
    hybrid_ratio: float,
) -> dict[str, Any]:
    initial = env.reset(episode_id, shock_id)
    total_reward = 0.0
    rl_actions = 0
    greedy_fallbacks = 0
    safety_violations = 0

    for _ in range(max_moves + 1):
        state = env.state()
        featured = attach_features(
            state, env.valid_actions(), max_moves
        )
        greedy = greedy_action(featured)

        if policy == "GREEDY":
            selected = greedy
        else:
            values = model_values(model, featured, device)
            rl_selected = featured[int(torch.argmax(values).item())]

            if policy == "RL_ONLY":
                selected = rl_selected
                if clean(selected[0].get("action_type")).upper() != "NO_OP":
                    rl_actions += 1
            elif policy == "HYBRID":
                greedy_reward = max(
                    0.0, number(greedy[0].get("projected_reward"))
                )
                rl_reward = number(
                    rl_selected[0].get("projected_reward")
                )
                rl_is_move = (
                    clean(rl_selected[0].get("action_type")).upper()
                    != "NO_OP"
                )
                if (
                    rl_is_move
                    and rl_reward > 0.0
                    and rl_reward >= greedy_reward * hybrid_ratio
                ):
                    selected = rl_selected
                    rl_actions += 1
                else:
                    selected = greedy
                    if (
                        clean(greedy[0].get("action_type")).upper()
                        != "NO_OP"
                    ):
                        greedy_fallbacks += 1
            else:
                raise ValueError(f"Unknown policy: {policy}")

        _, reward, done, info = safe_env_step(env, 
            clean(selected[0].get("action_id"))
        )
        total_reward += number(reward)
        if not info.get("accepted", False):
            safety_violations += 1
        if done:
            break

    final = env.state()
    initial_objective = (
        1000.0 * number(initial.get("total_under_kg"))
        + 10.0 * number(initial.get("total_over_kg"))
    )
    final_objective = (
        1000.0 * number(final.get("total_under_kg"))
        + 10.0 * number(final.get("total_over_kg"))
        + number(final.get("move_count"))
    )

    return {
        "episode_id": episode_id,
        "shock_id": shock_id,
        "scenario": clean(final.get("scenario")),
        "estate": clean(final.get("estate")),
        "policy": policy,
        "initial_under_kg": round(
            number(initial.get("total_under_kg")), 4
        ),
        "final_under_kg": round(
            number(final.get("total_under_kg")), 4
        ),
        "initial_over_kg": round(
            number(initial.get("total_over_kg")), 4
        ),
        "final_over_kg": round(
            number(final.get("total_over_kg")), 4
        ),
        "initial_objective": round(initial_objective, 4),
        "final_objective": round(final_objective, 4),
        "objective_improvement": round(
            initial_objective - final_objective, 4
        ),
        "moves": integer(final.get("move_count")),
        "rl_actions_used": rl_actions,
        "greedy_fallbacks": greedy_fallbacks,
        "total_reward": round(total_reward, 4),
        "safety_violations": safety_violations,
        "duplicate_assignments": integer(
            final.get("duplicate_assignments")
        ),
    }


def import_real_environment(manifest_path: Path) -> Any:
    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    code_path = Path(manifest["environment_code_path"])
    spec = importlib.util.spec_from_file_location(
        "tte_workforce_rl_env_runtime", code_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"Unable to import environment code: {code_path}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.TTEWorkforceRLEnvironment


class MockEnvironment:
    """Small internal environment used only by --self-test."""

    def __init__(
        self,
        _manifest: Path,
        max_moves: int,
        max_actions: int,
        safety_under_tolerance_kg: float,
    ) -> None:
        self.max_moves = max_moves
        self._episodes = [
            f"EP_{index:03d}"
            for index in range(1, 67)
        ]
        self.current_episode = ""
        self.current_shock = ""
        self.under = 0.0
        self.over = 0.0
        self.moves = 0
        self.done = False

    def episode_ids(self) -> list[str]:
        return self._episodes

    def shock_ids(self, episode_id: str) -> list[str]:
        return [
            "SHOCK_00_BASELINE",
            "SHOCK_01",
            "SHOCK_02",
            "SHOCK_03",
            "SHOCK_04",
            "SHOCK_05",
        ]

    def reset(
        self, episode_id: str, shock_id: str
    ) -> dict[str, Any]:
        self.current_episode = episode_id
        self.current_shock = shock_id
        self.moves = 0
        self.done = False
        self.under = (
            0.0
            if shock_id == "SHOCK_00_BASELINE"
            else 10.0
        )
        self.over = 2.0
        return self.state()

    def state(self) -> dict[str, Any]:
        return {
            "episode_id": self.current_episode,
            "shock_id": self.current_shock,
            "scenario": (
                "CONSERVATIVE"
                if int(self.current_episode.split("_")[1]) <= 33
                else "EXPECTED"
            ),
            "estate": self.current_episode,
            "total_target_crop_kg": 1000.0,
            "total_under_kg": self.under,
            "total_over_kg": self.over,
            "move_count": self.moves,
            "duplicate_assignments": 0,
            "terminated": self.done,
        }

    def valid_actions(self) -> list[dict[str, Any]]:
        if self.done:
            return []
        actions = [{
            "action_id": "NO_OP",
            "action_type": "NO_OP",
            "safe_action": "YES",
            "projected_reward": 0.0,
            "projected_under_change_kg": 0.0,
            "projected_over_change_kg": 0.0,
            "source_field_uid": "",
            "target_field_uid": "",
        }]
        if self.under > 0.0:
            actions.extend([
                {
                    "action_id": "MOVE_BEST",
                    "action_type": "MOVE",
                    "safe_action": "YES",
                    "projected_reward": 1999.0,
                    "projected_under_change_kg": -2.0,
                    "projected_over_change_kg": 0.0,
                    "source_field_uid": "F1",
                    "target_field_uid": "F2",
                },
                {
                    "action_id": "MOVE_SECOND",
                    "action_type": "MOVE",
                    "safe_action": "YES",
                    "projected_reward": 999.0,
                    "projected_under_change_kg": -1.0,
                    "projected_over_change_kg": 0.0,
                    "source_field_uid": "F1",
                    "target_field_uid": "F2",
                },
            ])
        return actions

    def step(
        self, action_id: str
    ) -> tuple[dict[str, Any], float, bool, dict[str, Any]]:
        if action_id == "NO_OP":
            self.done = True
            return self.state(), 0.0, True, {
                "accepted": True,
                "reason": "NO_OP",
            }
        if action_id == "MOVE_BEST":
            self.under = max(0.0, self.under - 2.0)
            reward = 1999.0
        elif action_id == "MOVE_SECOND":
            self.under = max(0.0, self.under - 1.0)
            reward = 999.0
        else:
            return self.state(), -1000.0, False, {
                "accepted": False,
                "reason": "UNKNOWN_ACTION",
            }
        self.moves += 1
        if self.moves >= self.max_moves or self.under <= 0.0:
            self.done = True
        return self.state(), reward, self.done, {
            "accepted": True,
            "reason": "MOVE",
        }


def train_and_evaluate(
    env: Any,
    output_root: Path,
    seed: int,
    warmup_epochs: int,
    training_epochs: int,
    max_moves: int,
    batch_size: int,
    gamma: float,
    learning_rate: float,
    hybrid_ratio: float,
    required_noninferiority_pct: float,
) -> dict[str, Any]:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

    device = torch.device(
        "cuda" if torch.cuda.is_available() else "cpu"
    )
    model = QNetwork().to(device)
    target_model = QNetwork().to(device)
    target_model.load_state_dict(model.state_dict())

    episode_ids = env.episode_ids()
    if len(episode_ids) != 66:
        raise RuntimeError(
            f"Expected 66 episodes but found {len(episode_ids)}."
        )

    training_pairs: list[tuple[str, str]] = []
    validation_pairs: list[tuple[str, str]] = []
    baseline_pairs: list[tuple[str, str]] = []

    for episode_id in episode_ids:
        for shock_id in env.shock_ids(episode_id):
            if shock_id == "SHOCK_00_BASELINE":
                baseline_pairs.append((episode_id, shock_id))
            elif shock_id == "SHOCK_05":
                validation_pairs.append((episode_id, shock_id))
            else:
                training_pairs.append((episode_id, shock_id))

    if len(validation_pairs) != 66:
        raise RuntimeError(
            f"Expected 66 validation pairs but found "
            f"{len(validation_pairs)}."
        )

    run_folder = output_root / datetime.now().strftime(
        "safe_rl_training_%Y%m%d_%H%M%S"
    )
    model_dir = run_folder / "models"
    training_dir = run_folder / "training"
    evaluation_dir = run_folder / "evaluation"
    quality_dir = run_folder / "quality"
    for folder in (
        model_dir,
        training_dir,
        evaluation_dir,
        quality_dir,
    ):
        folder.mkdir(parents=True, exist_ok=True)

    print(f"Safe development RL training: {run_folder}")
    print(f"Device: {device}")
    print(f"Training pairs: {len(training_pairs)}")
    print(f"Validation pairs: {len(validation_pairs)}")
    print("No live allocation or deployment will run.")

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=learning_rate,
        weight_decay=1e-5,
    )
    loss_function = nn.SmoothL1Loss()

    warm_features: list[np.ndarray] = []
    warm_targets: list[float] = []
    for episode_id, shock_id in training_pairs:
        env.reset(episode_id, shock_id)
        for _ in range(min(3, max_moves)):
            state = env.state()
            featured = attach_features(
                state, env.valid_actions(), max_moves
            )
            target_scale = max(
                number(state.get("total_target_crop_kg")), 1.0
            )
            for action, features in featured:
                warm_features.append(features)
                warm_targets.append(
                    float(np.clip(
                        number(action.get("projected_reward"))
                        / target_scale,
                        -20.0,
                        20.0,
                    ))
                )
            selected = greedy_action(featured)
            _, _, done, _ = safe_env_step(env, 
                clean(selected[0].get("action_id"))
            )
            if done:
                break

    warm_x = torch.from_numpy(
        np.stack(warm_features)
    ).float()
    warm_y = torch.tensor(
        warm_targets, dtype=torch.float32
    )

    history: list[dict[str, Any]] = []
    for epoch in range(1, warmup_epochs + 1):
        permutation = torch.randperm(len(warm_x))
        total_loss = 0.0
        batches = 0
        model.train()
        for start in range(0, len(warm_x), batch_size):
            indexes = permutation[start : start + batch_size]
            features = warm_x[indexes].to(device)
            targets = warm_y[indexes].to(device)
            predicted = model(features)
            loss = loss_function(predicted, targets)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            total_loss += float(loss.item())
            batches += 1

        history.append({
            "phase": "SAFE_VALUE_WARMUP",
            "epoch": epoch,
            "mean_loss": round(
                total_loss / max(batches, 1), 8
            ),
            "epsilon": "",
            "replay_size": 0,
            "transitions": len(warm_features),
            "safety_violations": 0,
        })

    target_model.load_state_dict(model.state_dict())
    replay: deque[
        tuple[np.ndarray, float, np.ndarray, bool]
    ] = deque(maxlen=50000)
    rng = random.Random(seed)
    global_step = 0

    def update_model() -> float:
        batch = rng.sample(
            list(replay),
            min(batch_size, len(replay)),
        )
        features = torch.from_numpy(
            np.stack([item[0] for item in batch])
        ).float().to(device)
        rewards = torch.tensor(
            [item[1] for item in batch],
            dtype=torch.float32,
            device=device,
        )
        done_tensor = torch.tensor(
            [item[3] for item in batch],
            dtype=torch.float32,
            device=device,
        )

        next_values: list[torch.Tensor] = []
        with torch.no_grad():
            for _, _, next_features, done in batch:
                if done or len(next_features) == 0:
                    next_values.append(
                        torch.tensor(0.0, device=device)
                    )
                else:
                    next_tensor = torch.from_numpy(
                        next_features
                    ).float().to(device)
                    next_values.append(
                        torch.max(target_model(next_tensor))
                    )
        target = (
            rewards
            + gamma
            * (1.0 - done_tensor)
            * torch.stack(next_values)
        )
        predicted = model(features)
        loss = loss_function(predicted, target)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        optimizer.step()
        return float(loss.item())

    for epoch in range(1, training_epochs + 1):
        pairs = list(training_pairs)
        rng.shuffle(pairs)
        epsilon = max(
            0.05,
            0.25
            - (epoch - 1)
            * (0.20 / max(training_epochs - 1, 1)),
        )
        epoch_loss = 0.0
        updates = 0
        transitions = 0
        safety_violations = 0

        for episode_id, shock_id in pairs:
            env.reset(episode_id, shock_id)
            for _ in range(max_moves + 1):
                state = env.state()
                featured = attach_features(
                    state, env.valid_actions(), max_moves
                )
                selected = choose_training_action(
                    model,
                    featured,
                    device,
                    epsilon,
                    rng,
                )
                _, reward, done, info = safe_env_step(env, 
                    clean(selected[0].get("action_id"))
                )
                if not info.get("accepted", False):
                    safety_violations += 1

                next_state = env.state()
                next_featured = (
                    attach_features(
                        next_state,
                        env.valid_actions(),
                        max_moves,
                    )
                    if not done
                    else []
                )
                next_features = (
                    np.stack([
                        features
                        for _, features in next_featured
                    ]).astype(np.float32)
                    if next_featured
                    else np.empty(
                        (0, FEATURE_COUNT),
                        dtype=np.float32,
                    )
                )
                target_scale = max(
                    number(state.get("total_target_crop_kg")),
                    1.0,
                )
                replay.append((
                    selected[1].astype(np.float32),
                    float(np.clip(
                        number(reward) / target_scale,
                        -20.0,
                        20.0,
                    )),
                    next_features,
                    bool(done),
                ))
                transitions += 1
                global_step += 1

                if len(replay) >= batch_size:
                    epoch_loss += update_model()
                    updates += 1
                if global_step % 200 == 0:
                    target_model.load_state_dict(
                        model.state_dict()
                    )
                if done:
                    break

        target_model.load_state_dict(model.state_dict())
        history.append({
            "phase": "SAFE_Q_LEARNING",
            "epoch": epoch,
            "mean_loss": round(
                epoch_loss / max(updates, 1), 8
            ),
            "epsilon": round(epsilon, 4),
            "replay_size": len(replay),
            "transitions": transitions,
            "safety_violations": safety_violations,
        })

    model.eval()
    model_path = model_dir / "safe_action_q_network.pt"
    torch.save({
        "package_version": VERSION,
        "feature_count": FEATURE_COUNT,
        "model_state_dict": model.state_dict(),
        "device_used": str(device),
        "seed": seed,
    }, model_path)

    evaluation_rows: list[dict[str, Any]] = []
    evaluation_pairs = validation_pairs + baseline_pairs
    for episode_id, shock_id in evaluation_pairs:
        for policy in ("GREEDY", "RL_ONLY", "HYBRID"):
            evaluation_rows.append(
                run_policy(
                    env=env,
                    episode_id=episode_id,
                    shock_id=shock_id,
                    policy=policy,
                    model=model,
                    device=device,
                    max_moves=max_moves,
                    hybrid_ratio=hybrid_ratio,
                )
            )

    evaluation_lookup = {
        (
            row["episode_id"],
            row["shock_id"],
            row["policy"],
        ): row
        for row in evaluation_rows
    }

    gate_rows: list[dict[str, Any]] = []
    noninferior = 0
    validation_safety = 0
    validation_duplicates = 0
    baseline_degradation = 0
    rl_actions_used = 0
    greedy_fallbacks = 0

    for episode_id, shock_id in evaluation_pairs:
        greedy = evaluation_lookup[
            (episode_id, shock_id, "GREEDY")
        ]
        rl_only = evaluation_lookup[
            (episode_id, shock_id, "RL_ONLY")
        ]
        hybrid = evaluation_lookup[
            (episode_id, shock_id, "HYBRID")
        ]

        tolerance = max(
            5.0,
            number(greedy["final_objective"]) * 0.01,
        )
        passed = (
            number(hybrid["final_objective"])
            <= number(greedy["final_objective"]) + tolerance
            and number(hybrid["final_under_kg"])
            <= number(greedy["final_under_kg"]) + 0.5
        )
        is_validation = shock_id == "SHOCK_05"

        if is_validation:
            if passed:
                noninferior += 1
            validation_safety += integer(
                hybrid["safety_violations"]
            )
            validation_duplicates += integer(
                hybrid["duplicate_assignments"]
            )
            rl_actions_used += integer(
                hybrid["rl_actions_used"]
            )
            greedy_fallbacks += integer(
                hybrid["greedy_fallbacks"]
            )
        elif not passed:
            baseline_degradation += 1

        gate_rows.append({
            "episode_id": episode_id,
            "shock_id": shock_id,
            "scenario": hybrid["scenario"],
            "estate": hybrid["estate"],
            "greedy_final_objective": (
                greedy["final_objective"]
            ),
            "rl_only_final_objective": (
                rl_only["final_objective"]
            ),
            "hybrid_final_objective": (
                hybrid["final_objective"]
            ),
            "greedy_final_under_kg": (
                greedy["final_under_kg"]
            ),
            "rl_only_final_under_kg": (
                rl_only["final_under_kg"]
            ),
            "hybrid_final_under_kg": (
                hybrid["final_under_kg"]
            ),
            "hybrid_rl_actions_used": (
                hybrid["rl_actions_used"]
            ),
            "hybrid_greedy_fallbacks": (
                hybrid["greedy_fallbacks"]
            ),
            "hybrid_noninferior_to_greedy": (
                "YES" if passed else "NO"
            ),
            "hybrid_safety_violations": (
                hybrid["safety_violations"]
            ),
            "hybrid_duplicate_assignments": (
                hybrid["duplicate_assignments"]
            ),
            "evaluation_group": (
                "UNSEEN_SHOCK_05"
                if is_validation
                else "NO_SHOCK_BASELINE"
            ),
        })

    noninferiority_rate = (
        noninferior / max(len(validation_pairs), 1) * 100.0
    )
    total_hybrid_decisions = (
        rl_actions_used + greedy_fallbacks
    )
    rl_usage_rate = (
        rl_actions_used / total_hybrid_decisions * 100.0
        if total_hybrid_decisions
        else 0.0
    )
    training_safety = sum(
        integer(row.get("safety_violations"))
        for row in history
    )

    policy_pass = (
        noninferiority_rate >= required_noninferiority_pct
        and training_safety == 0
        and validation_safety == 0
        and validation_duplicates == 0
        and baseline_degradation == 0
    )
    policy_gate = (
        "CANDIDATE_FOR_SHADOW_BACKTEST"
        if policy_pass
        else "NOT_APPROVED_REVIEW_REQUIRED"
    )

    write_csv(
        training_dir / "training_history.csv",
        history,
        [
            "phase",
            "epoch",
            "mean_loss",
            "epsilon",
            "replay_size",
            "transitions",
            "safety_violations",
        ],
    )
    write_csv(
        evaluation_dir / "policy_evaluation_results.csv",
        evaluation_rows,
        [
            "episode_id",
            "shock_id",
            "scenario",
            "estate",
            "policy",
            "initial_under_kg",
            "final_under_kg",
            "initial_over_kg",
            "final_over_kg",
            "initial_objective",
            "final_objective",
            "objective_improvement",
            "moves",
            "rl_actions_used",
            "greedy_fallbacks",
            "total_reward",
            "safety_violations",
            "duplicate_assignments",
        ],
    )
    write_csv(
        evaluation_dir / "policy_vs_greedy_gate.csv",
        gate_rows,
        [
            "episode_id",
            "shock_id",
            "scenario",
            "estate",
            "greedy_final_objective",
            "rl_only_final_objective",
            "hybrid_final_objective",
            "greedy_final_under_kg",
            "rl_only_final_under_kg",
            "hybrid_final_under_kg",
            "hybrid_rl_actions_used",
            "hybrid_greedy_fallbacks",
            "hybrid_noninferior_to_greedy",
            "hybrid_safety_violations",
            "hybrid_duplicate_assignments",
            "evaluation_group",
        ],
    )

    estate_gate_rows = [
        {
            "scenario": row["scenario"],
            "estate": row["estate"],
            "shock_id": row["shock_id"],
            "hybrid_noninferior": (
                row["hybrid_noninferior_to_greedy"]
            ),
            "safety_violations": (
                row["hybrid_safety_violations"]
            ),
            "duplicate_assignments": (
                row["hybrid_duplicate_assignments"]
            ),
            "hybrid_rl_actions_used": (
                row["hybrid_rl_actions_used"]
            ),
            "hybrid_greedy_fallbacks": (
                row["hybrid_greedy_fallbacks"]
            ),
            "estate_policy_gate": (
                "PASS"
                if (
                    row["hybrid_noninferior_to_greedy"]
                    == "YES"
                    and integer(
                        row["hybrid_safety_violations"]
                    ) == 0
                    and integer(
                        row["hybrid_duplicate_assignments"]
                    ) == 0
                )
                else "REVIEW_REQUIRED"
            ),
        }
        for row in gate_rows
        if row["evaluation_group"] == "UNSEEN_SHOCK_05"
    ]
    write_csv(
        evaluation_dir / "estate_policy_gate.csv",
        estate_gate_rows,
        [
            "scenario",
            "estate",
            "shock_id",
            "hybrid_noninferior",
            "safety_violations",
            "duplicate_assignments",
            "hybrid_rl_actions_used",
            "hybrid_greedy_fallbacks",
            "estate_policy_gate",
        ],
    )

    safety_gate_rows = [
        {
            "check": "TRAINING_SAFETY_VIOLATIONS",
            "value": training_safety,
            "required": 0,
            "status": (
                "PASS" if training_safety == 0 else "FAIL"
            ),
        },
        {
            "check": "VALIDATION_NONINFERIORITY_RATE_PCT",
            "value": round(noninferiority_rate, 2),
            "required": required_noninferiority_pct,
            "status": (
                "PASS"
                if noninferiority_rate
                >= required_noninferiority_pct
                else "FAIL"
            ),
        },
        {
            "check": "VALIDATION_SAFETY_VIOLATIONS",
            "value": validation_safety,
            "required": 0,
            "status": (
                "PASS" if validation_safety == 0 else "FAIL"
            ),
        },
        {
            "check": "VALIDATION_DUPLICATE_ASSIGNMENTS",
            "value": validation_duplicates,
            "required": 0,
            "status": (
                "PASS"
                if validation_duplicates == 0
                else "FAIL"
            ),
        },
        {
            "check": "NO_SHOCK_BASELINE_DEGRADATION",
            "value": baseline_degradation,
            "required": 0,
            "status": (
                "PASS"
                if baseline_degradation == 0
                else "FAIL"
            ),
        },
        {
            "check": "LIVE_DEPLOYMENT_STARTED",
            "value": False,
            "required": False,
            "status": "PASS",
        },
    ]
    write_csv(
        quality_dir / "rl_training_safety_gate.csv",
        safety_gate_rows,
        ["check", "value", "required", "status"],
    )

    (model_dir / "model_metadata.json").write_text(
        json.dumps({
            "model_type": "SAFE_ACTION_CONDITIONED_Q_NETWORK",
            "package_version": VERSION,
            "feature_count": FEATURE_COUNT,
            "device_used": str(device),
            "cuda_available": torch.cuda.is_available(),
            "training_pairs": len(training_pairs),
            "validation_pairs": len(validation_pairs),
            "baseline_pairs": len(baseline_pairs),
            "hybrid_acceptance_ratio": hybrid_ratio,
            "policy_gate": policy_gate,
            "operational_use_allowed": False,
        }, indent=2),
        encoding="utf-8",
    )

    summary = {
        "status": "PASS_DEVELOPMENT_RL_TRAINING_OUTPUTS",
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "device_used": str(device),
        "cuda_available": torch.cuda.is_available(),
        "episodes": len(episode_ids),
        "training_episode_shocks": len(training_pairs),
        "validation_episode_shocks": len(validation_pairs),
        "baseline_safety_episode_shocks": len(baseline_pairs),
        "warmup_examples": len(warm_features),
        "training_epochs": training_epochs,
        "model_path": str(model_path),
        "validation_hybrid_noninferiority_rate_pct": round(
            noninferiority_rate, 2
        ),
        "required_noninferiority_rate_pct": (
            required_noninferiority_pct
        ),
        "training_safety_violations": training_safety,
        "validation_safety_violations": validation_safety,
        "validation_duplicate_assignment_failures": (
            validation_duplicates
        ),
        "baseline_degradation_failures": baseline_degradation,
        "hybrid_rl_actions_used": rl_actions_used,
        "hybrid_greedy_fallbacks": greedy_fallbacks,
        "hybrid_rl_usage_rate_pct": round(rl_usage_rate, 2),
        "policy_gate": policy_gate,
        "operational_status": OPERATIONAL_STATUS,
        "rl_started": True,
        "rl_training_completed": True,
        "live_deployment_started": False,
        "important_interpretation": [
            "Training uses simulated shock states, not observed future outcomes.",
            "The RL-only policy and protected hybrid policy are evaluated separately.",
            "The hybrid policy falls back to safe greedy when the RL proposal is weak.",
            "A passing policy gate permits shadow backtesting only.",
            "Current employee attendance, leave, fitness and movement restrictions remain unverified.",
        ],
    }
    (run_folder / "run_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    (run_folder / "README.txt").write_text(
        "\n".join([
            "TTE SAFE DEVELOPMENT RL TRAINING v10.0.0",
            "",
            f"Device: {device}",
            f"Validation noninferiority: {noninferiority_rate:.2f}%",
            f"Policy gate: {policy_gate}",
            "",
            "Live deployment has not started.",
        ]) + "\n",
        encoding="utf-8",
    )

    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "LATEST_SAFE_RL_TRAINING_RUN.txt").write_text(
        str(run_folder), encoding="utf-8"
    )

    print("")
    print("SAFE DEVELOPMENT RL TRAINING FINISHED")
    print(json.dumps(summary, indent=2))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment-run")
    parser.add_argument("--output-root")
    parser.add_argument("--seed", type=int, default=20260724)
    parser.add_argument("--warmup-epochs", type=int, default=2)
    parser.add_argument("--training-epochs", type=int, default=3)
    parser.add_argument("--max-moves", type=int, default=5)
    parser.add_argument("--max-actions", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--gamma", type=float, default=0.95)
    parser.add_argument("--learning-rate", type=float, default=0.0005)
    parser.add_argument("--hybrid-ratio", type=float, default=0.95)
    parser.add_argument(
        "--required-noninferiority-pct",
        type=float,
        default=80.0,
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            env = MockEnvironment(
                temp_path / "mock_manifest.json",
                max_moves=3,
                max_actions=10,
                safety_under_tolerance_kg=0.5,
            )
            summary = train_and_evaluate(
                env=env,
                output_root=temp_path / "output",
                seed=args.seed,
                warmup_epochs=1,
                training_epochs=1,
                max_moves=3,
                batch_size=32,
                gamma=args.gamma,
                learning_rate=args.learning_rate,
                hybrid_ratio=args.hybrid_ratio,
                required_noninferiority_pct=80.0,
            )
            if summary["validation_safety_violations"] != 0:
                raise RuntimeError("Self-test safety failure.")
            if (
                summary[
                    "validation_duplicate_assignment_failures"
                ]
                != 0
            ):
                raise RuntimeError(
                    "Self-test duplicate assignment failure."
                )
            print("SELF_TEST_PASS")
        return 0

    if not args.environment_run or not args.output_root:
        raise SystemExit(
            "--environment-run and --output-root are required."
        )

    environment_run = Path(args.environment_run).resolve()
    output_root = Path(args.output_root).resolve()
    manifest_path = (
        environment_run / "rl_environment_manifest.json"
    )
    summary_path = environment_run / "run_summary.json"

    for path in (manifest_path, summary_path):
        if not path.exists():
            raise SystemExit(f"Missing required input: {path}")

    environment_summary = json.loads(
        summary_path.read_text(encoding="utf-8")
    )
    if (
        environment_summary.get("status")
        != "PASS_RL_ENVIRONMENT_DESIGN"
    ):
        raise SystemExit("The RL environment did not pass.")
    if not environment_summary.get(
        "environment_ready_for_training_code", False
    ):
        raise SystemExit(
            "Environment is not ready for training."
        )
    if environment_summary.get("rl_started") is not False:
        raise SystemExit("Unexpected RL-start flag.")

    environment_class = import_real_environment(
        manifest_path
    )
    import inspect

    constructor_parameters = inspect.signature(
        environment_class.__init__
    ).parameters

    environment_kwargs = {}

    if "max_moves" in constructor_parameters:
        environment_kwargs["max_moves"] = args.max_moves

    if "max_actions" in constructor_parameters:
        environment_kwargs["max_actions"] = args.max_actions

    if "safety_under_tolerance_kg" in constructor_parameters:
        environment_kwargs["safety_under_tolerance_kg"] = 0.5

    env = environment_class(
        manifest_path,
        **environment_kwargs,
    )

    train_and_evaluate(
        env=env,
        output_root=output_root,
        seed=args.seed,
        warmup_epochs=args.warmup_epochs,
        training_epochs=args.training_epochs,
        max_moves=args.max_moves,
        batch_size=args.batch_size,
        gamma=args.gamma,
        learning_rate=args.learning_rate,
        hybrid_ratio=args.hybrid_ratio,
        required_noninferiority_pct=(
            args.required_noninferiority_pct
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
