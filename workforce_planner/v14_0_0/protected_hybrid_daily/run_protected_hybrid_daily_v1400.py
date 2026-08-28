from __future__ import annotations

import argparse
import csv
import hashlib
import html
import importlib.util
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

VERSION = "14.0.0"
FEATURE_COUNT = 10


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


def norm(value: Any) -> str:
    return "".join(ch for ch in clean(value).lower() if ch.isalnum())


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def episode_key(scenario: str, estate: str) -> tuple[str, str]:
    return clean(scenario).upper(), norm(estate)


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


def resolved_state_move_count(state: dict[str, Any]) -> int:
    for field in ("move_count", "moves", "movement_count", "accepted_moves"):
        if field in state and clean(state.get(field)) != "":
            return integer(state.get(field))
    return 0


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
        resolved_state_move_count(state) / max(max_moves, 1),
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
            {"accepted": True, "reason": "PROTECTED_NO_OP_TERMINATED"},
        )
    return env.step(action_id)


def import_environment(manifest_path: Path) -> Any:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    code_path = Path(manifest["environment_code_path"])
    spec = importlib.util.spec_from_file_location(
        "tte_v14_environment_runtime",
        code_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import environment: {code_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.TTEWorkforceRLEnvironment


def objective(under_kg: float, over_kg: float, accepted_moves: int) -> float:
    return 1000.0 * under_kg + 10.0 * over_kg + float(accepted_moves)


def run_policy(
    env: Any,
    episode_id: str,
    policy: str,
    model: QNetwork,
    device: torch.device,
    max_moves: int,
    hybrid_ratio: float,
    capture_final: bool = False,
) -> dict[str, Any]:
    initial = env.reset(episode_id, "SHOCK_00_BASELINE")
    initial_assignment = dict(env.employee_field)
    total_reward = 0.0
    rl_actions = 0
    greedy_fallbacks = 0
    accepted_moves = 0
    rejected_moves = 0
    safety_violations = 0
    action_audit: list[dict[str, Any]] = []

    for step_index in range(max_moves + 1):
        state = env.state()
        featured = attach_features(state, env.valid_actions(), max_moves)
        greedy = greedy_action(featured)
        values: torch.Tensor | None = None
        rl_selected: tuple[dict[str, Any], np.ndarray] | None = None
        rl_q_value: float | None = None

        if policy == "GREEDY":
            selected = greedy
            selection_source = "GREEDY"
        elif policy == "HYBRID":
            values = model_values(model, featured, device)
            rl_index = int(torch.argmax(values).item())
            rl_selected = featured[rl_index]
            rl_q_value = float(values[rl_index].detach().cpu().item())
            greedy_reward = max(
                0.0,
                number(greedy[0].get("projected_reward")),
            )
            rl_reward = number(rl_selected[0].get("projected_reward"))
            rl_is_move = (
                clean(rl_selected[0].get("action_type")).upper() != "NO_OP"
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
                if clean(greedy[0].get("action_type")).upper() != "NO_OP":
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
            "policy_tested": policy,
            "selection_source": selection_source,
            "selected_action_id": action_id,
            "selected_action_type": action_type,
            "selected_projected_reward": round(
                number(action.get("projected_reward")), 6
            ),
            "selected_safe_action": clean(action.get("safe_action")),
            "selected_action_accepted": "YES" if accepted else "NO",
            "environment_reason": clean(info.get("reason")),
            "greedy_action_id": clean(greedy[0].get("action_id")),
            "greedy_projected_reward": round(
                number(greedy[0].get("projected_reward")), 6
            ),
            "rl_action_id": (
                "" if rl_selected is None else clean(rl_selected[0].get("action_id"))
            ),
            "rl_projected_reward": (
                "" if rl_selected is None
                else round(number(rl_selected[0].get("projected_reward")), 6)
            ),
            "rl_q_value": "" if rl_q_value is None else round(rl_q_value, 8),
        })

        if done:
            break

    final = env.state()
    final_assignment = dict(env.employee_field)
    final_productivity = dict(env.employee_productivity)

    initial_under = number(initial.get("total_under_kg"))
    initial_over = number(initial.get("total_over_kg"))
    final_under = number(final.get("total_under_kg"))
    final_over = number(final.get("total_over_kg"))

    result: dict[str, Any] = {
        "episode_id": episode_id,
        "scenario": clean(final.get("scenario")),
        "estate": clean(final.get("estate")),
        "policy": policy,
        "initial_under_kg": round(initial_under, 4),
        "final_under_kg": round(final_under, 4),
        "initial_over_kg": round(initial_over, 4),
        "final_over_kg": round(final_over, 4),
        "initial_objective": round(objective(initial_under, initial_over, 0), 4),
        "final_objective": round(
            objective(final_under, final_over, accepted_moves), 4
        ),
        "accepted_move_count": accepted_moves,
        "rejected_move_count": rejected_moves,
        "rl_actions_used": rl_actions,
        "greedy_fallbacks": greedy_fallbacks,
        "total_reward": round(total_reward, 4),
        "safety_violations": safety_violations,
        "duplicate_assignments": (
            len(final_assignment) - len(set(final_assignment))
        ),
        "action_audit": action_audit,
    }
    if capture_final:
        result["initial_assignment"] = initial_assignment
        result["final_assignment"] = final_assignment
        result["final_productivity"] = final_productivity
        result["final_fields"] = {
            uid: {
                "division": clean(row.get("division")),
                "field": clean(row.get("field")),
                "target": number(row.get("target")),
                "capacity": number(row.get("capacity")),
                "employees": sorted(row.get("employees", set())),
            }
            for uid, row in env.fields.items()
        }
    return result


def is_noninferior(
    routed: dict[str, Any],
    greedy: dict[str, Any],
) -> bool:
    tolerance = max(5.0, number(greedy.get("final_objective")) * 0.01)
    return (
        number(routed.get("final_objective"))
        <= number(greedy.get("final_objective")) + tolerance
        and number(routed.get("final_under_kg"))
        <= number(greedy.get("final_under_kg")) + 0.5
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--route-register", required=True)
    parser.add_argument("--allocation-date", required=True)
    parser.add_argument("--output-folder", required=True)
    parser.add_argument("--max-moves", type=int, default=5)
    parser.add_argument("--max-actions", type=int, default=100)
    parser.add_argument("--hybrid-ratio", type=float, default=0.95)
    parser.add_argument("--expected-episodes", type=int, default=66)
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    model_path = Path(args.model_path).resolve()
    route_path = Path(args.route_register).resolve()
    output = Path(args.output_folder).resolve()
    output.mkdir(parents=True, exist_ok=True)

    for path in (manifest_path, model_path, route_path):
        if not path.exists():
            raise SystemExit(f"Missing required input: {path}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    checkpoint = torch.load(model_path, map_location=device, weights_only=False)
    if integer(checkpoint.get("feature_count"), FEATURE_COUNT) != FEATURE_COUNT:
        raise SystemExit("RL checkpoint feature count is not 10.")

    model = QNetwork().to(device)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    environment_class = import_environment(manifest_path)
    env = environment_class(
        manifest_path,
        max_moves=args.max_moves,
        max_actions=args.max_actions,
    )

    episode_ids = env.episode_ids()
    if len(episode_ids) != args.expected_episodes:
        raise SystemExit(
            f"Expected {args.expected_episodes} episodes, found {len(episode_ids)}."
        )

    route_rows = read_csv(route_path)
    baseline_routes = {
        episode_key(row.get("scenario", ""), row.get("estate", "")): row
        for row in route_rows
        if clean(row.get("shock_id")).upper() == "SHOCK_00_BASELINE"
    }

    decision_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []
    assignment_rows: list[dict[str, Any]] = []
    field_rows: list[dict[str, Any]] = []

    for index, episode_id in enumerate(episode_ids, start=1):
        baseline = env.reset(episode_id, "SHOCK_00_BASELINE")
        scenario = clean(baseline.get("scenario")).upper()
        estate = clean(baseline.get("estate"))
        route = baseline_routes.get(episode_key(scenario, estate))
        if route is None:
            raise SystemExit(f"Missing baseline route for {scenario} {estate}.")

        configured_policy = clean(route.get("routed_shadow_policy"))
        configured_source = clean(route.get("routed_source_policy")).upper()
        configured_reason = clean(route.get("routed_reason"))

        print(
            f"[{index}/{len(episode_ids)}] {args.allocation_date} "
            f"{scenario} {estate} -> {configured_policy}",
            flush=True,
        )

        greedy = run_policy(
            env, episode_id, "GREEDY", model, device,
            args.max_moves, args.hybrid_ratio,
        )

        hybrid: dict[str, Any] | None = None
        if configured_source == "HYBRID":
            hybrid = run_policy(
                env, episode_id, "HYBRID", model, device,
                args.max_moves, args.hybrid_ratio,
            )
            hybrid_pass = (
                is_noninferior(hybrid, greedy)
                and integer(hybrid.get("safety_violations")) == 0
                and integer(hybrid.get("duplicate_assignments")) == 0
            )
            if hybrid_pass:
                selected_policy = "HYBRID"
                final_route = "PROTECTED_HYBRID_RL"
                final_reason = "VALIDATED_ROUTE_AND_RUNTIME_GATE_PASS"
            else:
                selected_policy = "GREEDY"
                final_route = "RUNTIME_GREEDY_FALLBACK"
                final_reason = "RUNTIME_NONINFERIORITY_OR_SAFETY_GATE"
        else:
            hybrid_pass = False
            selected_policy = "GREEDY"
            final_route = configured_policy or "EPISODE_GREEDY_FALLBACK"
            final_reason = configured_reason or "CONFIGURED_GREEDY_FALLBACK"

        selected = run_policy(
            env, episode_id, selected_policy, model, device,
            args.max_moves, args.hybrid_ratio, capture_final=True,
        )

        decision_rows.append({
            "allocation_date": args.allocation_date,
            "episode_id": episode_id,
            "scenario": scenario,
            "estate": estate,
            "configured_shadow_policy": configured_policy,
            "configured_source_policy": configured_source,
            "configured_reason": configured_reason,
            "rl_model_invoked": "YES" if configured_source == "HYBRID" else "NO",
            "runtime_hybrid_noninferior": (
                "YES" if configured_source == "HYBRID" and hybrid_pass
                else ("NO" if configured_source == "HYBRID" else "NOT_APPLICABLE")
            ),
            "final_allocation_policy": final_route,
            "final_policy_source": selected_policy,
            "final_policy_reason": final_reason,
            "greedy_final_objective": greedy["final_objective"],
            "hybrid_final_objective": (
                "" if hybrid is None else hybrid["final_objective"]
            ),
            "selected_final_objective": selected["final_objective"],
            "selected_final_under_kg": selected["final_under_kg"],
            "selected_final_over_kg": selected["final_over_kg"],
            "accepted_move_count": selected["accepted_move_count"],
            "rl_actions_used": selected["rl_actions_used"],
            "hybrid_greedy_fallbacks": selected["greedy_fallbacks"],
            "safety_violations": selected["safety_violations"],
            "duplicate_assignments": selected["duplicate_assignments"],
            "device_used": str(device),
            "operational_use_allowed": "NO",
            "live_assignment_authorized": "NO",
        })

        for audit in selected["action_audit"]:
            action_rows.append({
                "allocation_date": args.allocation_date,
                "episode_id": episode_id,
                "scenario": scenario,
                "estate": estate,
                "final_allocation_policy": final_route,
                **audit,
                "operational_use_allowed": "NO",
            })

        initial_assignment: dict[str, str] = selected["initial_assignment"]
        final_assignment: dict[str, str] = selected["final_assignment"]
        final_productivity: dict[str, float] = selected["final_productivity"]
        candidate_lookup = env._load_candidates(estate)

        for employee_id, final_uid in sorted(final_assignment.items()):
            initial_uid = initial_assignment.get(employee_id, "")
            field_info = selected["final_fields"][final_uid]
            candidate = candidate_lookup.get((employee_id, final_uid), {})
            assignment_rows.append({
                "allocation_date": args.allocation_date,
                "scenario": scenario,
                "estate": estate,
                "employee_key": f"{estate}|{employee_id}",
                "employee_id": employee_id,
                "division": field_info["division"],
                "field": field_info["field"],
                "field_uid": final_uid,
                "baseline_field_uid": initial_uid,
                "rl_moved_employee": "YES" if initial_uid != final_uid else "NO",
                "expected_productivity_kg": round(
                    number(final_productivity.get(employee_id)), 4
                ),
                "candidate_scope": clean(candidate.get("scope")),
                "cross_division": clean(candidate.get("cross_division")) or "NO",
                "final_allocation_policy": final_route,
                "rl_model_invoked": "YES" if configured_source == "HYBRID" else "NO",
                "safety_shield_enabled": "YES",
                "greedy_fallback_enabled": "YES",
                "employee_home_code_verified": "NO",
                "attendance_verified": "NO",
                "approved_leave_verified": "NO",
                "fitness_verified": "NO",
                "movement_restrictions_verified": "NO",
                "operational_use_allowed": "NO",
                "live_assignment_authorized": "NO",
                "allocation_status": "PROTECTED_HYBRID_RL_SHADOW_SIMULATION_ONLY",
            })

        for field_uid, field_info in sorted(selected["final_fields"].items()):
            target = number(field_info["target"])
            capacity = number(field_info["capacity"])
            field_rows.append({
                "allocation_date": args.allocation_date,
                "scenario": scenario,
                "estate": estate,
                "division": field_info["division"],
                "field": field_info["field"],
                "field_uid": field_uid,
                "target_crop_kg": round(target, 4),
                "assigned_capacity_kg": round(capacity, 4),
                "under_kg": round(max(0.0, target - capacity), 4),
                "over_kg": round(max(0.0, capacity - target), 4),
                "assigned_employee_count": len(field_info["employees"]),
                "final_allocation_policy": final_route,
                "operational_use_allowed": "NO",
            })

    decision_fields = [
        "allocation_date", "episode_id", "scenario", "estate",
        "configured_shadow_policy", "configured_source_policy",
        "configured_reason", "rl_model_invoked",
        "runtime_hybrid_noninferior", "final_allocation_policy",
        "final_policy_source", "final_policy_reason",
        "greedy_final_objective", "hybrid_final_objective",
        "selected_final_objective", "selected_final_under_kg",
        "selected_final_over_kg", "accepted_move_count",
        "rl_actions_used", "hybrid_greedy_fallbacks",
        "safety_violations", "duplicate_assignments", "device_used",
        "operational_use_allowed", "live_assignment_authorized",
    ]
    action_fields = [
        "allocation_date", "episode_id", "scenario", "estate",
        "final_allocation_policy", "step_index", "policy_tested",
        "selection_source", "selected_action_id", "selected_action_type",
        "selected_projected_reward", "selected_safe_action",
        "selected_action_accepted", "environment_reason",
        "greedy_action_id", "greedy_projected_reward", "rl_action_id",
        "rl_projected_reward", "rl_q_value", "operational_use_allowed",
    ]
    assignment_fields = [
        "allocation_date", "scenario", "estate", "employee_key",
        "employee_id", "division", "field", "field_uid",
        "baseline_field_uid", "rl_moved_employee",
        "expected_productivity_kg", "candidate_scope", "cross_division",
        "final_allocation_policy", "rl_model_invoked",
        "safety_shield_enabled", "greedy_fallback_enabled",
        "employee_home_code_verified", "attendance_verified",
        "approved_leave_verified", "fitness_verified",
        "movement_restrictions_verified", "operational_use_allowed",
        "live_assignment_authorized", "allocation_status",
    ]
    field_fields = [
        "allocation_date", "scenario", "estate", "division", "field",
        "field_uid", "target_crop_kg", "assigned_capacity_kg",
        "under_kg", "over_kg", "assigned_employee_count",
        "final_allocation_policy", "operational_use_allowed",
    ]

    write_csv(output / "protected_hybrid_rl_policy_decisions.csv", decision_rows, decision_fields)
    write_csv(output / "protected_hybrid_rl_action_audit.csv", action_rows, action_fields)
    write_csv(output / "protected_hybrid_rl_employee_allocations.csv", assignment_rows, assignment_fields)
    write_csv(output / "protected_hybrid_rl_field_results.csv", field_rows, field_fields)

    policy_counts = Counter(row["final_allocation_policy"] for row in decision_rows)
    configured_hybrid = sum(
        row["configured_source_policy"] == "HYBRID" for row in decision_rows
    )
    model_invoked = sum(row["rl_model_invoked"] == "YES" for row in decision_rows)
    safety_failures = sum(integer(row["safety_violations"]) for row in decision_rows)
    duplicate_failures = sum(integer(row["duplicate_assignments"]) for row in decision_rows)
    live_yes = sum(row["live_assignment_authorized"] != "NO" for row in decision_rows)

    gate_rows = [
        {"check": "EPISODES", "value": len(decision_rows), "required": args.expected_episodes,
         "status": "PASS" if len(decision_rows) == args.expected_episodes else "FAIL"},
        {"check": "CONFIGURED_HYBRID_ROUTES", "value": configured_hybrid, "required": 61,
         "status": "PASS" if args.expected_episodes != 66 or configured_hybrid == 61 else "FAIL"},
        {"check": "RL_MODEL_INVOKED_EPISODES", "value": model_invoked, "required": configured_hybrid,
         "status": "PASS" if model_invoked == configured_hybrid else "FAIL"},
        {"check": "SAFETY_VIOLATIONS", "value": safety_failures, "required": 0,
         "status": "PASS" if safety_failures == 0 else "FAIL"},
        {"check": "DUPLICATE_ASSIGNMENTS", "value": duplicate_failures, "required": 0,
         "status": "PASS" if duplicate_failures == 0 else "FAIL"},
        {"check": "LIVE_ASSIGNMENT_AUTHORIZED", "value": live_yes, "required": 0,
         "status": "PASS" if live_yes == 0 else "FAIL"},
    ]
    write_csv(
        output / "protected_hybrid_rl_allocation_gate.csv",
        gate_rows,
        ["check", "value", "required", "status"],
    )
    gate_failures = sum(row["status"] != "PASS" for row in gate_rows)

    summary = {
        "status": (
            "PASS_PROTECTED_HYBRID_RL_DAILY_SHADOW_ALLOCATION"
            if gate_failures == 0
            else "PROTECTED_HYBRID_RL_DAILY_REVIEW_REQUIRED"
        ),
        "package_version": VERSION,
        "allocation_date": args.allocation_date,
        "episodes": len(decision_rows),
        "employee_allocation_rows": len(assignment_rows),
        "field_rows": len(field_rows),
        "configured_protected_hybrid_routes": configured_hybrid,
        "rl_model_invoked_episodes": model_invoked,
        "final_policy_counts": dict(policy_counts),
        "rl_actions_used": sum(integer(row["rl_actions_used"]) for row in decision_rows),
        "hybrid_greedy_fallbacks": sum(
            integer(row["hybrid_greedy_fallbacks"]) for row in decision_rows
        ),
        "safety_violations": safety_failures,
        "duplicate_assignment_failures": duplicate_failures,
        "device_used": str(device),
        "cuda_available": torch.cuda.is_available(),
        "model_path": str(model_path),
        "model_sha256": sha256_file(model_path),
        "model_checkpoint_version": clean(checkpoint.get("package_version")),
        "route_register": str(route_path),
        "manifest": str(manifest_path),
        "protected_hybrid_rl_allocation_used": True,
        "safety_shield_enabled": True,
        "greedy_fallback_enabled": True,
        "employee_home_code_verified": False,
        "attendance_verified": False,
        "approved_leave_verified": False,
        "fitness_verified": False,
        "movement_restrictions_verified": False,
        "operational_use_allowed": False,
        "live_assignment_authorized": False,
    }
    (output / "run_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    table_rows = "".join(
        "<tr>"
        f"<td>{html.escape(row['scenario'])}</td>"
        f"<td>{html.escape(row['estate'])}</td>"
        f"<td>{html.escape(row['final_allocation_policy'])}</td>"
        f"<td>{html.escape(row['rl_model_invoked'])}</td>"
        f"<td>{row['rl_actions_used']}</td>"
        f"<td>{row['accepted_move_count']}</td>"
        f"<td>{row['selected_final_under_kg']}</td>"
        "</tr>"
        for row in decision_rows
    )
    dashboard = f"""<!DOCTYPE html>
<html lang='en'><head><meta charset='utf-8'>
<title>TTE Protected Hybrid RL Allocation</title>
<style>
body{{font-family:Arial,sans-serif;margin:28px;color:#222}}
h1,h2{{color:#1b5e20}}.cards{{display:grid;grid-template-columns:repeat(4,minmax(170px,1fr));gap:12px}}
.card{{background:#f3f8f3;border:1px solid #c8e6c9;border-radius:8px;padding:16px}}
.card strong{{display:block;font-size:24px;color:#1b5e20}}
.notice{{background:#fff8e1;border-left:6px solid #f9a825;padding:14px;margin:18px 0}}
table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{border:1px solid #ddd;padding:7px;text-align:left}}
th{{background:#2e7d32;color:#fff}}tr:nth-child(even){{background:#f7f7f7}}
</style></head><body>
<h1>TTE Protected Hybrid RL Employee Allocation</h1>
<p><strong>Date:</strong> {html.escape(args.allocation_date)}</p>
<div class='cards'>
<div class='card'><strong>YES</strong>Protected hybrid RL system</div>
<div class='card'><strong>{model_invoked}</strong>RL model-invoked episodes</div>
<div class='card'><strong>{len(assignment_rows):,}</strong>Named employee rows</div>
<div class='card'><strong>{html.escape(str(device))}</strong>Inference device</div>
</div>
<div class='notice'>This is a protected shadow simulation. The safety shield and greedy fallback are active. Attendance, leave, fitness, movement restrictions, home-code verification and live authorization remain NO.</div>
<h2>Policy decisions</h2>
<table><thead><tr><th>Scenario</th><th>Estate</th><th>Final policy</th><th>RL invoked</th><th>RL actions</th><th>Moves</th><th>Final under kg</th></tr></thead><tbody>{table_rows}</tbody></table>
<h2>Files</h2>
<p><a href='protected_hybrid_rl_employee_allocations.csv'>Named employee allocations</a></p>
<p><a href='protected_hybrid_rl_policy_decisions.csv'>Policy decisions</a></p>
<p><a href='protected_hybrid_rl_action_audit.csv'>RL action audit</a></p>
<p><a href='protected_hybrid_rl_field_results.csv'>Field results</a></p>
<p><a href='protected_hybrid_rl_allocation_gate.csv'>Safety gate</a></p>
</body></html>"""
    (output / "START_HERE.html").write_text(dashboard, encoding="utf-8")

    print("\nPROTECTED HYBRID RL DAILY ALLOCATION FINISHED")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
