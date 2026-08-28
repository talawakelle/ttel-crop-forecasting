from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


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


class TTEWorkforceRLEnvironment:
    """Development-only, safety-shielded employee reallocation environment."""

    def __init__(self, manifest_path: str | Path, max_moves: int = 20,
                 max_actions: int = 100, under_tolerance_kg: float = 0.5) -> None:
        self.manifest_path = Path(manifest_path).resolve()
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.max_moves = max(1, int(max_moves))
        self.max_actions = max(2, int(max_actions))
        self.under_tolerance_kg = max(0.0, float(under_tolerance_kg))

        self.episodes = read_csv(Path(self.manifest["episode_index_path"]))
        self.fields_source = read_csv(Path(self.manifest["baseline_field_state_path"]))
        self.assign_source = read_csv(Path(self.manifest["baseline_assignment_path"]))
        self.shocks_source = read_csv(Path(self.manifest["shock_field_state_path"]))
        self.candidate_path = Path(self.manifest["candidate_matrix_path"])

        self.episode_lookup = {row["episode_id"]: row for row in self.episodes}
        self.fields_by_episode: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
        self.assign_by_episode: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
        self.shocks: defaultdict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for row in self.fields_source:
            self.fields_by_episode[row["episode_id"]].append(row)
        for row in self.assign_source:
            self.assign_by_episode[row["episode_id"]].append(row)
        for row in self.shocks_source:
            self.shocks[(row["episode_id"], row["shock_id"])].append(row)

        self.candidate_cache: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
        self.episode_id = ""
        self.shock_id = ""
        self.estate = ""
        self.scenario = ""
        self.fields: dict[str, dict[str, Any]] = {}
        self.employee_field: dict[str, str] = {}
        self.employee_productivity: dict[str, float] = {}
        self.moves = 0
        self.terminated = False

    def episode_ids(self) -> list[str]:
        return sorted(self.episode_lookup)

    def shock_ids(self, episode_id: str) -> list[str]:
        return sorted({shock for ep, shock in self.shocks if ep == episode_id})

    def _load_candidates(self, estate: str) -> dict[tuple[str, str], dict[str, Any]]:
        estate_key = norm(estate)
        if estate_key in self.candidate_cache:
            return self.candidate_cache[estate_key]
        lookup: dict[tuple[str, str], dict[str, Any]] = {}
        with self.candidate_path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                if norm(row.get("estate")) != estate_key:
                    continue
                employee_id = clean(row.get("employee_id"))
                field_uid = clean(row.get("field_uid")) or f"{clean(row.get('division'))}::{clean(row.get('field'))}"
                candidate = {
                    "employee_id": employee_id,
                    "field_uid": field_uid,
                    "productivity": max(0.1, number(row.get("expected_productivity_kg"), 0.1)),
                    "scope": clean(row.get("candidate_scope")),
                    "cross_division": clean(row.get("cross_division")).upper(),
                }
                key = (employee_id, field_uid)
                if key not in lookup or candidate["productivity"] > lookup[key]["productivity"]:
                    lookup[key] = candidate
        self.candidate_cache[estate_key] = lookup
        return lookup

    @staticmethod
    def _objective(fields: dict[str, dict[str, Any]]) -> float:
        under = over = 0.0
        for row in fields.values():
            target = row["target"]
            capacity = row["capacity"]
            under += max(0.0, target - capacity)
            over += max(0.0, capacity - target)
        return 1000.0 * under + 10.0 * over

    def reset(self, episode_id: str, shock_id: str = "SHOCK_00_BASELINE") -> dict[str, Any]:
        if episode_id not in self.episode_lookup:
            raise KeyError(f"Unknown episode: {episode_id}")
        shock_rows = self.shocks.get((episode_id, shock_id))
        if not shock_rows:
            raise KeyError(f"Unknown shock {shock_id} for {episode_id}")
        episode = self.episode_lookup[episode_id]
        self.episode_id = episode_id
        self.shock_id = shock_id
        self.estate = episode["estate"]
        self.scenario = episode["scenario"]
        self.fields = {}
        self.employee_field = {}
        self.employee_productivity = {}
        self.moves = 0
        self.terminated = False
        shock_lookup = {row["field_uid"]: row for row in shock_rows}

        for row in self.fields_by_episode[episode_id]:
            uid = row["field_uid"]
            self.fields[uid] = {
                "division": row["division"],
                "field": row["field"],
                "target": number(shock_lookup[uid]["shocked_target_crop_kg"]),
                "capacity": 0.0,
                "employees": set(),
            }
        for row in self.assign_by_episode[episode_id]:
            employee = row["employee_id"]
            uid = row["field_uid"]
            prod = number(row["expected_productivity_kg"]) * number(shock_lookup[uid]["productivity_multiplier"], 1.0)
            self.employee_field[employee] = uid
            self.employee_productivity[employee] = prod
            self.fields[uid]["employees"].add(employee)
            self.fields[uid]["capacity"] += prod
        return self.state()

    def state(self) -> dict[str, Any]:
        target = sum(row["target"] for row in self.fields.values())
        capacity = sum(row["capacity"] for row in self.fields.values())
        under = sum(max(0.0, row["target"] - row["capacity"]) for row in self.fields.values())
        over = sum(max(0.0, row["capacity"] - row["target"]) for row in self.fields.values())
        return {
            "episode_id": self.episode_id,
            "shock_id": self.shock_id,
            "estate": self.estate,
            "scenario": self.scenario,
            "fields": len(self.fields),
            "assigned_employees": len(self.employee_field),
            "total_target_crop_kg": round(target, 4),
            "total_assigned_capacity_kg": round(capacity, 4),
            "total_under_kg": round(under, 4),
            "total_over_kg": round(over, 4),
            "moves": self.moves,
            "terminated": self.terminated,
        }

    def valid_actions(self) -> list[dict[str, Any]]:
        if self.terminated:
            return []
        current = self.state()
        current_under = current["total_under_kg"]
        current_over = current["total_over_kg"]
        before = self._objective(self.fields)
        candidates = self._load_candidates(self.estate)
        actions = [{
            "action_id": "NO_OP", "action_type": "NO_OP", "safe_action": "YES",
            "employee_id": "", "source_field_uid": "", "target_field_uid": "",
            "projected_reward": 0.0, "projected_under_change_kg": 0.0,
            "projected_over_change_kg": 0.0, "reason": "KEEP_BASELINE",
        }]
        for employee, source_uid in self.employee_field.items():
            source_prod = self.employee_productivity[employee]
            for target_uid in self.fields:
                if target_uid == source_uid:
                    continue
                candidate = candidates.get((employee, target_uid))
                if candidate is None:
                    continue
                projected = {uid: {**row, "capacity": row["capacity"]} for uid, row in self.fields.items()}
                projected[source_uid]["capacity"] -= source_prod
                projected[target_uid]["capacity"] += candidate["productivity"]
                after = self._objective(projected)
                under = sum(max(0.0, row["target"] - row["capacity"]) for row in projected.values())
                over = sum(max(0.0, row["capacity"] - row["target"]) for row in projected.values())
                under_change = under - current_under
                over_change = over - current_over
                move_penalty = 1.0 + (2.0 if candidate["cross_division"] == "YES" else 0.0)
                reward = before - after - move_penalty
                safe = under_change <= self.under_tolerance_kg and reward >= -1.0
                actions.append({
                    "action_id": f"MOVE::{employee}::{source_uid}::{target_uid}",
                    "action_type": "MOVE", "safe_action": "YES" if safe else "NO",
                    "employee_id": employee, "source_field_uid": source_uid,
                    "target_field_uid": target_uid, "projected_reward": round(reward, 6),
                    "projected_under_change_kg": round(under_change, 6),
                    "projected_over_change_kg": round(over_change, 6),
                    "reason": "SAFE" if safe else "BLOCKED_BY_SAFETY_SHIELD",
                })
        actions.sort(key=lambda row: (row["safe_action"] != "YES", -float(row["projected_reward"]), row["action_id"]))
        return actions[: self.max_actions]

    def step(self, action_id: str) -> tuple[dict[str, Any], float, bool, dict[str, Any]]:
        if self.terminated:
            raise RuntimeError("Episode terminated")
        action_lookup = {row["action_id"]: row for row in self.valid_actions()}
        if action_id not in action_lookup:
            raise KeyError(action_id)
        action = action_lookup[action_id]
        if action["safe_action"] != "YES":
            return self.state(), -1000.0, False, {"accepted": False, "reason": "SAFETY_SHIELD_REJECTED"}
        if action["action_type"] == "NO_OP":
            self.terminated = True
            return self.state(), 0.0, True, {"accepted": True, "reason": "NO_OP"}
        employee = action["employee_id"]
        source_uid = action["source_field_uid"]
        target_uid = action["target_field_uid"]
        candidate = self._load_candidates(self.estate)[(employee, target_uid)]
        source_prod = self.employee_productivity[employee]
        target_prod = candidate["productivity"]
        self.fields[source_uid]["employees"].remove(employee)
        self.fields[source_uid]["capacity"] -= source_prod
        self.fields[target_uid]["employees"].add(employee)
        self.fields[target_uid]["capacity"] += target_prod
        self.employee_field[employee] = target_uid
        self.employee_productivity[employee] = target_prod
        self.moves += 1
        self.terminated = self.moves >= self.max_moves
        return self.state(), float(action["projected_reward"]), self.terminated, {"accepted": True, "reason": "SAFE_MOVE_APPLIED"}
