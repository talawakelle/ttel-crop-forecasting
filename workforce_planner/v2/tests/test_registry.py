from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from multi_estate.contracts import PlannerSafetyPolicy
from multi_estate.registry import EstateRegistry


def registry() -> EstateRegistry:
    return EstateRegistry.load(
        ROOT / "config" / "estate_source_manifest.csv",
        ROOT / "config" / "estate_alias_mapping.csv",
    )


def test_registry_contains_33_unique_estates():
    value = registry()
    assert len(value) == 33
    assert len({record.key for record in value.records}) == 33


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("Great Western", "GreatWestern"),
        ("Wattegodde", "Wattegoda"),
        ("Oliphant", "Oilphant"),
        ("Glassugh", "Glassaugh"),
        ("Bambrakelly", "Bambarakelly"),
    ],
)
def test_aliases(alias, canonical):
    assert registry().resolve(alias).estate == canonical


def test_cross_estate_access_is_rejected():
    with pytest.raises(PermissionError):
        registry().assert_estate_access("Somerset", "Clarendon")


def test_safety_policy_rejects_weaker_limits():
    with pytest.raises(ValueError):
        PlannerSafetyPolicy(maximum_move_rate=0.20)
