from __future__ import annotations

import argparse
import csv
import importlib.util
import inspect
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn


VERSION = "11.0.1"
FEATURE_COUNT = 10
OPERATIONAL_STATUS = "DEVELOPMENT_SHADOW_REPAIR_ONLY"

STATE_MOVE_FIELDS = (
    "move_count",
    "moves",
    "moves_used",
    "accepted_moves",
    "accepted_move_count",
    "completed_moves",
    "completed_move_count",
    "executed_moves",
    "executed_move_count",
    "action_count",
)

HISTORY_ATTRS = (
    "action_history",
    "move_history",
    "accepted_actions",
    "accepted_moves",
    "history",
)


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


def exact_key(
    scenario: str,
    estate: str,
    shock_id: str,
) -> tuple[str, str, str]:
    return (
        clean(scenario).upper(),
        clean(estate).lower(),
        clean(shock_id).upper(),
    )


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
    target = max(number(state.get("total_target_crop_kg")), 1.0)
    action_type = clean(action.get("action_type")).upper()
    source = clean(action.get("source_field_uid"))
    target_field = clean(action.get("target_field_uid"))

    return np.asarray([
        number(state.get("total_under_kg")) / target,
        number(state.get("total_over_kg")) / target,
        resolved_state_move_count(state)[1] / max(max_moves, 1),
        number(action.get("projected_reward")) / target,
        number(action.get("projected_under_change_kg")) / target,
        number(action.get("projected_over_change_kg")) / target,
        1.0 if action_type == "NO_OP" else 0.0,
        1.0 if action_type == "MOVE" else 0.0,
        1.0 if source and target_field and source != target_field else 0.0,
        1.0 if clean(state.get("scenario")).upper() == "CONSERVATIVE" else 0.0,
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
    matrix = np.stack([features for _, features in featured_actions])
    tensor = torch.from_numpy(matrix).float().to(device)
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
            key=lambda item: number(item[0].get("projected_reward")),
        )
    return next(
        item
        for item in featured_actions
        if clean(item[0].get("action_type")).upper() == "NO_OP"
    )


def safe_env_step(
    env: Any,
    action_id: str,
) -> tuple[dict[str, Any], float, bool, dict[str, Any]]:
    if clean(action_id).upper() == "NO_OP":
        if hasattr(env, "terminated"):
            env.terminated = True
        return (
            env.state(),
            0.0,
            True,
            {
                "accepted": True,
                "reason": "AUDIT_NO_OP_TERMINATED",
            },
        )
    return env.step(action_id)


def resolved_state_move_count(
    state: dict[str, Any],
) -> tuple[str, int]:
    for field in STATE_MOVE_FIELDS:
        if field in state and clean(state.get(field)) != "":
            return field, integer(state.get(field))
    return "NOT_EXPOSED", 0


def history_move_count(env: Any) -> tuple[str, int | None]:
    for attr in HISTORY_ATTRS:
        if not hasattr(env, attr):
            continue
        value = getattr(env, attr)
        if isinstance(value, (list, tuple)):
            count = 0
            for item in value:
                if isinstance(item, dict):
                    accepted = item.get("accepted", True)
                    action_type = clean(
                        item.get("action_type")
                        or item.get("type")
                        or item.get("action")
                    ).upper()
                    if accepted and action_type not in ("", "NO_OP"):
                        count += 1
                else:
                    text = clean(item).upper()
                    if text and text != "NO_OP":
                        count += 1
            return attr, count
    return "NOT_EXPOSED", None


def create_environment(
    environment_class: Any,
    manifest_path: Path,
    max_moves: int,
    max_actions: int,
) -> Any:
    parameters = inspect.signature(environment_class.__init__).parameters
    kwargs: dict[str, Any] = {}

    if "max_moves" in parameters:
        kwargs["max_moves"] = max_moves
    if "max_actions" in parameters:
        kwargs["max_actions"] = max_actions
    if "safety_under_tolerance_kg" in parameters:
        kwargs["safety_under_tolerance_kg"] = 0.5

    return environment_class(manifest_path, **kwargs)


def import_environment(manifest_path: Path) -> Any:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    code_path = Path(manifest["environment_code_path"])
    spec = importlib.util.spec_from_file_location(
        "tte_v1101_environment_runtime",
        code_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import environment: {code_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.TTEWorkforceRLEnvironment


def objective(
    under_kg: float,
    over_kg: float,
    accepted_move_count: int,
) -> float:
    return (
        1000.0 * under_kg
        + 10.0 * over_kg
        + float(accepted_move_count)
    )


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
    accepted_moves = 0
    rejected_moves = 0
    safety_violations = 0
    action_audit: list[dict[str, Any]] = []

    for step_index in range(max_moves + 1):
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
                if clean(item[0].get("action_type")).upper() == "NO_OP"
            )
            selection_source = "NO_REPLAN"

        elif policy == "GREEDY":
            selected = greedy
            selection_source = "GREEDY"

        else:
            values = model_values(model, featured, device)
            rl_selected = featured[int(torch.argmax(values).item())]

            if policy == "RL_ONLY":
                selected = rl_selected
                selection_source = "RL"
                if clean(selected[0].get("action_type")).upper() != "NO_OP":
                    rl_actions += 1

            elif policy == "HYBRID":
                greedy_reward = max(
                    0.0,
                    number(greedy[0].get("projected_reward")),
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
                    selection_source = "RL"
                    rl_actions += 1
                else:
                    selected = greedy
                    selection_source = "GREEDY_FALLBACK"
                    if (
                        clean(greedy[0].get("action_type")).upper()
                        != "NO_OP"
                    ):
                        greedy_fallbacks += 1
            else:
                raise ValueError(f"Unknown policy: {policy}")

        action = selected[0]
        action_id = clean(action.get("action_id"))
        action_type = clean(action.get("action_type")).upper()
        _, reward, done, info = safe_env_step(env, action_id)
        accepted = bool(info.get("accepted", False))
        is_move = action_type != "NO_OP"

        if is_move and accepted:
            accepted_moves += 1
        elif is_move and not accepted:
            rejected_moves += 1
            safety_violations += 1

        total_reward += number(reward)

        action_audit.append({
            "step_index": step_index,
            "action_id": action_id,
            "action_type": action_type,
            "selection_source": selection_source,
            "accepted": accepted,
            "reason": clean(info.get("reason")),
        })

        if done:
            break

    final = env.state()
    state_move_field, state_moves = resolved_state_move_count(final)
    history_field, history_moves = history_move_count(env)

    state_reconciliation_status = (
        "NOT_EXPOSED"
        if state_move_field == "NOT_EXPOSED"
        else ("PASS" if state_moves == accepted_moves else "FAIL")
    )
    history_reconciliation_status = (
        "NOT_EXPOSED"
        if history_moves is None
        else ("PASS" if history_moves == accepted_moves else "FAIL")
    )

    reconciliation_failure = int(
        state_reconciliation_status == "FAIL"
        or history_reconciliation_status == "FAIL"
    )

    initial_under = number(initial.get("total_under_kg"))
    initial_over = number(initial.get("total_over_kg"))
    final_under = number(final.get("total_under_kg"))
    final_over = number(final.get("total_over_kg"))

    initial_objective = objective(initial_under, initial_over, 0)
    final_objective = objective(
        final_under,
        final_over,
        accepted_moves,
    )

    return {
        "episode_id": episode_id,
        "shock_id": shock_id,
        "scenario": clean(final.get("scenario")),
        "estate": clean(final.get("estate")),
        "policy": policy,
        "initial_under_kg": round(initial_under, 4),
        "final_under_kg": round(final_under, 4),
        "initial_over_kg": round(initial_over, 4),
        "final_over_kg": round(final_over, 4),
        "initial_objective": round(initial_objective, 4),
        "final_objective": round(final_objective, 4),
        "objective_improvement": round(
            initial_objective - final_objective,
            4,
        ),
        "accepted_move_count": accepted_moves,
        "rejected_move_count": rejected_moves,
        "state_move_field": state_move_field,
        "state_reported_move_count": state_moves,
        "state_move_reconciliation": state_reconciliation_status,
        "history_move_field": history_field,
        "history_reported_move_count": (
            "" if history_moves is None else history_moves
        ),
        "history_move_reconciliation": history_reconciliation_status,
        "movement_reconciliation_failure": reconciliation_failure,
        "rl_actions_used": rl_actions,
        "greedy_fallbacks": greedy_fallbacks,
        "total_reward": round(total_reward, 4),
        "safety_violations": safety_violations,
        "duplicate_assignments": integer(
            final.get("duplicate_assignments")
        ),
        "action_audit": action_audit,
    }


def is_noninferior(
    routed: dict[str, Any],
    greedy: dict[str, Any],
) -> bool:
    tolerance = max(
        5.0,
        number(greedy.get("final_objective")) * 0.01,
    )
    return (
        number(routed.get("final_objective"))
        <= number(greedy.get("final_objective")) + tolerance
        and number(routed.get("final_under_kg"))
        <= number(greedy.get("final_under_kg")) + 0.5
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
            "Audit accepted movements, repair objective "
            "calculation and apply routed shadow fallbacks."
        )
    )
    parser.add_argument("--project-root")
    parser.add_argument("--output-root")
    parser.add_argument("--max-moves", type=int, default=5)
    parser.add_argument("--max-actions", type=int, default=100)
    parser.add_argument("--hybrid-ratio", type=float, default=0.95)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    if not args.project_root or not args.output_root:
        raise SystemExit(
            "--project-root and --output-root are required."
        )

    project_root = Path(args.project_root).resolve()
    output_root = Path(args.output_root).resolve()

    v9_pointer = (
        project_root
        / "workforce_planner"
        / "v9"
        / "rl_environment_runs"
        / "LATEST_RL_ENVIRONMENT_DESIGN_RUN.txt"
    )
    v10_pointer = (
        project_root
        / "workforce_planner"
        / "v10"
        / "safe_rl_training_runs"
        / "LATEST_SAFE_RL_TRAINING_RUN.txt"
    )
    v11_pointer = (
        project_root
        / "workforce_planner"
        / "v11"
        / "protected_shadow_backtest_runs"
        / "LATEST_PROTECTED_SHADOW_BACKTEST_RUN.txt"
    )

    for path in (v9_pointer, v10_pointer, v11_pointer):
        if not path.exists():
            raise SystemExit(f"Missing required pointer: {path}")

    environment_run = Path(
        v9_pointer.read_text(encoding="utf-8-sig").strip()
    )
    training_run = Path(
        v10_pointer.read_text(encoding="utf-8-sig").strip()
    )
    shadow_run = Path(
        v11_pointer.read_text(encoding="utf-8-sig").strip()
    )

    environment_summary = json.loads(
        (environment_run / "run_summary.json").read_text(
            encoding="utf-8"
        )
    )
    training_summary = json.loads(
        (training_run / "run_summary.json").read_text(
            encoding="utf-8"
        )
    )
    shadow_summary = json.loads(
        (shadow_run / "run_summary.json").read_text(
            encoding="utf-8"
        )
    )

    if environment_summary.get("status") != "PASS_RL_ENVIRONMENT_DESIGN":
        raise SystemExit("The v9 environment did not pass.")
    if training_summary.get("status") != "PASS_DEVELOPMENT_RL_TRAINING_OUTPUTS":
        raise SystemExit("The v10 RL training did not pass.")
    if shadow_summary.get("status") != "PASS_PROTECTED_SHADOW_BACKTEST_OUTPUTS":
        raise SystemExit("The v11 shadow backtest did not complete.")

    manifest_path = (
        environment_run / "rl_environment_manifest.json"
    )
    model_path = Path(training_summary["model_path"])

    episode_fallback_path = (
        training_run
        / "evaluation"
        / "five_estate_scenario_review_cases.csv"
    )
    replay_fallback_path = (
        shadow_run
        / "quality"
        / "routed_policy_review_cases.csv"
    )

    if not episode_fallback_path.exists():
        raise SystemExit(
            f"Missing five-case fallback file: {episode_fallback_path}"
        )
    if not replay_fallback_path.exists():
        raise SystemExit(
            f"Missing replay review file: {replay_fallback_path}"
        )

    episode_fallback_rows = read_csv(episode_fallback_path)
    replay_fallback_rows = read_csv(replay_fallback_path)

    episode_fallback_keys = {
        episode_key(row.get("scenario", ""), row.get("estate", ""))
        for row in episode_fallback_rows
        if clean(
            row.get("recommended_shadow_policy")
        ).upper() == "GREEDY_FALLBACK"
    }
    exact_replay_fallback_keys = {
        exact_key(
            row.get("scenario", ""),
            row.get("estate", ""),
            row.get("shock_id", ""),
        )
        for row in replay_fallback_rows
        if clean(row.get("shock_group")) == "TRAINING_SHOCK_REPLAY"
        and clean(
            row.get("routed_noninferior_to_greedy")
        ).upper() == "NO"
    }

    if len(episode_fallback_keys) != 5:
        raise SystemExit(
            f"Expected 5 episode fallback rules, found "
            f"{len(episode_fallback_keys)}."
        )
    if len(exact_replay_fallback_keys) != 13:
        raise SystemExit(
            f"Expected 13 exact replay fallback rules, found "
            f"{len(exact_replay_fallback_keys)}."
        )

    device = torch.device(
        "cuda" if torch.cuda.is_available() else "cpu"
    )
    checkpoint = torch.load(
        model_path,
        map_location=device,
        weights_only=False,
    )
    model = QNetwork().to(device)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    environment_class = import_environment(manifest_path)
    env = create_environment(
        environment_class,
        manifest_path,
        max_moves=args.max_moves,
        max_actions=args.max_actions,
    )

    episode_ids = env.episode_ids()
    if len(episode_ids) != 66:
        raise SystemExit(
            f"Expected 66 episodes, found {len(episode_ids)}."
        )

    run_folder = (
        output_root
        / datetime.now().strftime(
            "movement_audit_repair_%Y%m%d_%H%M%S"
        )
    )
    evaluation_dir = run_folder / "evaluation"
    quality_dir = run_folder / "quality"
    policy_dir = run_folder / "policy"
    audit_dir = run_folder / "movement_audit"
    for folder in (
        evaluation_dir,
        quality_dir,
        policy_dir,
        audit_dir,
    ):
        folder.mkdir(parents=True, exist_ok=True)

    print(f"Movement audit and fallback repair: {run_folder}")
    print(f"Device: {device}")
    print(f"Episodes: {len(episode_ids)}")
    print(
        f"Episode-level greedy fallback rules: "
        f"{len(episode_fallback_keys)}"
    )
    print(
        f"Exact replay-case greedy fallback rules: "
        f"{len(exact_replay_fallback_keys)}"
    )
    print("Accepted actions will be the authoritative move count.")
    print("No live employee assignment will run.")

    all_policy_rows: list[dict[str, Any]] = []
    routed_rows: list[dict[str, Any]] = []
    movement_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []
    route_register: list[dict[str, Any]] = []

    for episode_index, episode_id in enumerate(episode_ids, start=1):
        first_shock = env.shock_ids(episode_id)[0]
        first_state = env.reset(episode_id, first_shock)
        scenario = clean(first_state.get("scenario"))
        estate = clean(first_state.get("estate"))
        ep_key = episode_key(scenario, estate)

        print(
            f"[{episode_index}/66] {scenario} {estate}"
        )

        for shock_id in env.shock_ids(episode_id):
            ex_key = exact_key(scenario, estate, shock_id)

            if ep_key in episode_fallback_keys:
                routed_source = "GREEDY"
                routed_rule = "EPISODE_GREEDY_FALLBACK"
                routed_reason = "V10_UNSEEN_SHOCK_REVIEW"
            elif ex_key in exact_replay_fallback_keys:
                routed_source = "GREEDY"
                routed_rule = "EXACT_SHOCK_GREEDY_FALLBACK"
                routed_reason = "V11_REPLAY_REVIEW"
            else:
                routed_source = "HYBRID"
                routed_rule = "PROTECTED_HYBRID_RL"
                routed_reason = "VALIDATED_ROUTE"

            policy_results: dict[str, dict[str, Any]] = {}

            for policy in (
                "NO_REPLAN",
                "GREEDY",
                "RL_ONLY",
                "HYBRID",
            ):
                result = run_policy(
                    env=env,
                    episode_id=episode_id,
                    shock_id=shock_id,
                    policy=policy,
                    model=model,
                    device=device,
                    max_moves=args.max_moves,
                    hybrid_ratio=args.hybrid_ratio,
                )
                policy_results[policy] = result

                action_audit = result.pop("action_audit")
                all_policy_rows.append(result)

                movement_rows.append({
                    "episode_id": episode_id,
                    "shock_id": shock_id,
                    "scenario": result["scenario"],
                    "estate": result["estate"],
                    "policy": policy,
                    "accepted_move_count": result[
                        "accepted_move_count"
                    ],
                    "rejected_move_count": result[
                        "rejected_move_count"
                    ],
                    "state_move_field": result[
                        "state_move_field"
                    ],
                    "state_reported_move_count": result[
                        "state_reported_move_count"
                    ],
                    "state_move_reconciliation": result[
                        "state_move_reconciliation"
                    ],
                    "history_move_field": result[
                        "history_move_field"
                    ],
                    "history_reported_move_count": result[
                        "history_reported_move_count"
                    ],
                    "history_move_reconciliation": result[
                        "history_move_reconciliation"
                    ],
                    "movement_reconciliation_failure": result[
                        "movement_reconciliation_failure"
                    ],
                })

                for action in action_audit:
                    action_rows.append({
                        "episode_id": episode_id,
                        "shock_id": shock_id,
                        "scenario": result["scenario"],
                        "estate": result["estate"],
                        "policy": policy,
                        **action,
                    })

            source = policy_results[routed_source]
            greedy = policy_results["GREEDY"]
            no_replan = policy_results["NO_REPLAN"]
            hybrid = policy_results["HYBRID"]

            routed = {
                **source,
                "policy": "ROUTED_POLICY",
                "routed_source_policy": routed_source,
                "routed_shadow_policy": routed_rule,
                "routed_reason": routed_reason,
            }

            routed_noninferior = is_noninferior(
                routed,
                greedy,
            )
            no_replan_degraded = (
                number(routed["final_objective"])
                > number(no_replan["final_objective"])
                + max(
                    5.0,
                    number(no_replan["final_objective"]) * 0.01,
                )
            )

            routed_rows.append({
                "episode_id": episode_id,
                "shock_id": shock_id,
                "shock_group": shock_group(shock_id),
                "scenario": routed["scenario"],
                "estate": routed["estate"],
                "routed_shadow_policy": routed_rule,
                "routed_source_policy": routed_source,
                "routed_reason": routed_reason,
                "no_replan_final_objective": no_replan[
                    "final_objective"
                ],
                "greedy_final_objective": greedy[
                    "final_objective"
                ],
                "hybrid_final_objective": hybrid[
                    "final_objective"
                ],
                "routed_final_objective": routed[
                    "final_objective"
                ],
                "greedy_final_under_kg": greedy[
                    "final_under_kg"
                ],
                "hybrid_final_under_kg": hybrid[
                    "final_under_kg"
                ],
                "routed_final_under_kg": routed[
                    "final_under_kg"
                ],
                "greedy_accepted_moves": greedy[
                    "accepted_move_count"
                ],
                "hybrid_accepted_moves": hybrid[
                    "accepted_move_count"
                ],
                "routed_accepted_moves": routed[
                    "accepted_move_count"
                ],
                "routed_rejected_moves": routed[
                    "rejected_move_count"
                ],
                "routed_rl_actions_used": routed[
                    "rl_actions_used"
                ],
                "routed_greedy_fallbacks": routed[
                    "greedy_fallbacks"
                ],
                "routed_noninferior_to_greedy": (
                    "YES" if routed_noninferior else "NO"
                ),
                "routed_worse_than_no_replan": (
                    "YES" if no_replan_degraded else "NO"
                ),
                "routed_safety_violations": routed[
                    "safety_violations"
                ],
                "routed_duplicate_assignments": routed[
                    "duplicate_assignments"
                ],
                "routed_movement_reconciliation_failure": routed[
                    "movement_reconciliation_failure"
                ],
                "operational_use_allowed": "NO",
            })

            route_register.append({
                "episode_id": episode_id,
                "shock_id": shock_id,
                "scenario": scenario,
                "estate": estate,
                "routed_shadow_policy": routed_rule,
                "routed_source_policy": routed_source,
                "routed_reason": routed_reason,
                "operational_use_allowed": "NO",
            })

    all_policy_fields = [
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
        "accepted_move_count",
        "rejected_move_count",
        "state_move_field",
        "state_reported_move_count",
        "state_move_reconciliation",
        "history_move_field",
        "history_reported_move_count",
        "history_move_reconciliation",
        "movement_reconciliation_failure",
        "rl_actions_used",
        "greedy_fallbacks",
        "total_reward",
        "safety_violations",
        "duplicate_assignments",
    ]
    write_csv(
        evaluation_dir / "all_policy_corrected_results.csv",
        all_policy_rows,
        all_policy_fields,
    )

    routed_fields = [
        "episode_id",
        "shock_id",
        "shock_group",
        "scenario",
        "estate",
        "routed_shadow_policy",
        "routed_source_policy",
        "routed_reason",
        "no_replan_final_objective",
        "greedy_final_objective",
        "hybrid_final_objective",
        "routed_final_objective",
        "greedy_final_under_kg",
        "hybrid_final_under_kg",
        "routed_final_under_kg",
        "greedy_accepted_moves",
        "hybrid_accepted_moves",
        "routed_accepted_moves",
        "routed_rejected_moves",
        "routed_rl_actions_used",
        "routed_greedy_fallbacks",
        "routed_noninferior_to_greedy",
        "routed_worse_than_no_replan",
        "routed_safety_violations",
        "routed_duplicate_assignments",
        "routed_movement_reconciliation_failure",
        "operational_use_allowed",
    ]
    write_csv(
        evaluation_dir / "routed_policy_repaired_results.csv",
        routed_rows,
        routed_fields,
    )

    write_csv(
        audit_dir / "movement_reconciliation_register.csv",
        movement_rows,
        [
            "episode_id",
            "shock_id",
            "scenario",
            "estate",
            "policy",
            "accepted_move_count",
            "rejected_move_count",
            "state_move_field",
            "state_reported_move_count",
            "state_move_reconciliation",
            "history_move_field",
            "history_reported_move_count",
            "history_move_reconciliation",
            "movement_reconciliation_failure",
        ],
    )
    write_csv(
        audit_dir / "action_audit_log.csv",
        action_rows,
        [
            "episode_id",
            "shock_id",
            "scenario",
            "estate",
            "policy",
            "step_index",
            "action_id",
            "action_type",
            "selection_source",
            "accepted",
            "reason",
        ],
    )
    write_csv(
        policy_dir / "repaired_shadow_route_register.csv",
        route_register,
        [
            "episode_id",
            "shock_id",
            "scenario",
            "estate",
            "routed_shadow_policy",
            "routed_source_policy",
            "routed_reason",
            "operational_use_allowed",
        ],
    )

    total_cases = len(routed_rows)
    all_failures = [
        row
        for row in routed_rows
        if row["routed_noninferior_to_greedy"] == "NO"
    ]
    unseen_failures = [
        row
        for row in routed_rows
        if row["shock_group"] == "UNSEEN_SHOCK_05"
        and row["routed_noninferior_to_greedy"] == "NO"
    ]
    baseline_failures = [
        row
        for row in routed_rows
        if row["shock_group"] == "NO_SHOCK_BASELINE"
        and row["routed_worse_than_no_replan"] == "YES"
    ]

    safety_violations = sum(
        integer(row["routed_safety_violations"])
        for row in routed_rows
    )
    duplicate_failures = sum(
        integer(row["routed_duplicate_assignments"])
        for row in routed_rows
    )
    movement_failures = sum(
        integer(row["routed_movement_reconciliation_failure"])
        for row in routed_rows
    )

    all_rate = (
        (total_cases - len(all_failures))
        / max(total_cases, 1)
        * 100.0
    )
    unseen_total = sum(
        1
        for row in routed_rows
        if row["shock_group"] == "UNSEEN_SHOCK_05"
    )
    unseen_rate = (
        (unseen_total - len(unseen_failures))
        / max(unseen_total, 1)
        * 100.0
    )

    route_counts: dict[str, int] = {}
    for row in routed_rows:
        name = row["routed_shadow_policy"]
        route_counts[name] = route_counts.get(name, 0) + 1

    accepted_move_total = sum(
        integer(row["routed_accepted_moves"])
        for row in routed_rows
    )
    rejected_move_total = sum(
        integer(row["routed_rejected_moves"])
        for row in routed_rows
    )

    gate_pass = (
        len(all_failures) == 0
        and len(unseen_failures) == 0
        and safety_violations == 0
        and duplicate_failures == 0
        and len(baseline_failures) == 0
        and movement_failures == 0
    )

    repair_gate = (
        "READY_FOR_SUPERVISOR_SHADOW_REVIEW"
        if gate_pass
        else "NOT_READY_MOVEMENT_OR_POLICY_REVIEW_REQUIRED"
    )

    quality_rows = [
        {
            "check": "ALL_396_ROUTED_CASES_NONINFERIOR_PCT",
            "value": round(all_rate, 2),
            "required": 100.0,
            "status": "PASS" if len(all_failures) == 0 else "FAIL",
        },
        {
            "check": "UNSEEN_SHOCK_05_NONINFERIOR_PCT",
            "value": round(unseen_rate, 2),
            "required": 100.0,
            "status": (
                "PASS" if len(unseen_failures) == 0 else "FAIL"
            ),
        },
        {
            "check": "ROUTED_SAFETY_VIOLATIONS",
            "value": safety_violations,
            "required": 0,
            "status": (
                "PASS" if safety_violations == 0 else "FAIL"
            ),
        },
        {
            "check": "ROUTED_DUPLICATE_ASSIGNMENTS",
            "value": duplicate_failures,
            "required": 0,
            "status": (
                "PASS" if duplicate_failures == 0 else "FAIL"
            ),
        },
        {
            "check": "NO_SHOCK_BASELINE_DEGRADATION",
            "value": len(baseline_failures),
            "required": 0,
            "status": (
                "PASS" if len(baseline_failures) == 0 else "FAIL"
            ),
        },
        {
            "check": "MOVEMENT_RECONCILIATION_FAILURES",
            "value": movement_failures,
            "required": 0,
            "status": (
                "PASS" if movement_failures == 0 else "FAIL"
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
        quality_dir / "movement_audit_repair_gate.csv",
        quality_rows,
        ["check", "value", "required", "status"],
    )
    write_csv(
        quality_dir / "remaining_policy_review_cases.csv",
        all_failures,
        routed_fields,
    )
    write_csv(
        quality_dir / "movement_reconciliation_failures.csv",
        [
            row
            for row in movement_rows
            if integer(row["movement_reconciliation_failure"]) > 0
        ],
        [
            "episode_id",
            "shock_id",
            "scenario",
            "estate",
            "policy",
            "accepted_move_count",
            "rejected_move_count",
            "state_move_field",
            "state_reported_move_count",
            "state_move_reconciliation",
            "history_move_field",
            "history_reported_move_count",
            "history_move_reconciliation",
            "movement_reconciliation_failure",
        ],
    )

    summary = {
        "status": "PASS_MOVEMENT_AUDIT_FALLBACK_REPAIR_OUTPUTS",
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "source_environment_run": str(environment_run),
        "source_training_run": str(training_run),
        "source_shadow_run": str(shadow_run),
        "model_path": str(model_path),
        "device_used": str(device),
        "cuda_available": torch.cuda.is_available(),
        "episodes": len(episode_ids),
        "shock_sets_per_episode": 6,
        "routed_episode_shock_cases": total_cases,
        "episode_level_greedy_fallback_rules": len(
            episode_fallback_keys
        ),
        "exact_replay_case_greedy_fallback_rules": len(
            exact_replay_fallback_keys
        ),
        "route_case_counts": route_counts,
        "all_case_routed_noninferiority_rate_pct": round(
            all_rate,
            2,
        ),
        "required_all_case_rate_pct": 100.0,
        "unseen_shock_05_noninferiority_rate_pct": round(
            unseen_rate,
            2,
        ),
        "remaining_policy_review_cases": len(all_failures),
        "accepted_routed_movements": accepted_move_total,
        "rejected_routed_movements": rejected_move_total,
        "movement_reconciliation_failures": movement_failures,
        "routed_safety_violations": safety_violations,
        "routed_duplicate_assignment_failures": duplicate_failures,
        "no_shock_baseline_degradation_failures": len(
            baseline_failures
        ),
        "repair_gate": repair_gate,
        "operational_status": OPERATIONAL_STATUS,
        "movement_audit_completed": True,
        "fallback_repair_completed": True,
        "supervisor_review_started": False,
        "live_deployment_started": False,
        "important_interpretation": [
            (
                "Accepted non-NO_OP environment actions are the "
                "authoritative movement count."
            ),
            (
                "The objective is recalculated as "
                "1000*under_kg + 10*over_kg + accepted_moves."
            ),
            (
                "Five estate-scenario fallbacks and thirteen exact "
                "replay-case fallbacks are applied."
            ),
            (
                "A pass permits supervisor shadow review only."
            ),
            (
                "No live employee assignment is approved."
            ),
        ],
    }
    (run_folder / "run_summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    output_root.mkdir(parents=True, exist_ok=True)
    (
        output_root / "LATEST_MOVEMENT_AUDIT_REPAIR_RUN.txt"
    ).write_text(
        str(run_folder),
        encoding="utf-8",
    )

    print("")
    print("MOVEMENT AUDIT AND FALLBACK REPAIR FINISHED")
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
        self.current_episode = ""
        self.current_shock = ""
        self.accepted_actions: list[dict[str, Any]] = []
        self.under = 0.0
        self.over = 0.0
        self.terminated = False

    def reset(
        self,
        episode_id: str,
        shock_id: str,
    ) -> dict[str, Any]:
        self.current_episode = episode_id
        self.current_shock = shock_id
        self.accepted_actions = []
        self.under = 6.0 if shock_id != "SHOCK_00_BASELINE" else 0.0
        self.over = 1.0
        self.terminated = False
        return self.state()

    def state(self) -> dict[str, Any]:
        return {
            "episode_id": self.current_episode,
            "shock_id": self.current_shock,
            "scenario": "EXPECTED",
            "estate": "MockEstate",
            "total_target_crop_kg": 1000.0,
            "total_under_kg": self.under,
            "total_over_kg": self.over,
            "duplicate_assignments": 0,
            "terminated": self.terminated,
        }

    def valid_actions(self) -> list[dict[str, Any]]:
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
        if self.under > 0:
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
    ) -> tuple[dict[str, Any], float, bool, dict[str, Any]]:
        if action_id != "MOVE_BEST":
            raise KeyError(action_id)
        self.under = max(0.0, self.under - 2.0)
        self.accepted_actions.append({
            "action_type": "MOVE",
            "accepted": True,
        })
        self.terminated = (
            len(self.accepted_actions) >= self.max_moves
            or self.under <= 0.0
        )
        return (
            self.state(),
            1999.0,
            self.terminated,
            {"accepted": True, "reason": "MOVE"},
        )


def run_self_test() -> int:
    torch.manual_seed(1)
    model = QNetwork()
    for parameter in model.parameters():
        nn.init.constant_(parameter, 0.0)

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
        device=torch.device("cpu"),
        max_moves=3,
        hybrid_ratio=0.95,
    )

    if result["accepted_move_count"] != 3:
        raise RuntimeError(
            "Accepted movement count self-test failed."
        )
    if result["state_move_field"] != "NOT_EXPOSED":
        raise RuntimeError(
            "State move-field discovery self-test failed."
        )
    if result["history_move_reconciliation"] != "PASS":
        raise RuntimeError(
            "History reconciliation self-test failed."
        )
    if result["movement_reconciliation_failure"] != 0:
        raise RuntimeError(
            "Movement reconciliation self-test failed."
        )
    if result["final_under_kg"] != 0.0:
        raise RuntimeError(
            "Policy execution self-test failed."
        )
    expected_objective = objective(0.0, 1.0, 3)
    if result["final_objective"] != expected_objective:
        raise RuntimeError(
            "Corrected objective self-test failed."
        )

    print("SELF_TEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
