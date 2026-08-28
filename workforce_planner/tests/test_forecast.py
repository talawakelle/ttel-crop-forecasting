from __future__ import annotations

from pathlib import Path
import csv
import gzip
import json
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.data import WorkforceData  # noqa: E402
from allocator.forecast import (  # noqa: E402
    BASE_FEATURE_COLUMNS,
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    ProductivityForecaster,
    feature_row_from_state,
    read_json,
)


class FakeForecaster:
    def __init__(self):
        self.calls = 0

    def predict_many(self, pairs, planning_date):
        self.calls += 1
        return {pair: 20.0 for pair in pairs} if planning_date > "2026-06-15" else {}

    def status(self, planning_date=None):
        return {
            "ready": True,
            "eligible_for_planning_date": planning_date > "2026-06-15" if planning_date else None,
            "method": "test",
            "state_as_of": "2026-06-15",
            "planning_date": planning_date,
            "approved": True,
            "error": None,
        }


class ForecastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile_path = ROOT / "data" / "workforce_profile.json"
        cls.state_path = ROOT / "data" / "productivity_state.json.gz"
        cls.dataset_path = ROOT / "data" / "productivity_training.csv.gz"
        cls.metadata_path = ROOT / "data" / "productivity_dataset_metadata.json"

    def test_prepared_dataset_is_pseudonymous_and_time_split(self):
        metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["source_sha256"], "cadfaa5ab4e783acf89ecd2f194ddc55f2e7726f1f752ee9441518db79286be3")
        self.assertEqual(metadata["aggregated_employee_field_day_rows"], 278_561)
        self.assertEqual(sum(metadata["split_rows"].values()), 278_561)
        self.assertEqual(metadata["test_start"], "2026-04-01")
        self.assertEqual(metadata["feature_schema_version"], 2)
        self.assertIn("rain_7d_mm", metadata["feature_columns"])
        self.assertEqual(metadata["weather_source_sha256"], "df0b81bfbd5f085040a408286ab4a2993d824f0e877b590b4c587489c7b51e04")
        with gzip.open(self.dataset_path, "rt", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            row = next(reader)
            self.assertTrue(row["employee_id"].startswith("EMP-"))
            forbidden = {"employee_name", "employee_no", "epf", "nic", "gender", "alias_map"}
            self.assertTrue(set(reader.fieldnames or []).isdisjoint(forbidden))

    def test_future_feature_row_matches_schema(self):
        state = read_json(self.state_path)
        employee_id = next(iter(state["employees"]))
        field_id = next(iter(state["fields"]))
        row = feature_row_from_state(state, employee_id, field_id, "2026-07-14")
        self.assertEqual(len(row), len(FEATURE_COLUMNS))
        self.assertTrue(all(isinstance(row[index], str) for index in range(len(CATEGORICAL_FEATURES))))
        self.assertTrue(all(isinstance(value, float) for value in row[len(CATEGORICAL_FEATURES):]))
        self.assertGreater(len(FEATURE_COLUMNS), len(BASE_FEATURE_COLUMNS))

    def test_batch_forecast_is_cached_and_historical_date_falls_back(self):
        data = WorkforceData.load(self.profile_path)
        fake = FakeForecaster()
        data.forecaster = fake
        employee_ids = [item.id for item in data.employees[:2]]
        field_ids = [item.id for item in data.fields[:2]]
        future = data.prediction_map(employee_ids, field_ids, "2026-07-14")
        self.assertEqual(set(future.values()), {20.0})
        self.assertEqual(fake.calls, 1)
        data.prediction_map(employee_ids, field_ids, "2026-07-14")
        self.assertEqual(fake.calls, 1)
        historical = data.prediction_map(employee_ids, field_ids, "2026-06-01")
        self.assertTrue(all(0.5 <= value <= 45.0 for value in historical.values()))
        self.assertNotEqual(set(historical.values()), {20.0})

    def test_missing_forecast_files_leave_safe_fallback(self):
        forecaster = ProductivityForecaster(
            model_path=ROOT / "models" / "not-present.cbm",
            metadata_path=ROOT / "models" / "not-present.json",
            state_path=self.state_path,
            profile_source_sha256="cadfaa5ab4e783acf89ecd2f194ddc55f2e7726f1f752ee9441518db79286be3",
        )
        self.assertFalse(forecaster.ready)
        self.assertIn("Missing forecast file", forecaster.error or "")

    def test_scenario_separates_template_and_planning_dates(self):
        data = WorkforceData.load(self.profile_path)
        scenario = data.create_scenario(
            template_date="2026-06-15",
            planning_date="2026-07-14",
            seed=42,
        )
        self.assertEqual(scenario.template_date, "2026-06-15")
        self.assertEqual(scenario.planning_date, "2026-07-14")

    def test_packaged_model_exposes_confidence_and_horizon_gate(self):
        model = ROOT / "models" / "productivity_catboost.cbm"
        metrics = ROOT / "models" / "productivity_metrics.json"
        if not model.exists() or not metrics.exists():
            self.skipTest("Packaged forecast model not present")
        data = WorkforceData.load(self.profile_path)
        status = data.configure_forecaster(
            model_path=model,
            metadata_path=metrics,
            state_path=self.state_path,
        )
        self.assertTrue(status["ready"])
        employee_id = data.employees[0].id
        field_id = data.fields[0].id
        bundle = data.prediction_bundle_map([employee_id], [field_id], "2026-07-22")[(employee_id, field_id)]
        self.assertEqual(bundle["method"], "catboost")
        self.assertTrue(0.0 < bundle["confidence"] <= 1.0)
        self.assertGreater(bundle["uncertainty_kg"], 0.0)
        late = data.forecast_status("2026-12-31")
        self.assertFalse(late["eligible_for_planning_date"])
        self.assertGreater(late["forecast_horizon_days"], late["maximum_forecast_horizon_days"])


if __name__ == "__main__":
    unittest.main()
