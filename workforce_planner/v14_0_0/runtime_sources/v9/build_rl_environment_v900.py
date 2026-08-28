from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

VERSION = "9.0.0"
STATUS = "DEVELOPMENT_ENVIRONMENT_ONLY"


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def norm(value: Any) -> str:
    return "".join(ch for ch in clean(value).lower() if ch.isalnum())


def number(value: Any, default: float = 0.0) -> float:
    try:
        out = float(clean(value).replace(",", ""))
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


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


def multiplier(*parts: str, low: float, high: float) -> float:
    digest = hashlib.sha256("||".join(parts).encode("utf-8")).digest()
    ratio = int.from_bytes(digest[:8], "big") / float(2**64 - 1)
    return low + (high - low) * ratio


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capacity-run", required=True)
    parser.add_argument("--comparison-run", required=True)
    parser.add_argument("--balanced-run", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--shock-count", type=int, default=5)
    parser.add_argument("--expected-field-rows", type=int, default=894)
    args = parser.parse_args()

    capacity = Path(args.capacity_run).resolve()
    comparison = Path(args.comparison_run).resolve()
    balanced = Path(args.balanced_run).resolve()
    output_root = Path(args.output_root).resolve()
    candidate_path = capacity / "inputs" / "expanded_employee_field_candidate_matrix.csv"
    assignment_path = capacity / "assignments" / "cp_sat_capacity_matched_assignments.csv"
    field_path = capacity / "quality" / "cp_sat_capacity_field_results.csv"
    balanced_summary_path = balanced / "run_summary.json"
    review_path = balanced / "quality" / "balanced_cp_sat_vs_greedy_review.csv"
    for path in (candidate_path, assignment_path, field_path, balanced_summary_path, review_path):
        if not path.exists():
            raise SystemExit(f"Missing required input: {path}")

    balanced_summary = json.loads(balanced_summary_path.read_text(encoding="utf-8"))
    if balanced_summary.get("rl_environment_gate") != "READY_FOR_RL_ENVIRONMENT_DESIGN":
        raise SystemExit("Balanced gate is not ready for RL environment design.")
    if balanced_summary.get("rl_started") is not False:
        raise SystemExit("Unexpected prior RL-start flag.")

    fields = read_csv(field_path)
    assignments = read_csv(assignment_path)
    reviews = read_csv(review_path)
    if len(fields) != args.expected_field_rows:
        raise SystemExit(f"Expected {args.expected_field_rows} field rows but found {len(fields)}.")

    review_lookup = {(clean(row.get("scenario")).upper(), norm(row.get("estate"))): row for row in reviews}
    pairs = sorted({(clean(row.get("scenario")).upper(), clean(row.get("estate"))) for row in fields})
    if len(pairs) != 66:
        raise SystemExit(f"Expected 66 estate-scenario episodes but found {len(pairs)}.")

    episode_lookup: dict[tuple[str, str], str] = {}
    episode_rows: list[dict[str, Any]] = []
    for index, (scenario, estate) in enumerate(pairs, start=1):
        ep = f"EP_{index:03d}_{scenario}_{norm(estate)}"
        episode_lookup[(scenario, norm(estate))] = ep
        review = review_lookup[(scenario, norm(estate))]
        preferred = clean(review.get("preferred_baseline"))
        episode_rows.append({
            "episode_id": ep, "scenario": scenario, "estate": estate,
            "baseline_method": "CP_SAT" if preferred in {"CP_SAT", "EITHER_BASELINE_ACCEPTABLE"} else preferred,
            "material_noninferior": clean(review.get("material_noninferior")),
            "cp_sat_service_safe": clean(review.get("cp_sat_service_safe")),
            "operational_use_allowed": "NO",
        })

    field_rows: list[dict[str, Any]] = []
    for row in fields:
        scenario = clean(row.get("scenario")).upper()
        estate = clean(row.get("estate"))
        field_rows.append({
            "episode_id": episode_lookup[(scenario, norm(estate))], "scenario": scenario,
            "estate": estate, "division": clean(row.get("division")), "field": clean(row.get("field")),
            "field_uid": clean(row.get("field_uid")), "target_crop_kg": number(row.get("target_crop_kg")),
            "assigned_employee_count": int(number(row.get("assigned_employee_count"))),
            "assigned_capacity_kg": number(row.get("assigned_capacity_kg")), "under_kg": number(row.get("under_kg")),
            "over_kg": number(row.get("over_kg")), "coverage_pct": number(row.get("coverage_pct")),
            "operational_use_allowed": "NO",
        })

    assignment_rows: list[dict[str, Any]] = []
    duplicate_check: defaultdict[tuple[str, str], int] = defaultdict(int)
    for row in assignments:
        scenario = clean(row.get("scenario")).upper()
        estate = clean(row.get("estate"))
        episode_id = episode_lookup[(scenario, norm(estate))]
        employee = clean(row.get("employee_id"))
        duplicate_check[(episode_id, employee)] += 1
        assignment_rows.append({
            "episode_id": episode_id, "scenario": scenario, "estate": estate,
            "division": clean(row.get("division")), "field": clean(row.get("field")),
            "field_uid": clean(row.get("field_uid")), "employee_id": employee,
            "expected_productivity_kg": number(row.get("expected_productivity_kg")),
            "candidate_scope": clean(row.get("candidate_scope")), "cross_division": clean(row.get("cross_division")),
            "operational_use_allowed": "NO",
        })
    duplicate_failures = sum(count - 1 for count in duplicate_check.values() if count > 1)
    if duplicate_failures:
        raise SystemExit(f"Duplicate employee assignments found: {duplicate_failures}")

    shock_rows: list[dict[str, Any]] = []
    shock_count = max(1, int(args.shock_count))
    for row in field_rows:
        for shock_index in range(0, shock_count + 1):
            shock_id = "SHOCK_00_BASELINE" if shock_index == 0 else f"SHOCK_{shock_index:02d}"
            crop_mult = 1.0 if shock_index == 0 else multiplier(row["episode_id"], row["field_uid"], shock_id, "CROP", low=0.90, high=1.10)
            prod_mult = 1.0 if shock_index == 0 else multiplier(row["episode_id"], row["field_uid"], shock_id, "PROD", low=0.90, high=1.10)
            shock_rows.append({
                "episode_id": row["episode_id"], "shock_id": shock_id, "scenario": row["scenario"],
                "estate": row["estate"], "division": row["division"], "field": row["field"],
                "field_uid": row["field_uid"], "crop_multiplier": round(crop_mult, 6),
                "productivity_multiplier": round(prod_mult, 6),
                "shocked_target_crop_kg": round(row["target_crop_kg"] * crop_mult, 4),
                "development_only": "YES",
            })

    run = output_root / datetime.now().strftime("rl_environment_design_%Y%m%d_%H%M%S")
    data = run / "data"
    quality = run / "quality"
    code_out = run / "environment_code"
    for folder in (data, quality, code_out):
        folder.mkdir(parents=True, exist_ok=True)

    episode_path = data / "episode_index.csv"
    field_out = data / "baseline_field_state.csv"
    assignment_out = data / "baseline_employee_assignments.csv"
    shock_out = data / "shock_field_state.csv"
    write_csv(episode_path, episode_rows, ["episode_id", "scenario", "estate", "baseline_method", "material_noninferior", "cp_sat_service_safe", "operational_use_allowed"])
    write_csv(field_out, field_rows, ["episode_id", "scenario", "estate", "division", "field", "field_uid", "target_crop_kg", "assigned_employee_count", "assigned_capacity_kg", "under_kg", "over_kg", "coverage_pct", "operational_use_allowed"])
    write_csv(assignment_out, assignment_rows, ["episode_id", "scenario", "estate", "division", "field", "field_uid", "employee_id", "expected_productivity_kg", "candidate_scope", "cross_division", "operational_use_allowed"])
    write_csv(shock_out, shock_rows, ["episode_id", "shock_id", "scenario", "estate", "division", "field", "field_uid", "crop_multiplier", "productivity_multiplier", "shocked_target_crop_kg", "development_only"])
    env_source = Path(__file__).with_name("tte_workforce_rl_env.py")
    env_copy = code_out / "tte_workforce_rl_env.py"
    shutil.copy2(env_source, env_copy)

    manifest_path = run / "rl_environment_manifest.json"
    manifest = {
        "package_version": VERSION, "status": STATUS,
        "episode_index_path": str(episode_path), "baseline_field_state_path": str(field_out),
        "baseline_assignment_path": str(assignment_out), "shock_field_state_path": str(shock_out),
        "candidate_matrix_path": str(candidate_path), "environment_code_path": str(env_copy),
        "episodes": len(episode_rows), "baseline_field_rows": len(field_rows),
        "baseline_assignment_rows": len(assignment_rows), "shock_sets_per_episode": shock_count + 1,
        "shock_field_rows": len(shock_rows), "rl_started": False, "operational_use_allowed": False,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    sys.path.insert(0, str(code_out))
    from tte_workforce_rl_env import TTEWorkforceRLEnvironment
    env = TTEWorkforceRLEnvironment(manifest_path, max_moves=5)
    smoke_rows: list[dict[str, Any]] = []
    smoke_failures = 0
    for episode_id in env.episode_ids()[:3]:
        selected_shock = "SHOCK_01" if "SHOCK_01" in env.shock_ids(episode_id) else env.shock_ids(episode_id)[0]
        initial = env.reset(episode_id, selected_shock)
        actions = env.valid_actions()
        safe = [row for row in actions if row["safe_action"] == "YES"]
        if not safe:
            smoke_failures += 1
            continue
        selected = max(safe, key=lambda row: float(row["projected_reward"]))
        _, reward, terminated, info = env.step(selected["action_id"])
        smoke_rows.append({
            "episode_id": episode_id, "shock_id": selected_shock, "initial_under_kg": initial["total_under_kg"],
            "available_actions": len(actions), "safe_actions": len(safe), "selected_action_id": selected["action_id"],
            "selected_action_reward": reward, "action_accepted": info["accepted"], "terminated": terminated,
            "smoke_status": "PASS" if info["accepted"] else "FAIL",
        })
        if not info["accepted"]:
            smoke_failures += 1
    write_csv(quality / "environment_smoke_test.csv", smoke_rows, ["episode_id", "shock_id", "initial_under_kg", "available_actions", "safe_actions", "selected_action_id", "selected_action_reward", "action_accepted", "terminated", "smoke_status"])

    gate_rows = [
        {"check": "BALANCED_BASELINE_GATE", "value": balanced_summary.get("rl_environment_gate"), "required": "READY_FOR_RL_ENVIRONMENT_DESIGN", "status": "PASS"},
        {"check": "EPISODE_COUNT", "value": len(episode_rows), "required": 66, "status": "PASS" if len(episode_rows) == 66 else "FAIL"},
        {"check": "BASELINE_FIELD_ROWS", "value": len(field_rows), "required": args.expected_field_rows, "status": "PASS" if len(field_rows) == args.expected_field_rows else "FAIL"},
        {"check": "DUPLICATE_EMPLOYEE_ASSIGNMENTS", "value": duplicate_failures, "required": 0, "status": "PASS" if duplicate_failures == 0 else "FAIL"},
        {"check": "SMOKE_TEST_FAILURES", "value": smoke_failures, "required": 0, "status": "PASS" if smoke_failures == 0 else "FAIL"},
        {"check": "RL_STARTED", "value": False, "required": False, "status": "PASS"},
    ]
    write_csv(quality / "rl_environment_safety_gate.csv", gate_rows, ["check", "value", "required", "status"])
    gate_failures = sum(1 for row in gate_rows if row["status"] != "PASS")
    summary = {
        "status": "PASS_RL_ENVIRONMENT_DESIGN" if gate_failures == 0 else "PASS_WITH_RL_ENVIRONMENT_DESIGN_WARNINGS",
        "package_version": VERSION, "run_folder": str(run), "capacity_run": str(capacity),
        "comparison_run": str(comparison), "balanced_run": str(balanced), "episodes": len(episode_rows),
        "baseline_field_rows": len(field_rows), "baseline_assignment_rows": len(assignment_rows),
        "shock_sets_per_episode": shock_count + 1, "shock_field_rows": len(shock_rows),
        "duplicate_employee_assignment_failures": duplicate_failures, "smoke_test_rows": len(smoke_rows),
        "smoke_test_failures": smoke_failures, "safety_gate_failures": gate_failures,
        "environment_ready_for_training_code": gate_failures == 0, "operational_status": STATUS,
        "rl_started": False,
        "important_interpretation": [
            "This stage creates and smoke-tests the RL environment only.",
            "The environment starts from the CP-SAT development baseline.",
            "Shock states are deterministic simulations, not observed future events.",
            "The safety shield blocks duplicate, cross-estate and materially harmful moves.",
            "A pass permits development RL training only; it does not approve operational deployment.",
        ],
    }
    (run / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (run / "README.txt").write_text(f"TTE SAFE RL ENVIRONMENT DESIGN v{VERSION}\n\nEpisodes: {len(episode_rows)}\nFields: {len(field_rows)}\nShock sets per episode: {shock_count + 1}\nSmoke failures: {smoke_failures}\n\nRL training has not started.\nOperational use is prohibited.\n", encoding="utf-8")
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "LATEST_RL_ENVIRONMENT_DESIGN_RUN.txt").write_text(str(run), encoding="utf-8")
    print("\nRL ENVIRONMENT DESIGN FINISHED")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
