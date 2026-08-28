from datetime import date
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from multi_estate.crop_adapter import CropForecastAdapter
from multi_estate.registry import EstateRegistry


def adapter() -> CropForecastAdapter:
    registry = EstateRegistry.load(
        ROOT / "config" / "estate_source_manifest.csv",
        ROOT / "config" / "estate_alias_mapping.csv",
    )
    embedded_outputs = ROOT.parents[1] / "outputs"
    workspace_outputs = ROOT.parents[1] / "ttel_crop_forecasting" / "outputs"
    outputs = embedded_outputs if (embedded_outputs / "portfolio_summary.csv").exists() else workspace_outputs
    return CropForecastAdapter(
        registry,
        outputs / "portfolio_summary.csv",
        outputs / "portfolio_forecasts.csv",
        outputs / "five_year_daily_projection.csv",
    )


def test_crop_adapter_resolves_alias_and_requires_four_horizons():
    snapshot = adapter().load("Great Western", as_of=date(2026, 6, 15))
    assert snapshot.estate == "GreatWestern"
    assert [row.horizon_weeks for row in snapshot.horizons] == [1, 2, 3, 4]
    assert snapshot.four_week_forecast_kg > 0


def test_crop_adapter_blocks_stale_operational_use():
    snapshot = adapter().load("Clarendon", as_of=date(2026, 7, 22))
    assert not snapshot.current_practice_operational
    assert any("ended before" in reason for reason in snapshot.blocking_reasons)


def test_best_practice_is_not_fabricated():
    snapshot = adapter().load("Somerset", as_of=date(2026, 6, 15))
    assert snapshot.best_practice_available is False
