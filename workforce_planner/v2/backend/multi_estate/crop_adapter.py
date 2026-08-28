from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .registry import EstateRegistry


@dataclass(frozen=True)
class WeeklyCropDemand:
    horizon_weeks: int
    week_starting: str
    week_ending: str
    forecast_kg: float
    lower_80_kg: float
    upper_80_kg: float
    method: str


@dataclass(frozen=True)
class EstateCropSnapshot:
    estate: str
    forecast_origin: str
    forecast_end: str
    crop_date_max: str
    training_status: str
    operational_status: str
    horizons: tuple[WeeklyCropDemand, ...]
    best_practice_available: bool
    current_practice_operational: bool
    blocking_reasons: tuple[str, ...]

    @property
    def four_week_forecast_kg(self) -> float:
        return sum(item.forecast_kg for item in self.horizons)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _parse_iso(value: str, field: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {field}: {value!r}") from exc


class CropForecastAdapter:
    """Validated, read-only bridge from crop outputs into workforce planning.

    The adapter deliberately exposes no best-practice demand until a real GAP
    scenario exists. It also blocks operational workforce use when the four-week
    forecast no longer covers the requested planning date.
    """

    def __init__(
        self,
        registry: EstateRegistry,
        summary_path: Path | str,
        forecasts_path: Path | str,
        projection_path: Path | str,
    ) -> None:
        self.registry = registry
        self.summary_path = Path(summary_path)
        self.forecasts_path = Path(forecasts_path)
        self.projection_path = Path(projection_path)

    def load(self, estate: str, as_of: date | None = None) -> EstateCropSnapshot:
        as_of = as_of or date.today()
        canonical = self.registry.resolve(estate).estate
        summaries = [row for row in _read_csv(self.summary_path) if row["estate"] == canonical]
        if len(summaries) != 1:
            raise ValueError(f"Expected one crop summary for {canonical}; found {len(summaries)}")
        summary = summaries[0]

        rows = [row for row in _read_csv(self.forecasts_path) if row["estate"] == canonical]
        rows.sort(key=lambda row: int(row["horizon_weeks"]))
        horizons = tuple(
            WeeklyCropDemand(
                horizon_weeks=int(row["horizon_weeks"]),
                week_starting=row["forecast_week_starting"],
                week_ending=row["forecast_week_ending"],
                forecast_kg=float(row["forecast_kg"]),
                lower_80_kg=float(row["lower_80_kg"]),
                upper_80_kg=float(row["upper_80_kg"]),
                method=row["selected_method"],
            )
            for row in rows
        )

        reasons: list[str] = []
        horizon_numbers = [item.horizon_weeks for item in horizons]
        if horizon_numbers != [1, 2, 3, 4]:
            reasons.append("Exactly four ordered weekly crop horizons are required")
        if _parse_iso(summary["forecast_end"], "forecast_end") < as_of:
            reasons.append(f"Crop forecast ended before {as_of.isoformat()}")
        if summary["operational_status"].upper().startswith("OUTDATED"):
            reasons.append("Crop portfolio marks the forecast as outdated")
        if any(item.lower_80_kg > item.forecast_kg or item.upper_80_kg < item.forecast_kg for item in horizons):
            reasons.append("A forecast falls outside its 80% interval")

        best_available = self._best_practice_available(canonical)
        return EstateCropSnapshot(
            estate=canonical,
            forecast_origin=summary["forecast_origin"],
            forecast_end=summary["forecast_end"],
            crop_date_max=summary["crop_date_max"],
            training_status=summary["training_status"],
            operational_status=summary["operational_status"],
            horizons=horizons,
            best_practice_available=best_available,
            current_practice_operational=not reasons,
            blocking_reasons=tuple(reasons),
        )

    def _best_practice_available(self, canonical: str) -> bool:
        if not self.projection_path.exists():
            return False
        for row in _read_csv(self.projection_path):
            if row["estate"] != canonical:
                continue
            value = str(row.get("best_practice_kg", "")).strip()
            if value:
                return True
        return False

