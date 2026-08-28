from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.baseline import greedy_allocate
from allocator.data import WorkforceData
from allocator.hybrid import build_candidate_plans
from allocator.optimizer import optimize_allocate, optimizer_available


@unittest.skipUnless(optimizer_available(), "OR-Tools is not installed")
class OptimizerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = WorkforceData.load(ROOT / "data" / "workforce_profile.json")
        cls.scenario = cls.data.create_scenario(
            template_date="2026-06-15",
            attendance_rate=0.90,
            demand_multiplier=1.0,
            same_division_only=True,
            seed=42,
        )

    def test_optimizer_matches_or_beats_warm_start_without_violations(self):
        standard = greedy_allocate(self.data, self.scenario)
        optimized = optimize_allocate(
            self.data,
            self.scenario,
            time_limit_seconds=5,
            warm_start_plan=standard,
        )
        self.assertEqual(optimized["metrics"]["constraint_violations"], 0)
        self.assertGreaterEqual(
            optimized["metrics"]["coverage_pct"],
            standard["metrics"]["coverage_pct"],
        )
        self.assertLessEqual(optimized["metrics"]["coverage_pct"], 100.0)
        self.assertGreaterEqual(
            optimized["optimization"]["coverage_upper_bound_pct"] + 0.051,
            optimized["metrics"]["coverage_pct"],
        )

    def test_hybrid_selects_strongest_zero_violation_candidate(self):
        result = build_candidate_plans(
            self.data,
            self.scenario,
            model_path=None,
            include_rl=False,
            include_optimizer=True,
            optimizer_time_limit_seconds=5,
        )
        self.assertEqual(result["selected"]["metrics"]["constraint_violations"], 0)
        self.assertGreaterEqual(
            result["selected"]["metrics"]["coverage_pct"],
            result["plans"]["standard"]["metrics"]["coverage_pct"],
        )
        self.assertIn(result["selected_name"], {"standard", "optimizer"})

    def test_active_forecast_uses_native_thread_safety_mode(self):
        class ActiveForecast:
            def predict_many(self, pairs, planning_date):
                return {pair: 14.0 for pair in pairs}

            def status(self, planning_date=None):
                return {
                    "ready": True,
                    "eligible_for_planning_date": True if planning_date else None,
                    "method": "test forecast",
                    "state_as_of": "2026-06-15",
                    "planning_date": planning_date,
                    "approved": True,
                    "error": None,
                }

        data = WorkforceData.load(ROOT / "data" / "workforce_profile.json")
        data.forecaster = ActiveForecast()
        scenario = data.create_scenario(
            template_date="2026-06-15",
            planning_date="2026-07-14",
            attendance_rate=0.9,
            seed=42,
        )
        standard = greedy_allocate(data, scenario)
        optimized = optimize_allocate(data, scenario, time_limit_seconds=5, warm_start_plan=standard)
        self.assertEqual(optimized["optimization"]["search_workers"], 1)
        self.assertTrue(optimized["optimization"]["forecast_native_thread_safety_mode"])
        self.assertEqual(optimized["metrics"]["constraint_violations"], 0)


if __name__ == "__main__":
    unittest.main()
