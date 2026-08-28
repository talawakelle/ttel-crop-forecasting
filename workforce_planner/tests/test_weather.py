from __future__ import annotations

from pathlib import Path
import json
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.forecast import sha256_file  # noqa: E402
from allocator.weather import WEATHER_FEATURE_COLUMNS, WeatherHistory  # noqa: E402


class WeatherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.daily_path = ROOT / "data" / "weather_daily.csv.gz"
        cls.metadata_path = ROOT / "data" / "weather_metadata.json"
        cls.metadata = json.loads(cls.metadata_path.read_text(encoding="utf-8"))
        cls.history = WeatherHistory.load(cls.daily_path, cls.metadata_path)

    def test_weather_source_and_daily_fingerprint(self):
        self.assertEqual(
            self.metadata["source_sha256"],
            "df0b81bfbd5f085040a408286ab4a2993d824f0e877b590b4c587489c7b51e04",
        )
        self.assertEqual(self.metadata["daily_sha256"], sha256_file(self.daily_path))
        self.assertEqual(self.metadata["raw_rows_read"], 172_234)
        self.assertEqual(self.metadata["duplicate_timestamps_removed"], 1_561)
        self.assertEqual(self.metadata["clarendon_join"]["weather_covered_workdays"], 1_601)

    def test_features_are_strictly_past_and_have_expected_schema(self):
        result = self.history.features_for_date("2026-06-16")
        self.assertEqual(len(result.values), len(WEATHER_FEATURE_COLUMNS))
        self.assertLess(result.last_observation_date or "", "2026-06-16")
        self.assertTrue(result.morning_available)
        self.assertTrue(result.operationally_fresh)

    def test_stale_weather_is_not_operationally_fresh(self):
        result = self.history.features_for_date("2026-06-28")
        self.assertEqual(result.last_observation_date, "2026-06-25")
        self.assertEqual(result.age_days, 3)
        self.assertFalse(result.morning_available)
        self.assertFalse(result.operationally_fresh)

    def test_rainfall_counter_uses_daily_max_not_sum(self):
        result = self.history.features_for_date("2024-11-27")
        index = WEATHER_FEATURE_COLUMNS.index("rain_lag1_mm")
        self.assertAlmostEqual(result.values[index], 80.7, places=2)


if __name__ == "__main__":
    unittest.main()
