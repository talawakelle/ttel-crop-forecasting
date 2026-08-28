from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
import json
import math
import random


@dataclass(frozen=True)
class FieldProfile:
    id: str
    division: str
    field_code: str
    median_active_day_demand_kg: float
    active_days: int
    median_worker_kg: float


@dataclass(frozen=True)
class EmployeeProfile:
    id: str
    home_division: str
    overall_median_kg: float
    days_observed: int
    field_productivity: dict[str, dict[str, float]]
    division_productivity: dict[str, dict[str, float]]


@dataclass
class Scenario:
    template_date: str
    planning_date: str
    employee_ids: list[str]
    demand_kg: dict[str, float]
    capacity: dict[str, int]
    attendance_rate: float
    demand_multiplier: float
    same_division_only: bool
    seed: int
    division: str | None = None
    demand_source: str = "historical_template"
    forecast_risk: str = "central"
    crop_forecast: dict[str, Any] | None = None


class WorkforceData:
    def __init__(self, profile: dict[str, Any]):
        self.metadata = profile["metadata"]
        self.fields = [FieldProfile(**item) for item in profile["fields"]]
        self.employees = [EmployeeProfile(**item) for item in profile["employees"]]
        self.days = profile["days"]
        self.field_by_id = {item.id: item for item in self.fields}
        self.employee_by_id = {item.id: item for item in self.employees}
        self.day_by_date = {item["date"]: item for item in self.days}
        self.complete_dates = [item["date"] for item in self.days if not item.get("incomplete")]
        self.forecaster: Any = None
        self.crop_forecaster: Any = None
        self._prediction_cache: dict[tuple[str, str, str], float] = {}
        self._confidence_cache: dict[tuple[str, str, str], float] = {}
        self._uncertainty_cache: dict[tuple[str, str, str], float] = {}
        self._method_cache: dict[tuple[str, str, str], str] = {}

    @classmethod
    def load(cls, path: Path | str) -> "WorkforceData":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def configure_forecaster(
        self,
        *,
        model_path: Path | str,
        metadata_path: Path | str,
        state_path: Path | str,
        weather_model_path: Path | str | None = None,
        weather_daily_path: Path | str | None = None,
        weather_metadata_path: Path | str | None = None,
    ) -> dict[str, Any]:
        from .forecast import ProductivityForecaster

        self.forecaster = ProductivityForecaster(
            model_path=Path(model_path),
            metadata_path=Path(metadata_path),
            state_path=Path(state_path),
            profile_source_sha256=self.metadata.get("source_sha256"),
            weather_model_path=Path(weather_model_path) if weather_model_path else None,
            weather_daily_path=Path(weather_daily_path) if weather_daily_path else None,
            weather_metadata_path=Path(weather_metadata_path) if weather_metadata_path else None,
        )
        self._prediction_cache.clear()
        self._confidence_cache.clear()
        self._uncertainty_cache.clear()
        self._method_cache.clear()
        return self.forecaster.status()

    def configure_crop_forecaster(self, path: Path | str) -> dict[str, Any]:
        from .crop_forecast import CropForecastProvider

        self.crop_forecaster = CropForecastProvider(Path(path), self)
        return self.crop_forecaster.status()

    def crop_forecast_status(self, planning_date: str | None = None) -> dict[str, Any]:
        if self.crop_forecaster is None:
            return {
                "ready": False,
                "eligible_for_planning_date": False if planning_date else None,
                "planning_date": planning_date,
                "error": "Estate crop forecast is not configured",
            }
        return self.crop_forecaster.status(planning_date)

    def forecast_status(self, planning_date: str | None = None) -> dict[str, Any]:
        if self.forecaster is None:
            return {
                "ready": False,
                "eligible_for_planning_date": False if planning_date else None,
                "method": "historical median fallback",
                "state_as_of": self.metadata.get("date_max"),
                "planning_date": planning_date,
                "approved": False,
                "error": "GPU productivity forecast is not configured",
            }
        return self.forecaster.status(planning_date)

    def _median_predict_kg(self, employee_id: str, field_id: str) -> float:
        employee = self.employee_by_id[employee_id]
        field = self.field_by_id[field_id]
        overall = max(1.0, employee.overall_median_kg)
        division_stats = employee.division_productivity.get(field.division)
        if division_stats:
            n = float(division_stats["days"])
            division_value = (n * float(division_stats["median_kg"]) + 3.0 * overall) / (n + 3.0)
        else:
            division_value = overall * (0.82 if employee.home_division != field.division else 1.0)
        field_stats = employee.field_productivity.get(field_id)
        if field_stats:
            n = float(field_stats["days"])
            estimate = (n * float(field_stats["median_kg"]) + 4.0 * division_value) / (n + 4.0)
        else:
            estimate = division_value * 0.92
        if employee.home_division != field.division:
            estimate *= 0.88
        return round(max(0.5, min(45.0, estimate)), 3)

    def _median_confidence(self, employee_id: str, field_id: str) -> float:
        employee = self.employee_by_id[employee_id]
        pair_days = float(employee.field_productivity.get(field_id, {}).get("days", 0.0))
        division = self.field_by_id[field_id].division
        division_days = float(employee.division_productivity.get(division, {}).get("days", 0.0))
        support = 0.25 + 0.20 * (1.0 - math.exp(-pair_days / 12.0))
        support += 0.10 * (1.0 - math.exp(-division_days / 40.0))
        return round(max(0.20, min(0.60, support)), 4)

    def prediction_bundle_map(
        self,
        employee_ids: list[str],
        field_ids: list[str],
        planning_date: str | None = None,
    ) -> dict[tuple[str, str], dict[str, float | str]]:
        planning_date = planning_date or date.today().isoformat()
        pairs = [(employee_id, field_id) for employee_id in employee_ids for field_id in field_ids]
        missing = [
            pair for pair in pairs
            if (pair[0], pair[1], planning_date) not in self._prediction_cache
        ]
        learned_details: dict[tuple[str, str], dict[str, float]] = {}
        if missing and self.forecaster is not None:
            if hasattr(self.forecaster, "prediction_details_many"):
                learned_details = self.forecaster.prediction_details_many(missing, planning_date)
            else:
                learned = self.forecaster.predict_many(missing, planning_date)
                learned_details = {
                    pair: {"expected_kg": value, "confidence": 0.50, "uncertainty_kg": 5.0}
                    for pair, value in learned.items()
                }
        for employee_id, field_id in missing:
            key = (employee_id, field_id, planning_date)
            details = learned_details.get((employee_id, field_id))
            if details:
                expected = float(details["expected_kg"])
                confidence = float(details.get("confidence", 0.50))
                uncertainty = float(details.get("uncertainty_kg", 5.0))
            else:
                expected = self._median_predict_kg(employee_id, field_id)
                confidence = self._median_confidence(employee_id, field_id)
                uncertainty = 6.0 * (1.15 - confidence)
            self._prediction_cache[key] = round(max(0.5, min(45.0, expected)), 3)
            self._confidence_cache[key] = round(max(0.0, min(1.0, confidence)), 4)
            self._uncertainty_cache[key] = round(max(0.5, uncertainty), 3)
            self._method_cache[key] = "catboost" if details else "historical_median"
        result: dict[tuple[str, str], dict[str, float | str]] = {}
        for employee_id, field_id in pairs:
            key = (employee_id, field_id, planning_date)
            expected = self._prediction_cache[key]
            confidence = self._confidence_cache[key]
            uncertainty = self._uncertainty_cache[key]
            result[(employee_id, field_id)] = {
                "expected_kg": expected,
                "confidence": confidence,
                "uncertainty_kg": uncertainty,
                "conservative_kg": round(max(0.5, expected - 0.50 * uncertainty), 3),
                "method": self._method_cache[key],
            }
        return result

    def prediction_map(
        self,
        employee_ids: list[str],
        field_ids: list[str],
        planning_date: str | None = None,
    ) -> dict[tuple[str, str], float]:
        bundles = self.prediction_bundle_map(employee_ids, field_ids, planning_date)
        return {pair: float(details["expected_kg"]) for pair, details in bundles.items()}

    def prediction_confidence_map(
        self,
        employee_ids: list[str],
        field_ids: list[str],
        planning_date: str | None = None,
    ) -> dict[tuple[str, str], float]:
        bundles = self.prediction_bundle_map(employee_ids, field_ids, planning_date)
        return {pair: float(details["confidence"]) for pair, details in bundles.items()}

    def predict_kg(
        self,
        employee_id: str,
        field_id: str,
        planning_date: str | None = None,
    ) -> float:
        return self.prediction_map([employee_id], [field_id], planning_date)[(employee_id, field_id)]

    def create_scenario(
        self,
        template_date: str | None = None,
        planning_date: str | None = None,
        attendance_rate: float = 0.9,
        demand_multiplier: float = 1.0,
        same_division_only: bool = True,
        division: str | None = None,
        seed: int = 42,
        demand_source: str = "historical_template",
        forecast_risk: str = "central",
    ) -> Scenario:
        template_date = template_date or self.metadata["default_template_date"]
        if template_date not in self.day_by_date:
            raise ValueError("Unknown demand-template date")
        planning_date = planning_date or date.today().isoformat()
        try:
            date.fromisoformat(planning_date)
        except ValueError as exc:
            raise ValueError("Planning date must use YYYY-MM-DD format") from exc
        attendance_rate = max(0.25, min(1.0, float(attendance_rate)))
        demand_multiplier = max(0.5, min(1.75, float(demand_multiplier)))
        source_day = self.day_by_date[template_date]
        crop_metadata: dict[str, Any] | None = None
        if demand_source == "crop_forecast":
            if self.crop_forecaster is None:
                raise ValueError("Estate crop forecast is not configured")
            demand, crop_metadata = self.crop_forecaster.build_field_demand(
                template_date=template_date,
                planning_date=planning_date,
                risk=forecast_risk,
                division=division,
            )
            demand = {
                field_id: round(float(kilos) * demand_multiplier, 3)
                for field_id, kilos in demand.items()
            }
        elif demand_source == "historical_template":
            demand = {
                field_id: round(float(kilos) * demand_multiplier, 3)
                for field_id, kilos in source_day["demand_kg"].items()
                if field_id in self.field_by_id
                and (not division or self.field_by_id[field_id].division == division)
                and float(kilos) > 0
            }
        else:
            raise ValueError("Demand source must be historical_template or crop_forecast")
        candidates = [
            employee_id for employee_id in source_day["available_employee_ids"]
            if employee_id in self.employee_by_id
            and (not division or self.employee_by_id[employee_id].home_division == division)
        ]
        rng = random.Random(seed)
        rng.shuffle(candidates)
        keep = min(len(candidates), max(1, round(len(candidates) * attendance_rate)))
        employee_ids = sorted(candidates[:keep])
        capacity = {}
        for field_id, target in demand.items():
            typical = max(1.0, self.field_by_id[field_id].median_worker_kg)
            capacity[field_id] = max(1, math.ceil(target / typical))
        return Scenario(
            template_date=template_date,
            planning_date=planning_date,
            employee_ids=employee_ids,
            demand_kg=demand,
            capacity=capacity,
            attendance_rate=attendance_rate,
            demand_multiplier=demand_multiplier,
            same_division_only=bool(same_division_only),
            seed=int(seed),
            division=division,
            demand_source=demand_source,
            forecast_risk=forecast_risk,
            crop_forecast=crop_metadata,
        )

    def public_summary(self) -> dict[str, Any]:
        divisions = sorted({item.division for item in self.fields})
        return {
            **self.metadata,
            "dates": [
                {
                    "date": item["date"],
                    "total_kg": item["total_kg"],
                    "employee_count": item["employee_count"],
                    "field_count": len(item["demand_kg"]),
                    "incomplete": bool(item.get("incomplete")),
                }
                for item in self.days
            ],
            "divisions": divisions,
            "crop_forecast": self.crop_forecast_status(),
        }


def validate_plan(scenario: Scenario, assignments: list[dict[str, Any]]) -> list[str]:
    violations = []
    employees = [item["employee_id"] for item in assignments if item.get("field_id")]
    duplicate_employees = sorted({employee for employee in employees if employees.count(employee) > 1})
    if duplicate_employees:
        violations.append(f"Employees assigned more than once: {', '.join(duplicate_employees[:5])}")
    counts: dict[str, int] = {}
    for item in assignments:
        employee_id = item.get("employee_id")
        field_id = item.get("field_id")
        if not field_id:
            continue
        if employee_id not in scenario.employee_ids:
            violations.append(f"Unavailable employee assigned: {employee_id}")
        counts[field_id] = counts.get(field_id, 0) + 1
        if field_id not in scenario.demand_kg:
            violations.append(f"Assignment to inactive field: {field_id}")
        if (
            scenario.same_division_only
            and item.get("home_division") != item.get("division")
        ):
            violations.append(f"Cross-division assignment blocked: {employee_id} to {field_id}")
    for field_id, count in counts.items():
        if count > scenario.capacity.get(field_id, 0):
            violations.append(f"Field capacity exceeded: {field_id}")
    return violations


def build_plan(
    data: WorkforceData,
    scenario: Scenario,
    assignments: list[dict[str, Any]],
    policy: str,
    policy_status: str,
) -> dict[str, Any]:
    field_predictions = {field_id: 0.0 for field_id in scenario.demand_kg}
    field_counts = {field_id: 0 for field_id in scenario.demand_kg}
    transfer_count = 0
    normalized = []
    assigned_ids = set()
    for item in assignments:
        employee_id = item["employee_id"]
        field_id = item.get("field_id")
        if not field_id:
            continue
        employee = data.employee_by_id[employee_id]
        field = data.field_by_id[field_id]
        details = data.prediction_bundle_map(
            [employee_id], [field_id], scenario.planning_date
        )[(employee_id, field_id)]
        predicted = float(item.get("predicted_kg") or details["expected_kg"])
        forecast_confidence = float(item.get("forecast_confidence", details["confidence"]))
        uncertainty_kg = float(details["uncertainty_kg"])
        transfer = employee.home_division != field.division
        transfer_count += int(transfer)
        field_predictions[field_id] += predicted
        field_counts[field_id] += 1
        assigned_ids.add(employee_id)
        normalized.append({
            "employee_id": employee_id,
            "home_division": employee.home_division,
            "field_id": field_id,
            "division": field.division,
            "field_code": field.field_code,
            "predicted_kg": round(predicted, 2),
            "cross_division": transfer,
            "forecast_confidence": round(forecast_confidence, 3),
            "forecast_uncertainty_kg": round(uncertainty_kg, 2),
            "confidence": (
                "high" if forecast_confidence >= 0.70
                else "medium" if forecast_confidence >= 0.40
                else "low"
            ),
        })
    field_rows = []
    fulfilled_total = 0.0
    target_total = sum(scenario.demand_kg.values())
    for field_id, target in scenario.demand_kg.items():
        predicted = field_predictions[field_id]
        fulfilled = min(target, predicted)
        fulfilled_total += fulfilled
        field = data.field_by_id[field_id]
        field_rows.append({
            "field_id": field_id,
            "division": field.division,
            "field_code": field.field_code,
            "target_kg": round(target, 2),
            "predicted_kg": round(predicted, 2),
            "assigned_workers": field_counts[field_id],
            "worker_capacity": scenario.capacity[field_id],
            "coverage_pct": round(100.0 * fulfilled / target, 1) if target else 100.0,
            "gap_kg": round(max(0.0, target - predicted), 2),
        })
    violations = validate_plan(scenario, normalized)
    return {
        "policy": policy,
        "policy_status": policy_status,
        "scenario": {
            "template_date": scenario.template_date,
            "planning_date": scenario.planning_date,
            "attendance_rate": scenario.attendance_rate,
            "demand_multiplier": scenario.demand_multiplier,
            "same_division_only": scenario.same_division_only,
            "seed": scenario.seed,
            "division": scenario.division,
            "demand_source": scenario.demand_source,
            "forecast_risk": scenario.forecast_risk,
            "crop_forecast": scenario.crop_forecast,
        },
        "metrics": {
            "target_kg": round(target_total, 2),
            "predicted_fulfilled_kg": round(fulfilled_total, 2),
            "coverage_pct": round(100.0 * fulfilled_total / target_total, 1) if target_total else 100.0,
            "available_workers": len(scenario.employee_ids),
            "assigned_workers": len(assigned_ids),
            "unassigned_workers": len(scenario.employee_ids) - len(assigned_ids),
            "cross_division_assignments": transfer_count,
            "constraint_violations": len(violations),
        },
        "fields": sorted(field_rows, key=lambda item: (item["division"], -item["target_kg"])),
        "assignments": sorted(normalized, key=lambda item: (item["division"], item["field_code"], item["employee_id"])),
        "violations": violations,
        "forecast": data.forecast_status(scenario.planning_date),
        "notice": "Simulation-calibrated decision support. Supervisor approval is required before operational use.",
    }
