from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.baseline import greedy_allocate
from allocator.data import WorkforceData
from allocator.optimizer import optimize_allocate, optimizer_available
from allocator.practical import build_practical_plan


@unittest.skipUnless(optimizer_available(), "OR-Tools is not installed")
class PracticalOperationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = WorkforceData.load(ROOT / "data" / "workforce_profile.json")
        planning_date = (
            date.fromisoformat(cls.data.metadata["date_max"]) + timedelta(days=1)
        ).isoformat()
        cls.scenario = cls.data.create_scenario(
            template_date=cls.data.metadata["default_template_date"],
            planning_date=planning_date,
            attendance_rate=0.9,
            demand_multiplier=1.0,
            same_division_only=True,
            seed=42,
        )
        warm = greedy_allocate(cls.data, cls.scenario)
        cls.current = optimize_allocate(
            cls.data,
            cls.scenario,
            time_limit_seconds=5,
            warm_start_plan=warm,
        )

    def test_zero_authorizations_use_only_current_home_division_workers(self):
        result = build_practical_plan(
            self.data,
            self.scenario,
            self.current,
            max_additional_workers=0,
            max_cross_division_assignments=0,
            time_limit_seconds=5,
        )
        baseline = set(self.scenario.employee_ids)
        assigned = {item["employee_id"] for item in result["plan"]["assignments"]}
        self.assertTrue(result["ready"])
        self.assertEqual(result["constraint_violations"], 0)
        self.assertEqual(result["additional_workers_used"], 0)
        self.assertEqual(result["transfers_used"], 0)
        self.assertTrue(assigned <= baseline)

    def test_supervisor_caps_are_hard_solver_constraints(self):
        result = build_practical_plan(
            self.data,
            self.scenario,
            self.current,
            max_additional_workers=5,
            max_cross_division_assignments=10,
            time_limit_seconds=5,
        )
        self.assertTrue(result["ready"])
        self.assertLessEqual(result["additional_workers_used"], 5)
        self.assertLessEqual(result["transfers_used"], 10)
        self.assertEqual(result["plan"]["metrics"]["constraint_violations"], 0)
        self.assertEqual(result["plan"]["optimization"]["max_additional_workers"], 5)
        self.assertEqual(result["plan"]["optimization"]["max_cross_division_assignments"], 10)

    def test_review_lists_reconcile_with_the_plan(self):
        result = build_practical_plan(
            self.data,
            self.scenario,
            self.current,
            max_additional_workers=10,
            max_cross_division_assignments=40,
            time_limit_seconds=5,
        )
        baseline = set(self.scenario.employee_ids)
        plan = result["plan"]
        additional = {
            item["employee_id"]
            for item in plan["assignments"]
            if item["employee_id"] not in baseline
        }
        transfers = [item for item in plan["assignments"] if item["cross_division"]]
        self.assertEqual(
            additional,
            {item["employee_id"] for item in result["additional_workers"]},
        )
        self.assertEqual(len(transfers), result["transfers_used"])
        self.assertEqual(len(additional), result["additional_workers_used"])


if __name__ == "__main__":
    unittest.main()
