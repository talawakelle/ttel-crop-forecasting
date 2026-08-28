from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any
import json
import math


RISK_TO_KEY = {
    "lower": "lower_80_kg",
    "central": "forecast_kg",
    "upper": "upper_80_kg",
}


@dataclass(frozen=True)
class CropForecastPeriod:
    estate: str
    horizon: int
    origin_week_ending: str
    forecast_start: str
    forecast_end: str
    forecast_kg: float
    lower_80_kg: float
    upper_80_kg: float
    selected_method: str
    validation_wape: float

    def contains(self, planning_date: str) -> bool:
        return self.forecast_start <= planning_date <= self.forecast_end


class CropForecastProvider:
    """Validated estate-week forecast adapter for field-level planning.

    The source model predicts total estate crop for a week. It does not predict
    the exact field schedule. This adapter therefore preserves the supervisor's
    selected historical template-day field mix and scales that mix to the daily
    share of the estate-week forecast. The resulting demand is suitable for
    planning scenarios, but the schedule-source limitation is exposed in every
    response and never hidden.
    """

    def __init__(self, path: Path, workforce_data: Any):
        self.path = Path(path)
        self.data = workforce_data
        self.error: str | None = None
        self.payload: dict[str, Any] = {}
        self.periods: list[CropForecastPeriod] = []
        self.file_sha256: str | None = None
        self.weekday_shares = self._historical_weekday_shares()
        try:
            raw = self.path.read_bytes()
            self.file_sha256 = sha256(raw).hexdigest()
            self.payload = json.loads(raw.decode("utf-8"))
            self.periods = [CropForecastPeriod(**row) for row in self.payload.get("periods", [])]
            if not self.periods:
                raise ValueError("No forecast periods were found")
            self.periods.sort(key=lambda item: item.forecast_start)
        except Exception as exc:  # status endpoint must remain available
            self.error = f"{type(exc).__name__}: {exc}"

    def _historical_weekday_shares(self) -> dict[int, float]:
        week_totals: dict[tuple[int, int], float] = {}
        day_totals: dict[tuple[int, int, int], float] = {}
        for row in self.data.days:
            if row.get("incomplete"):
                continue
            try:
                day = date.fromisoformat(str(row["date"]))
            except (KeyError, ValueError):
                continue
            total = max(0.0, float(row.get("total_kg", 0.0)))
            iso = day.isocalendar()
            week_key = (iso.year, iso.week)
            week_totals[week_key] = week_totals.get(week_key, 0.0) + total
            key = (iso.year, iso.week, day.weekday())
            day_totals[key] = day_totals.get(key, 0.0) + total
        sums = {weekday: 0.0 for weekday in range(7)}
        counts = {weekday: 0 for weekday in range(7)}
        for (year, week, weekday), total in day_totals.items():
            weekly = week_totals.get((year, week), 0.0)
            if weekly <= 0.0:
                continue
            sums[weekday] += total / weekly
            counts[weekday] += 1
        shares = {
            weekday: (sums[weekday] / counts[weekday] if counts[weekday] else 1.0 / 7.0)
            for weekday in range(7)
        }
        normalizer = sum(shares.values()) or 1.0
        return {weekday: value / normalizer for weekday, value in shares.items()}

    def period_for(self, planning_date: str) -> CropForecastPeriod | None:
        return next((period for period in self.periods if period.contains(planning_date)), None)

    def status(self, planning_date: str | None = None) -> dict[str, Any]:
        period = self.period_for(planning_date) if planning_date and not self.error else None
        latest_end = self.periods[-1].forecast_end if self.periods else None
        today_text = date.today().isoformat()
        today_period = self.period_for(today_text) if not self.error else None
        return {
            "ready": not self.error and bool(self.periods),
            "eligible_for_planning_date": bool(period) if planning_date else None,
            "planning_date": planning_date,
            "estate": self.payload.get("estate"),
            "forecast_origin": self.payload.get("forecast_origin"),
            "forecast_start": self.periods[0].forecast_start if self.periods else None,
            "forecast_end": latest_end,
            "period_count": len(self.periods),
            "today": today_text,
            "eligible_today": bool(today_period),
            "stale_as_of_today": bool(latest_end and latest_end < today_text),
            "source_file": self.payload.get("source_file"),
            "source_sha256": self.file_sha256,
            "field_schedule_source": "supervisor-selected historical template day",
            "granularity": "estate-week total scaled to field-day template mix",
            "error": self.error,
            "active_period": period.__dict__ if period else None,
            "limitation": (
                "The crop model predicts the estate-week total. It does not independently predict which fields "
                "will be plucked on each day. Field demand therefore follows the selected template-day mix."
            ),
        }

    def build_field_demand(
        self,
        *,
        template_date: str,
        planning_date: str,
        risk: str = "central",
        division: str | None = None,
    ) -> tuple[dict[str, float], dict[str, Any]]:
        if self.error:
            raise ValueError(f"Crop forecast is unavailable: {self.error}")
        if risk not in RISK_TO_KEY:
            raise ValueError("Forecast risk must be lower, central or upper")
        period = self.period_for(planning_date)
        if period is None:
            available = (
                f"{self.periods[0].forecast_start} to {self.periods[-1].forecast_end}"
                if self.periods else "none"
            )
            raise ValueError(
                f"No crop forecast covers {planning_date}. Available forecast period: {available}. "
                "Import a refreshed crop forecast before using forecast demand."
            )
        source_day = self.data.day_by_date.get(template_date)
        if source_day is None:
            raise ValueError("Unknown demand-template date")
        source_all = {
            field_id: float(kilos)
            for field_id, kilos in source_day.get("demand_kg", {}).items()
            if field_id in self.data.field_by_id and float(kilos) > 0.0
        }
        if not source_all:
            raise ValueError("The selected template day has no usable active-field demand")
        selected = {
            field_id: kilos
            for field_id, kilos in source_all.items()
            if not division or self.data.field_by_id[field_id].division == division
        }
        if not selected:
            raise ValueError("The selected template day has no active fields for that division")
        period_value = float(getattr(period, RISK_TO_KEY[risk]))
        weekday_share = float(self.weekday_shares[date.fromisoformat(planning_date).weekday()])
        estate_daily_target = period_value * weekday_share
        division_share = sum(selected.values()) / max(1.0, sum(source_all.values()))
        daily_target = estate_daily_target * division_share
        scale = daily_target / max(1.0, sum(selected.values()))
        demand = {
            field_id: round(max(0.1, kilos * scale), 3)
            for field_id, kilos in selected.items()
        }
        metadata = {
            "demand_source": "estate_week_crop_forecast",
            "forecast_risk": risk,
            "weekly_forecast_kg": round(period_value, 2),
            "weekday_share": round(weekday_share, 6),
            "estate_daily_target_kg": round(estate_daily_target, 2),
            "division_share": round(division_share, 6),
            "daily_target_kg": round(sum(demand.values()), 2),
            "template_date": template_date,
            "planning_date": planning_date,
            "period": period.__dict__,
            "schedule_source": "historical template-day active fields and proportions",
            "source_sha256": self.file_sha256,
        }
        return demand, metadata

    def representative_wape(self) -> float:
        values = [max(0.0, float(period.validation_wape)) for period in self.periods]
        return sum(values) / len(values) if values else 0.15
