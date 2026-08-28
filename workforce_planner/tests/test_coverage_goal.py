from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.baseline import greedy_allocate
from allocator.data import WorkforceData
from allocator.goal import analyze_coverage_goal
from allocator.optimizer import optimize_allocate, optimizer_available


@unittest.skipUnless(optimizer_available(), "OR-Tools is not installed")
class CoverageGoalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = WorkforceData.load(ROOT / "data" / "workforce_profile.json")
        cls.scenario = cls.data.create_scenario(
            template_date="2026-06-15",
            planning_date="2026-06-16",
            attendance_rate=0.9,
            demand_multiplier=1.0,
            same_division_only=True,
            seed=42,
        )
        standard = greedy_allocate(cls.data, cls.scenario)
        cls.optimized = optimize_allocate(
            cls.data,
            cls.scenario,
            time_limit_seconds=5,
            warm_start_plan=standard,
        )

    def test_goal_already_met_needs_no_extra_workers(self):
        goal = analyze_coverage_goal(
            self.data,
            self.scenario,
            self.optimized,
            goal_coverage_pct=50,
            time_limit_seconds=3,
        )
        self.assertEqual(goal["status"], "goal_met")
        self.assertEqual(goal["minimum_additional_workers"], 0)
        self.assertEqual(goal["goal_plan"]["metrics"]["constraint_violations"], 0)

    def test_85_goal_returns_an_honest_feasibility_result(self):
        goal = analyze_coverage_goal(
            self.data,
            self.scenario,
            self.optimized,
            goal_coverage_pct=85,
            time_limit_seconds=5,
        )
        self.assertIn(
            goal["status"],
            {"goal_met", "more_attendance_needed", "cross_division_needed", "capacity_gap"},
        )
        self.assertEqual(goal["goal_coverage_pct"], 85.0)
        self.assertGreaterEqual(goal["current_shortfall_kg"], 0)
        if goal.get("goal_plan"):
            self.assertEqual(goal["goal_plan"]["metrics"]["constraint_violations"], 0)
        if goal["status"] in {"more_attendance_needed", "cross_division_needed"}:
            self.assertGreater(goal["minimum_additional_workers"], 0)
            self.assertGreaterEqual(goal["goal_plan"]["metrics"]["coverage_pct"], 84.9)


if __name__ == "__main__":
    unittest.main()
