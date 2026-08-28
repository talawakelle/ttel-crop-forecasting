from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.baseline import greedy_allocate
from allocator.data import WorkforceData
from allocator.frontier import REFERENCE_BENCHMARK, build_coverage_frontier
from allocator.optimizer import optimize_allocate, optimizer_available


@unittest.skipUnless(optimizer_available(), "OR-Tools is not installed")
class CoverageFrontierTests(unittest.TestCase):
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
        cls.frontier = build_coverage_frontier(
            cls.data,
            cls.scenario,
            cls.current,
            time_limit_seconds=5,
        )

    def test_frontier_returns_four_safe_options(self):
        self.assertTrue(self.frontier["ready"])
        self.assertEqual(len(self.frontier["options"]), 4)
        self.assertTrue(all(
            option["constraint_violations"] == 0
            for option in self.frontier["options"]
        ))
        self.assertEqual(
            self.frontier["best_plan"]["metrics"]["constraint_violations"],
            0,
        )

    def test_frontier_never_reports_a_weaker_best_option(self):
        self.assertGreaterEqual(
            self.frontier["best_coverage_pct"],
            self.frontier["current_coverage_pct"],
        )

    def test_reference_benchmark_is_frozen(self):
        self.assertEqual(REFERENCE_BENCHMARK["strict_mean_coverage_pct"], 67.75)
        self.assertEqual(REFERENCE_BENCHMARK["open_divisions_mean_coverage_pct"], 71.50)
        self.assertEqual(REFERENCE_BENCHMARK["full_attendance_mean_coverage_pct"], 77.56)
        self.assertEqual(
            REFERENCE_BENCHMARK["full_attendance_open_divisions_mean_coverage_pct"],
            81.37,
        )


if __name__ == "__main__":
    unittest.main()
