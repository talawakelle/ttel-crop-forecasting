from __future__ import annotations

from pathlib import Path
import json
import random
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.baseline import greedy_allocate
from allocator.data import WorkforceData, validate_plan
from allocator.environment import MODEL_SCHEMA_VERSION, ORDER_MODES, WorkforceAllocationEnv


class AllocatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile_path = ROOT / "data" / "workforce_profile.json"
        cls.data = WorkforceData.load(cls.profile_path)

    def test_profile_excludes_direct_identifiers_and_protected_features(self):
        profile = json.loads(self.profile_path.read_text(encoding="utf-8"))
        keys = set()
        def collect(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    keys.add(key.lower())
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)
        collect(profile)
        forbidden = {"employee_name", "employee_no", "gender", "epf", "nic", "kanganie name"}
        self.assertTrue(keys.isdisjoint(forbidden))
        self.assertEqual(profile["metadata"]["source_rows_scanned"], 428_401)
        self.assertEqual(profile["metadata"]["source_rows_used"], 415_920)
        self.assertEqual(profile["metadata"]["employee_count"], 650)
        self.assertEqual(profile["metadata"]["field_count"], 36)
        self.assertEqual(profile["metadata"]["date_min"], "2021-04-01")
        self.assertEqual(profile["metadata"]["date_max"], "2026-06-15")
        self.assertTrue(all(item["id"].startswith("EMP-") for item in profile["employees"]))

    def test_greedy_plan_respects_hard_constraints(self):
        scenario = self.data.create_scenario(attendance_rate=0.88, demand_multiplier=1.1, seed=91)
        plan = greedy_allocate(self.data, scenario)
        self.assertEqual(plan["metrics"]["constraint_violations"], 0)
        employees = [item["employee_id"] for item in plan["assignments"]]
        self.assertEqual(len(employees), len(set(employees)))
        self.assertGreater(plan["metrics"]["coverage_pct"], 50.0)

    def test_environment_action_masks_prevent_invalid_assignments(self):
        scenario = self.data.create_scenario(attendance_rate=0.82, demand_multiplier=1.15, seed=12)
        env = WorkforceAllocationEnv(self.data, seed=12)
        _observation, _info = env.reset(options={"scenario": scenario})
        rng = random.Random(12)
        terminated = False
        while not terminated:
            valid = [index for index, allowed in enumerate(env.action_masks()) if allowed]
            action = rng.choice(valid)
            _observation, reward, terminated, truncated, _info = env.step(action)
            self.assertFalse(truncated)
            self.assertTrue(float("-inf") < reward < float("inf"))
        plan = env.result("random-masked", "test")
        self.assertEqual(plan["metrics"]["constraint_violations"], 0)

    def test_lookahead_observation_and_order_modes(self):
        scenario = self.data.create_scenario(attendance_rate=0.8, seed=2026)
        for mode in ORDER_MODES:
            env = WorkforceAllocationEnv(self.data, seed=2026)
            observation, info = env.reset(options={"scenario": scenario, "order_mode": mode})
            self.assertEqual(observation.shape, env.observation_space.shape)
            self.assertTrue(env.observation_space.contains(observation))
            self.assertEqual(set(env.employee_order), set(scenario.employee_ids))
            self.assertEqual(info["model_schema_version"], MODEL_SCHEMA_VERSION)

    def test_same_division_mode_blocks_transfers(self):
        scenario = self.data.create_scenario(same_division_only=True, seed=44)
        plan = greedy_allocate(self.data, scenario)
        self.assertEqual(plan["metrics"]["cross_division_assignments"], 0)

    def test_validator_rejects_unavailable_and_cross_division_assignments(self):
        scenario = self.data.create_scenario(same_division_only=True, seed=44)
        employee_id = scenario.employee_ids[0]
        employee = self.data.employee_by_id[employee_id]
        foreign_field = next(
            field for field in self.data.fields
            if field.division != employee.home_division and field.id in scenario.demand_kg
        )
        violations = validate_plan(scenario, [{
            "employee_id": employee_id,
            "field_id": foreign_field.id,
            "home_division": employee.home_division,
            "division": foreign_field.division,
        }, {
            "employee_id": "EMP-NOT-AVAILABLE",
            "field_id": foreign_field.id,
            "home_division": foreign_field.division,
            "division": foreign_field.division,
        }])
        self.assertTrue(any("Cross-division" in item for item in violations))
        self.assertTrue(any("Unavailable employee" in item for item in violations))


if __name__ == "__main__":
    unittest.main()
