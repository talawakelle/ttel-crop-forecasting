from __future__ import annotations

import csv
import json
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

from multi_estate.crop_adapter import CropForecastAdapter
from multi_estate.registry import EstateRegistry


registry = EstateRegistry.load(
    ROOT / "config" / "estate_source_manifest.csv",
    ROOT / "config" / "estate_alias_mapping.csv",
)
assert len(registry) == 33
assert registry.resolve("Great Western").estate == "GreatWestern"
assert registry.resolve("Oliphant").estate == "Oilphant"
try:
    registry.assert_estate_access("Clarendon", "Somerset")
except PermissionError:
    pass
else:
    raise AssertionError("Cross-estate access was not rejected")

embedded_outputs = ROOT.parents[1] / "outputs"
workspace_outputs = ROOT.parents[1] / "ttel_crop_forecasting" / "outputs"
outputs = embedded_outputs if (embedded_outputs / "portfolio_summary.csv").exists() else workspace_outputs
adapter = CropForecastAdapter(
    registry,
    outputs / "portfolio_summary.csv",
    outputs / "portfolio_forecasts.csv",
    outputs / "five_year_daily_projection.csv",
)
clarendon = adapter.load("Clarendon", as_of=date(2026, 7, 22))
assert len(clarendon.horizons) == 4
assert not clarendon.current_practice_operational
assert not clarendon.best_practice_available

audit_path = ROOT / "audit" / "estate_data_audit.csv"
with audit_path.open(newline="", encoding="utf-8-sig") as handle:
    audits = list(csv.DictReader(handle))
assert len(audits) == 33
assert len({(row["plantation_id"], row["estate_id"]) for row in audits}) == 33
assert not any(str(row["identity_mismatch"]).lower() == "true" for row in audits)

result = {
    "status": "PASS",
    "estates": len(registry),
    "cross_estate_access_rejected": True,
    "crop_horizons_per_estate": 4,
    "stale_crop_demand_blocked": True,
    "best_practice_fabricated": False,
    "gpu_training_authorized": False,
    "rl_training_authorized": False,
}
(ROOT / "audit" / "v2_checkpoint_validation.json").write_text(
    json.dumps(result, indent=2), encoding="utf-8"
)
print(json.dumps(result, indent=2))
