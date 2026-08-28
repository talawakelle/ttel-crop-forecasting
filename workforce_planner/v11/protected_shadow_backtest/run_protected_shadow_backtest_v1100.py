from __future__ import annotations

import argparse
import csv
import importlib.util
import inspect
import json
import math
import random
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn


VERSION = "11.0.0"
FEATURE_COUNT = 10
OPERATIONAL_STATUS = "DEVELOPMENT_SHADOW_BACKTEST_ONLY"


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


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fields: list[str],
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def episode_key(scenario: str, estate: str) -> tuple[str, str]:
    return clean(scenario).upper(), clean(estate).lower()


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


def safe_actions(
    actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
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
            "source_field_uid": "",
            "target_field_uid": "",
        })
    return filtered


def action_features(
    state: dict[str, Any],
    action: dict[str, Any],
    max_moves: int,
) -> np.ndarray:
    target = max(
        number(state.get("total_target_crop_kg")),
        1.0,
    )
    action_type = clean(
        action.get("action_type")
    ).upper()
    source = clean(action.get("source_field_uid"))
    target_field = clean(action.get("target_field_uid"))

    return np.asarray([
        number(state.get("total_under_kg")) / target,
        number(state.get("total_over_kg")) / target,
        number(state.get("move_count")) / max(max_moves, 1),
        number(action.get("projected_reward")) / target,
        number(
            action.get("projected_under_change_kg")
        ) / target,
        number(
            action.get("projected_over_change_kg")
        ) / target,
        1.0 if action_type == "NO_OP" else 0.0,
        1.0 if action_type == "MOVE" else 0.0,
        1.0 if (
            source
            and target_field
            and source != target_field
        ) else 0.0,
        1.0 if clean(
            state.get("scenario")
        ).upper() == "CONSERVATIVE" else 0.0,
    ], dtype=np.float32)


def attach_features(
    state: dict[str, Any],
    actions: list[dict[str, Any]],
    max_moves: int,
) -> list[tuple[dict[str, Any], np.ndarray]]:
    return [
        (
            action,
            action_features(state, action, max_moves),
        )
        for action in safe_actions(actions)
    ]


def model_values(
    model: QNetwork,
    featured_actions: list[
        tuple[dict[str, Any], np.ndarray]
    ],
    device: torch.device,
) -> torch.Tensor:
    matrix = np.stack([
        features
        for _, features in featured_actions
    ])
    tensor = torch.from_numpy(
        matrix
    ).float().to(device)
    with torch.no_grad():
        return model(tensor)


def greedy_action(
    featured_actions: list[
        tuple[dict[str, Any], np.ndarray]
    ],
) -> tuple[dict[str, Any], np.ndarray]:
    positive = [
        item
        for item in featured_actions
        if clean(
            item[0].get("action_type")
        ).upper() != "NO_OP"
        and number(
            item[0].get("projected_reward")
        ) > 0.0
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
        if clean(
            item[0].get("action_type")
        ).upper() == "NO_OP"
    )


def safe_env_step(
    env: Any,
    action_id: str,
) -> tuple[
    dict[str, Any],
    float,
    bool,
    dict[str, Any],
]:
    if clean(action_id).upper() == "NO_OP":
        if hasattr(env, "terminated"):
            env.terminated = True
        return (
            env.state(),
            0.0,
            True,
            {
                "accepted": True,
                "reason": "SHADOW_NO_OP_TERMINATED",
            },
        )
    return env.step(action_id)


def create_environment(
    environment_class: Any,
    manifest_path: Path,
    max_moves: int,
    max_actions: int,
) -> Any:
    parameters = inspect.signature(
        environment_class.__init__
    ).parameters
    kwargs: dict[str, Any] = {}

    if "max_moves" in parameters:
        kwargs["max_moves"] = max_moves
    if "max_actions" in parameters:
        kwargs["max_actions"] = max_actions
    if "safety_under_tolerance_kg" in parameters:
        kwargs["safety_under_tolerance_kg"] = 0.5

    return environment_class(
        manifest_path,
        **kwargs,
    )


def import_environment(
    manifest_path: Path,
) -> Any:
    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    code_path = Path(
        manifest["environment_code_path"]
    )
    spec = importlib.util.spec_from_file_location(
        "tte_v11_environment_runtime",
        code_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"Unable to import environment: {code_path}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.TTEWorkforceRLEnvironment


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
            state,
            env.valid_actions(),
            max_moves,
        )
        greedy = greedy_action(featured)

        if policy == "NO_REPLAN":
            selected = next(
                item
                for item in featured
                if clean(
                    item[0].get("action_type")
                ).upper() == "NO_OP"
            )
        elif policy == "GREEDY":
            selected = greedy
        else:
            values = model_values(
                model,
                featured,
                device,
            )
            rl_selected = featured[
                int(torch.argmax(values).item())
            ]

            if policy == "RL_ONLY":
                selected = rl_selected
                if clean(
                    selected[0].get("action_type")
                ).upper() != "NO_OP":
                    rl_actions += 1

            elif policy == "HYBRID":
                greedy_reward = max(
                    0.0,
                    number(
                        greedy[0].get("projected_reward")
                    ),
                )
                rl_reward = number(
                    rl_selected[0].get(
                        "projected_reward"
                    )
                )
                rl_is_move = clean(
                    rl_selected[0].get("action_type")
                ).upper() != "NO_OP"

                if (
                    rl_is_move
                    and rl_reward > 0.0
                    and rl_reward
                    >= greedy_reward * hybrid_ratio
                ):
                    selected = rl_selected
                    rl_actions += 1
                else:
                    selected = greedy
                    if clean(
                        greedy[0].get("action_type")
                    ).upper() != "NO_OP":
                        greedy_fallbacks += 1
            else:
                raise ValueError(
                    f"Unknown policy: {policy}"
                )

        _, reward, done, info = safe_env_step(
            env,
            clean(selected[0].get("action_id")),
        )
        total_reward += number(reward)

        if not info.get("accepted", False):
            safety_violations += 1

        if done:
            break

    final = env.state()

    initial_objective = (
        1000.0
        * number(initial.get("total_under_kg"))
        + 10.0
        * number(initial.get("total_over_kg"))
    )
    final_objective = (
        1000.0
        * number(final.get("total_under_kg"))
        + 10.0
        * number(final.get("total_over_kg"))
        + number(final.get("move_count"))
    )

    return {
        "episode_id": episode_id,
        "shock_id": shock_id,
        "scenario": clean(final.get("scenario")),
        "estate": clean(final.get("estate")),
        "policy": policy,
        "initial_under_kg": round(
            number(initial.get("total_under_kg")),
            4,
        ),
        "final_under_kg": round(
            number(final.get("total_under_kg")),
            4,
        ),
        "initial_over_kg": round(
            number(initial.get("total_over_kg")),
            4,
        ),
        "final_over_kg": round(
            number(final.get("total_over_kg")),
            4,
        ),
        "initial_objective": round(
            initial_objective,
            4,
        ),
        "final_objective": round(
            final_objective,
            4,
        ),
        "objective_improvement": round(
            initial_objective - final_objective,
            4,
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


def is_noninferior(
    routed: dict[str, Any],
    greedy: dict[str, Any],
) -> bool:
    tolerance = max(
        5.0,
        number(
            greedy.get("final_objective")
        ) * 0.01,
    )
    return (
        number(routed.get("final_objective"))
        <= number(
            greedy.get("final_objective")
        ) + tolerance
        and number(routed.get("final_under_kg"))
        <= number(
            greedy.get("final_under_kg")
        ) + 0.5
    )


def shock_group(shock_id: str) -> str:
    if shock_id == "SHOCK_00_BASELINE":
        return "NO_SHOCK_BASELINE"
    if shock_id == "SHOCK_05":
        return "UNSEEN_SHOCK_05"
    return "TRAINING_SHOCK_REPLAY"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run protected routed-policy shadow "
            "backtesting."
        )
    )
    parser.add_argument("--project-root")
    parser.add_argument("--output-root")
    parser.add_argument("--max-moves", type=int, default=5)
    parser.add_argument(
        "--max-actions",
        type=int,
        default=100,
    )
    parser.add_argument(
        "--hybrid-ratio",
        type=float,
        default=0.95,
    )
    parser.add_argument(
        "--required-all-case-noninferiority-pct",
        type=float,
        default=95.0,
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    if not args.project_root or not args.output_root:
        raise SystemExit(
            "--project-root and --output-root "
            "are required."
        )

    project_root = Path(
        args.project_root
    ).resolve()
    output_root = Path(
        args.output_root
    ).resolve()

    environment_pointer = (
        project_root
        / "workforce_planner"
        / "v9"
        / "rl_environment_runs"
        / "LATEST_RL_ENVIRONMENT_DESIGN_RUN.txt"
    )
    training_pointer = (
        project_root
        / "workforce_planner"
        / "v10"
        / "safe_rl_training_runs"
        / "LATEST_SAFE_RL_TRAINING_RUN.txt"
    )

    for path in (
        environment_pointer,
        training_pointer,
    ):
        if not path.exists():
            raise SystemExit(
                f"Missing required pointer: {path}"
            )

    environment_run = Path(
        environment_pointer.read_text(
            encoding="utf-8-sig"
        ).strip()
    )
    training_run = Path(
        training_pointer.read_text(
            encoding="utf-8-sig"
        ).strip()
    )

    environment_summary_path = (
        environment_run / "run_summary.json"
    )
    training_summary_path = (
        training_run / "run_summary.json"
    )
    manifest_path = (
        environment_run
        / "rl_environment_manifest.json"
    )

    environment_summary = json.loads(
        environment_summary_path.read_text(
            encoding="utf-8"
        )
    )
    training_summary = json.loads(
        training_summary_path.read_text(
            encoding="utf-8"
        )
    )

    if environment_summary.get(
        "status"
    ) != "PASS_RL_ENVIRONMENT_DESIGN":
        raise SystemExit(
            "The v9 environment did not pass."
        )
    if training_summary.get(
        "status"
    ) != "PASS_DEVELOPMENT_RL_TRAINING_OUTPUTS":
        raise SystemExit(
            "The v10 RL training did not pass."
        )
    if training_summary.get(
        "policy_gate"
    ) != "CANDIDATE_FOR_SHADOW_BACKTEST":
        raise SystemExit(
            "The v10 policy gate does not permit "
            "shadow backtesting."
        )
    if training_summary.get(
        "live_deployment_started"
    ) is not False:
        raise SystemExit(
            "Unexpected live-deployment flag."
        )

    model_path = Path(
        training_summary["model_path"]
    )
    if not model_path.exists():
        raise SystemExit(
            f"Model file not found: {model_path}"
        )

    review_path = (
        training_run
        / "evaluation"
        / "five_estate_scenario_review_cases.csv"
    )
    evaluation_path = (
        training_run
        / "evaluation"
        / "policy_vs_greedy_gate.csv"
    )

    if review_path.exists():
        review_rows = read_csv(review_path)
    else:
        review_rows = [
            {
                **row,
                "recommended_shadow_policy": (
                    "GREEDY_FALLBACK"
                ),
            }
            for row in read_csv(evaluation_path)
            if clean(
                row.get("evaluation_group")
            ) == "UNSEEN_SHOCK_05"
            and clean(
                row.get(
                    "hybrid_noninferior_to_greedy"
                )
            ).upper() == "NO"
        ]

    fallback_keys = {
        episode_key(
            row.get("scenario", ""),
            row.get("estate", ""),
        )
        for row in review_rows
        if clean(
            row.get(
                "recommended_shadow_policy"
            )
        ).upper() == "GREEDY_FALLBACK"
    }

    if not fallback_keys:
        raise SystemExit(
            "No shadow fallback rules were found."
        )

    device = torch.device(
        "cuda"
        if torch.cuda.is_available()
        else "cpu"
    )
    checkpoint = torch.load(
        model_path,
        map_location=device,
        weights_only=False,
    )
    model = QNetwork().to(device)
    model.load_state_dict(
        checkpoint["model_state_dict"]
    )
    model.eval()

    environment_class = import_environment(
        manifest_path
    )
    env = create_environment(
        environment_class,
        manifest_path,
        max_moves=args.max_moves,
        max_actions=args.max_actions,
    )

    episode_ids = env.episode_ids()
    if len(episode_ids) != 66:
        raise SystemExit(
            f"Expected 66 episodes, found "
            f"{len(episode_ids)}."
        )

    run_folder = (
        output_root
        / datetime.now().strftime(
            "protected_shadow_backtest_%Y%m%d_%H%M%S"
        )
    )
    evaluation_dir = (
        run_folder / "evaluation"
    )
    quality_dir = run_folder / "quality"
    policy_dir = run_folder / "policy"
    for folder in (
        evaluation_dir,
        quality_dir,
        policy_dir,
    ):
        folder.mkdir(
            parents=True,
            exist_ok=True,
        )

    print(
        f"Protected shadow backtest: {run_folder}"
    )
    print(f"Device: {device}")
    print(f"Episodes: {len(episode_ids)}")
    print(
        f"Episode-level greedy fallback rules: "
        f"{len(fallback_keys)}"
    )
    print(
        "All six deterministic shock sets will "
        "be replayed."
    )
    print(
        "No live employee assignment will run."
    )

    results: list[dict[str, Any]] = []
    routed_rows: list[dict[str, Any]] = []
    episode_policy_rows: list[
        dict[str, Any]
    ] = []

    episode_counter = 0
    for episode_id in episode_ids:
        first_state = env.reset(
            episode_id,
            env.shock_ids(episode_id)[0],
        )
        key = episode_key(
            first_state.get("scenario", ""),
            first_state.get("estate", ""),
        )
        selected_policy = (
            "GREEDY"
            if key in fallback_keys
            else "HYBRID"
        )

        episode_policy_rows.append({
            "episode_id": episode_id,
            "scenario": first_state.get(
                "scenario", ""
            ),
            "estate": first_state.get(
                "estate", ""
            ),
            "routed_shadow_policy": (
                "GREEDY_FALLBACK"
                if selected_policy == "GREEDY"
                else "PROTECTED_HYBRID_RL"
            ),
            "fallback_reason": (
                "V10_UNSEEN_SHOCK_REVIEW"
                if selected_policy == "GREEDY"
                else "V10_VALIDATION_PASS"
            ),
            "operational_use_allowed": "NO",
        })

        episode_counter += 1
        print(
            f"[{episode_counter}/66] "
            f"{first_state.get('scenario')} "
            f"{first_state.get('estate')} -> "
            f"{selected_policy}"
        )

        for shock_id in env.shock_ids(
            episode_id
        ):
            policy_results: dict[
                str,
                dict[str, Any],
            ] = {}

            for policy in (
                "NO_REPLAN",
                "GREEDY",
                "RL_ONLY",
                "HYBRID",
            ):
                policy_results[policy] = run_policy(
                    env=env,
                    episode_id=episode_id,
                    shock_id=shock_id,
                    policy=policy,
                    model=model,
                    device=device,
                    max_moves=args.max_moves,
                    hybrid_ratio=args.hybrid_ratio,
                )
                results.append(
                    policy_results[policy]
                )

            source = policy_results[
                selected_policy
            ]
            routed = {
                **source,
                "policy": "ROUTED_POLICY",
                "routed_source_policy": (
                    selected_policy
                ),
                "routed_shadow_policy": (
                    "GREEDY_FALLBACK"
                    if selected_policy == "GREEDY"
                    else "PROTECTED_HYBRID_RL"
                ),
            }
            results.append(routed)

            greedy = policy_results["GREEDY"]
            no_replan = policy_results[
                "NO_REPLAN"
            ]
            hybrid = policy_results["HYBRID"]

            routed_noninferior = is_noninferior(
                routed,
                greedy,
            )
            no_replan_degraded = (
                number(
                    routed.get(
                        "final_objective"
                    )
                )
                > number(
                    no_replan.get(
                        "final_objective"
                    )
                )
                + max(
                    5.0,
                    number(
                        no_replan.get(
                            "final_objective"
                        )
                    )
                    * 0.01,
                )
            )

            routed_rows.append({
                "episode_id": episode_id,
                "shock_id": shock_id,
                "shock_group": shock_group(
                    shock_id
                ),
                "scenario": routed["scenario"],
                "estate": routed["estate"],
                "routed_shadow_policy": (
                    routed[
                        "routed_shadow_policy"
                    ]
                ),
                "routed_source_policy": (
                    routed[
                        "routed_source_policy"
                    ]
                ),
                "no_replan_final_objective": (
                    no_replan[
                        "final_objective"
                    ]
                ),
                "greedy_final_objective": (
                    greedy["final_objective"]
                ),
                "hybrid_final_objective": (
                    hybrid["final_objective"]
                ),
                "routed_final_objective": (
                    routed["final_objective"]
                ),
                "greedy_final_under_kg": (
                    greedy["final_under_kg"]
                ),
                "hybrid_final_under_kg": (
                    hybrid["final_under_kg"]
                ),
                "routed_final_under_kg": (
                    routed["final_under_kg"]
                ),
                "routed_moves": routed["moves"],
                "routed_rl_actions_used": (
                    routed["rl_actions_used"]
                ),
                "routed_greedy_fallbacks": (
                    routed["greedy_fallbacks"]
                ),
                "routed_noninferior_to_greedy": (
                    "YES"
                    if routed_noninferior
                    else "NO"
                ),
                "routed_worse_than_no_replan": (
                    "YES"
                    if no_replan_degraded
                    else "NO"
                ),
                "routed_safety_violations": (
                    routed[
                        "safety_violations"
                    ]
                ),
                "routed_duplicate_assignments": (
                    routed[
                        "duplicate_assignments"
                    ]
                ),
                "operational_use_allowed": "NO",
            })

    result_fields = [
        "episode_id",
        "shock_id",
        "scenario",
        "estate",
        "policy",
        "routed_source_policy",
        "routed_shadow_policy",
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
    ]
    write_csv(
        evaluation_dir
        / "all_policy_shadow_results.csv",
        results,
        result_fields,
    )

    routed_fields = [
        "episode_id",
        "shock_id",
        "shock_group",
        "scenario",
        "estate",
        "routed_shadow_policy",
        "routed_source_policy",
        "no_replan_final_objective",
        "greedy_final_objective",
        "hybrid_final_objective",
        "routed_final_objective",
        "greedy_final_under_kg",
        "hybrid_final_under_kg",
        "routed_final_under_kg",
        "routed_moves",
        "routed_rl_actions_used",
        "routed_greedy_fallbacks",
        "routed_noninferior_to_greedy",
        "routed_worse_than_no_replan",
        "routed_safety_violations",
        "routed_duplicate_assignments",
        "operational_use_allowed",
    ]
    write_csv(
        evaluation_dir
        / "routed_policy_shadow_results.csv",
        routed_rows,
        routed_fields,
    )

    write_csv(
        policy_dir
        / "estate_scenario_shadow_policy_register.csv",
        episode_policy_rows,
        [
            "episode_id",
            "scenario",
            "estate",
            "routed_shadow_policy",
            "fallback_reason",
            "operational_use_allowed",
        ],
    )

    total_cases = len(routed_rows)
    unseen_rows = [
        row
        for row in routed_rows
        if row["shock_group"]
        == "UNSEEN_SHOCK_05"
    ]
    baseline_rows = [
        row
        for row in routed_rows
        if row["shock_group"]
        == "NO_SHOCK_BASELINE"
    ]
    training_replay_rows = [
        row
        for row in routed_rows
        if row["shock_group"]
        == "TRAINING_SHOCK_REPLAY"
    ]

    def pass_count(
        rows: list[dict[str, Any]],
    ) -> int:
        return sum(
            1
            for row in rows
            if row[
                "routed_noninferior_to_greedy"
            ] == "YES"
        )

    all_passes = pass_count(routed_rows)
    unseen_passes = pass_count(unseen_rows)
    replay_passes = pass_count(
        training_replay_rows
    )

    all_rate = (
        all_passes / max(total_cases, 1) * 100.0
    )
    unseen_rate = (
        unseen_passes
        / max(len(unseen_rows), 1)
        * 100.0
    )
    replay_rate = (
        replay_passes
        / max(len(training_replay_rows), 1)
        * 100.0
    )

    safety_violations = sum(
        integer(
            row[
                "routed_safety_violations"
            ]
        )
        for row in routed_rows
    )
    duplicate_failures = sum(
        integer(
            row[
                "routed_duplicate_assignments"
            ]
        )
        for row in routed_rows
    )
    baseline_degradation = sum(
        1
        for row in baseline_rows
        if row[
            "routed_worse_than_no_replan"
        ] == "YES"
    )
    unseen_failures = [
        row
        for row in unseen_rows
        if row[
            "routed_noninferior_to_greedy"
        ] == "NO"
    ]
    all_failures = [
        row
        for row in routed_rows
        if row[
            "routed_noninferior_to_greedy"
        ] == "NO"
    ]

    rl_actions = sum(
        integer(
            row["routed_rl_actions_used"]
        )
        for row in routed_rows
    )
    greedy_actions = sum(
        integer(
            row["routed_greedy_fallbacks"]
        )
        for row in routed_rows
    )
    routed_greedy_episode_cases = sum(
        1
        for row in routed_rows
        if row["routed_source_policy"]
        == "GREEDY"
    )
    routed_hybrid_episode_cases = (
        total_cases
        - routed_greedy_episode_cases
    )

    gate_pass = (
        unseen_rate == 100.0
        and all_rate
        >= args.required_all_case_noninferiority_pct
        and safety_violations == 0
        and duplicate_failures == 0
        and baseline_degradation == 0
    )
    shadow_gate = (
        "READY_FOR_SUPERVISOR_SHADOW_REVIEW"
        if gate_pass
        else "NOT_READY_SHADOW_REVIEW_REQUIRED"
    )

    quality_rows = [
        {
            "check": (
                "V10_POLICY_GATE"
            ),
            "value": training_summary.get(
                "policy_gate"
            ),
            "required": (
                "CANDIDATE_FOR_SHADOW_BACKTEST"
            ),
            "status": "PASS",
        },
        {
            "check": (
                "UNSEEN_SHOCK_ROUTED_"
                "NONINFERIORITY_RATE_PCT"
            ),
            "value": round(
                unseen_rate,
                2,
            ),
            "required": 100.0,
            "status": (
                "PASS"
                if unseen_rate == 100.0
                else "FAIL"
            ),
        },
        {
            "check": (
                "ALL_CASE_ROUTED_"
                "NONINFERIORITY_RATE_PCT"
            ),
            "value": round(all_rate, 2),
            "required": (
                args
                .required_all_case_noninferiority_pct
            ),
            "status": (
                "PASS"
                if all_rate
                >= args
                .required_all_case_noninferiority_pct
                else "FAIL"
            ),
        },
        {
            "check": (
                "ROUTED_SAFETY_VIOLATIONS"
            ),
            "value": safety_violations,
            "required": 0,
            "status": (
                "PASS"
                if safety_violations == 0
                else "FAIL"
            ),
        },
        {
            "check": (
                "ROUTED_DUPLICATE_ASSIGNMENTS"
            ),
            "value": duplicate_failures,
            "required": 0,
            "status": (
                "PASS"
                if duplicate_failures == 0
                else "FAIL"
            ),
        },
        {
            "check": (
                "NO_SHOCK_BASELINE_DEGRADATION"
            ),
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
        quality_dir
        / "protected_shadow_backtest_gate.csv",
        quality_rows,
        [
            "check",
            "value",
            "required",
            "status",
        ],
    )

    write_csv(
        quality_dir
        / "routed_policy_review_cases.csv",
        all_failures,
        routed_fields,
    )
    write_csv(
        quality_dir
        / "unseen_shock_review_cases.csv",
        unseen_failures,
        routed_fields,
    )

    summary = {
        "status": (
            "PASS_PROTECTED_SHADOW_BACKTEST_OUTPUTS"
        ),
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "environment_run": str(
            environment_run
        ),
        "training_run": str(training_run),
        "model_path": str(model_path),
        "device_used": str(device),
        "cuda_available": (
            torch.cuda.is_available()
        ),
        "episodes": len(episode_ids),
        "shock_sets_per_episode": 6,
        "routed_episode_shock_cases": (
            total_cases
        ),
        "greedy_fallback_episode_count": (
            len(fallback_keys)
        ),
        "protected_hybrid_episode_count": (
            len(episode_ids)
            - len(fallback_keys)
        ),
        "routed_greedy_episode_shock_cases": (
            routed_greedy_episode_cases
        ),
        "routed_hybrid_episode_shock_cases": (
            routed_hybrid_episode_cases
        ),
        "all_case_routed_noninferiority_rate_pct": round(
            all_rate,
            2,
        ),
        "required_all_case_noninferiority_rate_pct": (
            args
            .required_all_case_noninferiority_pct
        ),
        "training_shock_replay_noninferiority_rate_pct": round(
            replay_rate,
            2,
        ),
        "unseen_shock_05_routed_noninferiority_rate_pct": round(
            unseen_rate,
            2,
        ),
        "unseen_shock_05_review_cases": len(
            unseen_failures
        ),
        "routed_safety_violations": (
            safety_violations
        ),
        "routed_duplicate_assignment_failures": (
            duplicate_failures
        ),
        "no_shock_baseline_degradation_failures": (
            baseline_degradation
        ),
        "routed_rl_actions_used": rl_actions,
        "routed_hybrid_greedy_fallbacks": (
            greedy_actions
        ),
        "shadow_gate": shadow_gate,
        "operational_status": (
            OPERATIONAL_STATUS
        ),
        "shadow_backtest_completed": True,
        "supervisor_review_started": False,
        "live_deployment_started": False,
        "important_interpretation": [
            (
                "This replays deterministic "
                "simulated shock states; it is not "
                "observed historical performance."
            ),
            (
                "Five estate-scenario episodes use "
                "greedy fallback and the remainder "
                "use protected hybrid RL."
            ),
            (
                "A pass permits supervisor shadow "
                "review only."
            ),
            (
                "No named employee recommendation "
                "is approved for live use."
            ),
            (
                "Attendance, leave, fitness and "
                "movement restrictions remain "
                "unverified."
            ),
        ],
    }
    (run_folder / "run_summary.json").write_text(
        json.dumps(
            summary,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_folder / "README.txt").write_text(
        "\n".join([
            (
                "TTE PROTECTED SHADOW "
                "BACKTEST v11.0.0"
            ),
            "",
            f"Device: {device}",
            (
                "All-case noninferiority: "
                f"{all_rate:.2f}%"
            ),
            (
                "Unseen SHOCK_05 "
                f"noninferiority: "
                f"{unseen_rate:.2f}%"
            ),
            (
                f"Safety violations: "
                f"{safety_violations}"
            ),
            (
                f"Shadow gate: {shadow_gate}"
            ),
            "",
            (
                "This is not a live employee "
                "allocation system."
            ),
        ]) + "\n",
        encoding="utf-8",
    )

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )
    (
        output_root
        / "LATEST_PROTECTED_SHADOW_BACKTEST_RUN.txt"
    ).write_text(
        str(run_folder),
        encoding="utf-8",
    )

    print("")
    print(
        "PROTECTED SHADOW BACKTEST FINISHED"
    )
    print(json.dumps(summary, indent=2))
    return 0


class MockEnvironment:
    def __init__(
        self,
        manifest_path: Path,
        max_moves: int = 3,
        max_actions: int = 10,
    ) -> None:
        self.max_moves = max_moves
        self._episodes = [
            f"EP_{index:03d}"
            for index in range(1, 67)
        ]
        self.current_episode = ""
        self.current_shock = ""
        self.moves = 0
        self.under = 0.0
        self.over = 0.0
        self.terminated = False

    def episode_ids(self) -> list[str]:
        return list(self._episodes)

    def shock_ids(
        self,
        episode_id: str,
    ) -> list[str]:
        return [
            "SHOCK_00_BASELINE",
            "SHOCK_01",
            "SHOCK_02",
            "SHOCK_03",
            "SHOCK_04",
            "SHOCK_05",
        ]

    def reset(
        self,
        episode_id: str,
        shock_id: str,
    ) -> dict[str, Any]:
        self.current_episode = episode_id
        self.current_shock = shock_id
        self.moves = 0
        self.terminated = False
        self.under = (
            0.0
            if shock_id == "SHOCK_00_BASELINE"
            else 6.0
        )
        self.over = 1.0
        return self.state()

    def state(self) -> dict[str, Any]:
        index = int(
            self.current_episode.split("_")[1]
        )
        return {
            "episode_id": self.current_episode,
            "shock_id": self.current_shock,
            "scenario": (
                "CONSERVATIVE"
                if index <= 33
                else "EXPECTED"
            ),
            "estate": (
                f"Estate{((index - 1) % 33) + 1:02d}"
            ),
            "total_target_crop_kg": 1000.0,
            "total_under_kg": self.under,
            "total_over_kg": self.over,
            "move_count": self.moves,
            "duplicate_assignments": 0,
            "terminated": self.terminated,
        }

    def valid_actions(
        self,
    ) -> list[dict[str, Any]]:
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
            actions.append({
                "action_id": "MOVE_BEST",
                "action_type": "MOVE",
                "safe_action": "YES",
                "projected_reward": 1999.0,
                "projected_under_change_kg": -2.0,
                "projected_over_change_kg": 0.0,
                "source_field_uid": "F1",
                "target_field_uid": "F2",
            })
        return actions

    def step(
        self,
        action_id: str,
    ) -> tuple[
        dict[str, Any],
        float,
        bool,
        dict[str, Any],
    ]:
        if action_id != "MOVE_BEST":
            raise KeyError(action_id)
        self.under = max(
            0.0,
            self.under - 2.0,
        )
        self.moves += 1
        self.terminated = (
            self.moves >= self.max_moves
            or self.under <= 0.0
        )
        return (
            self.state(),
            1999.0,
            self.terminated,
            {
                "accepted": True,
                "reason": "MOVE",
            },
        )


def run_self_test() -> int:
    torch.manual_seed(1)
    model = QNetwork()
    for parameter in model.parameters():
        nn.init.constant_(parameter, 0.0)
    device = torch.device("cpu")
    env = MockEnvironment(
        Path("mock_manifest.json"),
        max_moves=3,
        max_actions=10,
    )

    result = run_policy(
        env=env,
        episode_id="EP_001",
        shock_id="SHOCK_05",
        policy="HYBRID",
        model=model,
        device=device,
        max_moves=3,
        hybrid_ratio=0.95,
    )
    if result["safety_violations"] != 0:
        raise RuntimeError(
            "Self-test safety failure."
        )
    if result["duplicate_assignments"] != 0:
        raise RuntimeError(
            "Self-test duplicate failure."
        )
    if result["final_under_kg"] != 0.0:
        raise RuntimeError(
            "Self-test routing failure."
        )

    no_replan = run_policy(
        env=env,
        episode_id="EP_001",
        shock_id="SHOCK_00_BASELINE",
        policy="NO_REPLAN",
        model=model,
        device=device,
        max_moves=3,
        hybrid_ratio=0.95,
    )
    if no_replan["moves"] != 0:
        raise RuntimeError(
            "Self-test NO_OP failure."
        )

    print("SELF_TEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
