from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.data import WorkforceData


def loaded_data() -> WorkforceData:
    data = WorkforceData.load(ROOT / "data" / "workforce_profile.json")
    data.configure_crop_forecaster(ROOT / "data" / "crop_forecast_clarendon.json")
    return data


def test_crop_forecast_status_and_stale_gate():
    data = loaded_data()
    status = data.crop_forecast_status("2026-06-20")
    assert status["ready"] is True
    assert status["eligible_for_planning_date"] is True
    stale = data.crop_forecast_status("2026-07-22")
    assert stale["eligible_for_planning_date"] is False


def test_forecast_scenario_scales_template_mix():
    data = loaded_data()
    lower = data.create_scenario(
        template_date="2026-06-15",
        planning_date="2026-06-20",
        demand_source="crop_forecast",
        forecast_risk="lower",
    )
    upper = data.create_scenario(
        template_date="2026-06-15",
        planning_date="2026-06-20",
        demand_source="crop_forecast",
        forecast_risk="upper",
    )
    assert set(lower.demand_kg) == set(upper.demand_kg)
    assert sum(upper.demand_kg.values()) > sum(lower.demand_kg.values())
    assert lower.crop_forecast["schedule_source"].startswith("historical template")
