from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Iterable
import gzip
import hashlib
import json
import math

from .weather import WEATHER_FEATURE_COLUMNS, WeatherHistory, weather_prefix_sha256


FEATURE_SCHEMA_VERSION = 2
PREDICTION_MIN_KG = 0.5
PREDICTION_MAX_KG = 45.0
MAX_FORECAST_HORIZON_DAYS = 120
CONFIDENCE_MIN = 0.15
CONFIDENCE_MAX = 0.95

CATEGORICAL_FEATURES = (
    "employee_id",
    "field_id",
    "home_division",
    "field_division",
)

BASE_NUMERIC_FEATURES = (
    "month",
    "day_of_week",
    "day_of_year_sin",
    "day_of_year_cos",
    "years_since_start",
    "cross_division",
    "employee_count_log",
    "employee_mean_kg",
    "employee_ewma_kg",
    "pair_count_log",
    "pair_mean_kg",
    "pair_ewma_kg",
    "division_count_log",
    "division_mean_kg",
    "division_ewma_kg",
    "field_count_log",
    "field_mean_kg",
    "field_ewma_kg",
    "days_since_employee",
    "days_since_pair",
)

BASE_FEATURE_COLUMNS = (*CATEGORICAL_FEATURES, *BASE_NUMERIC_FEATURES)
NUMERIC_FEATURES = (*BASE_NUMERIC_FEATURES, *WEATHER_FEATURE_COLUMNS)
FEATURE_COLUMNS = (*BASE_FEATURE_COLUMNS, *WEATHER_FEATURE_COLUMNS)
CATEGORICAL_INDICES = tuple(FEATURE_COLUMNS.index(name) for name in CATEGORICAL_FEATURES)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _number(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def _stat_values(stat: dict[str, Any] | None, default_mean: float) -> tuple[float, float, float, str | None]:
    stat = stat or {}
    count = max(0.0, _number(stat.get("count"), 0.0))
    mean = _number(stat.get("mean_kg"), default_mean)
    ewma = _number(stat.get("ewma_kg"), mean)
    return count, mean, ewma, stat.get("last_date")


def _days_since(last_value: str | None, current: date, default: float = 365.0) -> float:
    previous = _safe_date(last_value)
    if previous is None:
        return default
    return max(0.0, min(730.0, float((current - previous).days)))


def feature_row_from_state(
    state: dict[str, Any],
    employee_id: str,
    field_id: str,
    planning_date: str,
    weather_history: WeatherHistory | None = None,
) -> list[Any]:
    """Create one future-only feature row from a privacy-safe historical state."""

    current = date.fromisoformat(planning_date)
    metadata = state["metadata"]
    global_count, global_mean, global_ewma, _ = _stat_values(state.get("global"), 10.0)
    employee = state.get("employees", {}).get(employee_id, {})
    home_division = str(employee.get("home_division") or "UNK")
    field_division = str(field_id).split("/", 1)[0] if "/" in str(field_id) else "UNK"
    employee_count, employee_mean, employee_ewma, employee_last = _stat_values(
        employee,
        global_mean,
    )
    pair = state.get("employee_fields", {}).get(employee_id, {}).get(field_id)
    pair_count, pair_mean, pair_ewma, pair_last = _stat_values(pair, employee_mean)
    division = state.get("employee_divisions", {}).get(employee_id, {}).get(field_division)
    division_count, division_mean, division_ewma, _ = _stat_values(division, employee_mean)
    field_stat = state.get("fields", {}).get(field_id)
    field_count, field_mean, field_ewma, _ = _stat_values(field_stat, global_mean)

    start = _safe_date(metadata.get("date_min")) or current
    day_of_year = current.timetuple().tm_yday
    angle = 2.0 * math.pi * day_of_year / 365.25
    row = [
        str(employee_id),
        str(field_id),
        home_division,
        field_division,
        float(current.month),
        float(current.weekday()),
        math.sin(angle),
        math.cos(angle),
        max(0.0, (current - start).days / 365.25),
        float(home_division != field_division),
        math.log1p(employee_count),
        employee_mean,
        employee_ewma,
        math.log1p(pair_count),
        pair_mean,
        pair_ewma,
        math.log1p(division_count),
        division_mean,
        division_ewma,
        math.log1p(field_count),
        field_mean,
        field_ewma,
        _days_since(employee_last, current),
        _days_since(pair_last, current),
    ]
    if weather_history is None:
        row.extend((
            0.0, 365.0, 0.0, 0.0, 0.0, 0.0, 0.0, 18.5, 6.0, 85.0, 2.0,
            0.0, 18.5, 85.0, 0.0, 2.0,
        ))
    else:
        row.extend(weather_history.features_for_date(current).values)
    return row


class ProductivityForecaster:
    """Base and optional weather CatBoost forecasts with strict safety gates."""

    def __init__(
        self,
        *,
        model_path: Path,
        metadata_path: Path,
        state_path: Path,
        profile_source_sha256: str | None,
        weather_model_path: Path | None = None,
        weather_daily_path: Path | None = None,
        weather_metadata_path: Path | None = None,
    ):
        self.model_path = Path(model_path)
        self.weather_model_path = Path(weather_model_path) if weather_model_path else self.model_path.with_name(
            "productivity_weather_catboost.cbm"
        )
        self.metadata_path = Path(metadata_path)
        self.state_path = Path(state_path)
        data_dir = self.state_path.parent
        self.weather_daily_path = Path(weather_daily_path) if weather_daily_path else data_dir / "weather_daily.csv.gz"
        self.weather_metadata_path = (
            Path(weather_metadata_path) if weather_metadata_path else data_dir / "weather_metadata.json"
        )
        self.profile_source_sha256 = profile_source_sha256
        self.metadata: dict[str, Any] | None = None
        self.state: dict[str, Any] | None = None
        self.base_model: Any = None
        self.weather_model: Any = None
        self.weather_history: WeatherHistory | None = None
        self.error: str | None = None
        self.base_error: str | None = None
        self.weather_error: str | None = None
        self._load()

    def _fail(self, message: str) -> None:
        self.error = message
        self.base_model = None
        self.weather_model = None

    @staticmethod
    def _load_model(path: Path):
        from catboost import CatBoostRegressor

        model = CatBoostRegressor()
        model.load_model(str(path))
        return model

    def _load(self) -> None:
        if self.state_path.exists():
            try:
                self.state = read_json(self.state_path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                self._fail(f"Forecast state cannot be read: {type(exc).__name__}: {exc}")
                return
        missing = [path.name for path in (self.metadata_path, self.state_path) if not path.exists()]
        if missing:
            self._fail(f"Missing forecast file(s): {', '.join(missing)}")
            return
        try:
            self.metadata = read_json(self.metadata_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._fail(f"Forecast metadata cannot be read: {type(exc).__name__}: {exc}")
            return

        if self.metadata.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
            self._fail("Forecast feature schema version does not match this application")
            return
        if list(self.metadata.get("feature_columns") or []) != list(FEATURE_COLUMNS):
            self._fail("Forecast feature columns do not match this application")
            return
        expected = self.profile_source_sha256
        if not expected or self.metadata.get("profile_source_sha256") != expected:
            self._fail("Forecast profile fingerprint does not match")
            return
        if self.state.get("metadata", {}).get("source_sha256") != expected:
            self._fail("Forecast state fingerprint does not match")
            return
        expected_state_hash = self.metadata.get("state_sha256")
        if expected_state_hash and sha256_file(self.state_path) != expected_state_hash:
            self._fail("Forecast state file hash does not match its training report")
            return
        base_approved = bool(self.metadata.get("base_approved", self.metadata.get("approved")))
        weather_approved = bool(self.metadata.get("weather_approved"))
        if base_approved:
            try:
                if not self.model_path.exists():
                    raise FileNotFoundError(self.model_path.name)
                expected_base_hash = self.metadata.get("base_model_sha256") or self.metadata.get("model_sha256")
                if expected_base_hash and sha256_file(self.model_path) != expected_base_hash:
                    raise ValueError("Base model hash does not match its training report")
                self.base_model = self._load_model(self.model_path)
            except (ImportError, OSError, RuntimeError, ValueError) as exc:
                self.base_error = f"Base CatBoost forecast cannot be loaded: {type(exc).__name__}: {exc}"

        if weather_approved:
            try:
                if not self.weather_model_path.exists():
                    raise FileNotFoundError(self.weather_model_path.name)
                if not self.weather_daily_path.exists() or not self.weather_metadata_path.exists():
                    raise FileNotFoundError("Weather history file is missing")
                weather_meta = read_json(self.weather_metadata_path)
                expected_training_hash = self.metadata.get("weather_training_sha256")
                training_cutoff = self.metadata.get("weather_training_cutoff")
                if expected_training_hash and training_cutoff and weather_prefix_sha256(
                    self.weather_daily_path, training_cutoff
                ) != expected_training_hash:
                    raise ValueError("Weather history used for training has changed")
                if weather_meta.get("daily_sha256") != sha256_file(self.weather_daily_path):
                    raise ValueError("Weather metadata does not match the daily history")
                expected_weather_hash = self.metadata.get("weather_model_sha256")
                if expected_weather_hash and sha256_file(self.weather_model_path) != expected_weather_hash:
                    raise ValueError("Weather model hash does not match its training report")
                self.weather_history = WeatherHistory.load(
                    self.weather_daily_path,
                    self.weather_metadata_path,
                )
                self.weather_model = self._load_model(self.weather_model_path)
            except (ImportError, OSError, RuntimeError, ValueError) as exc:
                self.weather_history = None
                self.weather_model = None
                self.weather_error = (
                    f"Weather CatBoost forecast cannot be loaded: {type(exc).__name__}: {exc}"
                )
        if self.base_model is None and self.weather_model is None:
            details = "; ".join(value for value in (self.base_error, self.weather_error) if value)
            self._fail(details or "No productivity forecast passed its holdout safety gate")

    @property
    def ready(self) -> bool:
        return (
            (self.base_model is not None or self.weather_model is not None)
            and self.state is not None
            and self.error is None
        )

    @property
    def state_as_of(self) -> str | None:
        if not self.state:
            return None
        return self.state.get("metadata", {}).get("state_as_of")

    def forecast_horizon_days(self, planning_date: str | None) -> int | None:
        planned = _safe_date(planning_date)
        state_day = _safe_date(self.state_as_of)
        if not planned or not state_day:
            return None
        return int((planned - state_day).days)

    def eligible_for_date(self, planning_date: str | None) -> bool:
        if not self.ready:
            return False
        horizon = self.forecast_horizon_days(planning_date)
        if horizon is None or horizon <= 0 or horizon > MAX_FORECAST_HORIZON_DAYS:
            return False
        if self.base_model is not None:
            return True
        return bool(self._weather_active(planning_date))

    def _support_confidence(self, employee_id: str, field_id: str, planning_date: str) -> float:
        """Return a bounded reliability score from support, recency and holdout quality.

        This is not a probability of a kilogram value being correct. It is a planning
        confidence signal used by the RL policy to avoid over-trusting sparse pairs.
        """
        if not self.state:
            return CONFIDENCE_MIN
        current = _safe_date(planning_date)
        if current is None:
            return CONFIDENCE_MIN
        employee = self.state.get("employees", {}).get(employee_id, {})
        field_division = str(field_id).split("/", 1)[0] if "/" in str(field_id) else "UNK"
        pair = self.state.get("employee_fields", {}).get(employee_id, {}).get(field_id, {})
        division = self.state.get("employee_divisions", {}).get(employee_id, {}).get(field_division, {})
        field_stat = self.state.get("fields", {}).get(field_id, {})

        employee_count = max(0.0, _number(employee.get("count"), 0.0))
        pair_count = max(0.0, _number(pair.get("count"), 0.0))
        division_count = max(0.0, _number(division.get("count"), 0.0))
        field_count = max(0.0, _number(field_stat.get("count"), 0.0))
        employee_recency = math.exp(-_days_since(employee.get("last_date"), current) / 180.0)
        pair_recency = math.exp(-_days_since(pair.get("last_date"), current) / 120.0)
        support = (
            0.35 * (1.0 - math.exp(-pair_count / 12.0))
            + 0.20 * (1.0 - math.exp(-employee_count / 60.0))
            + 0.10 * (1.0 - math.exp(-division_count / 30.0))
            + 0.10 * (1.0 - math.exp(-field_count / 180.0))
            + 0.15 * pair_recency
            + 0.10 * employee_recency
        )
        test = (self.metadata or {}).get("base_test_metrics") or (self.metadata or {}).get("test_metrics", {})
        improvement = _number(test.get("mae_improvement_pct"), 0.0)
        validation_factor = max(0.55, min(0.90, 0.60 + improvement / 25.0))
        horizon = max(1, self.forecast_horizon_days(planning_date) or 1)
        horizon_factor = max(0.55, 1.0 - 0.45 * horizon / MAX_FORECAST_HORIZON_DAYS)
        value = support * validation_factor * horizon_factor
        return round(max(CONFIDENCE_MIN, min(CONFIDENCE_MAX, value)), 4)

    def confidence_many(
        self,
        pairs: Iterable[tuple[str, str]],
        planning_date: str,
    ) -> dict[tuple[str, str], float]:
        pairs = list(dict.fromkeys(pairs))
        if not pairs or not self.eligible_for_date(planning_date):
            return {}
        return {
            pair: self._support_confidence(pair[0], pair[1], planning_date)
            for pair in pairs
        }

    def _weather_features(self, planning_date: str | None):
        if not planning_date or self.weather_history is None:
            return None
        try:
            return self.weather_history.features_for_date(planning_date)
        except ValueError:
            return None

    def _weather_active(self, planning_date: str | None) -> bool:
        result = self._weather_features(planning_date)
        return bool(self.weather_model is not None and result and result.operationally_fresh)

    def predict_many(
        self,
        pairs: Iterable[tuple[str, str]],
        planning_date: str,
    ) -> dict[tuple[str, str], float]:
        pairs = list(dict.fromkeys(pairs))
        if not pairs or not self.eligible_for_date(planning_date):
            return {}
        assert self.state is not None
        use_weather = self._weather_active(planning_date)
        feature_columns = FEATURE_COLUMNS if use_weather else BASE_FEATURE_COLUMNS
        rows = []
        for employee_id, field_id in pairs:
            row = feature_row_from_state(
                self.state,
                employee_id,
                field_id,
                planning_date,
                self.weather_history if use_weather else None,
            )
            rows.append(row if use_weather else row[: len(BASE_FEATURE_COLUMNS)])
        model = self.weather_model if use_weather else self.base_model
        if model is None:
            return {}
        try:
            from catboost import Pool

            pool = Pool(
                rows,
                cat_features=list(CATEGORICAL_INDICES),
                feature_names=list(feature_columns),
            )
            # Single-threaded inference avoids native worker-pool contention with
            # the multi-threaded CP-SAT solver that runs immediately afterwards.
            # The allocation matrix is small, so this has negligible latency.
            values = model.predict(pool, task_type="CPU", thread_count=1)
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            self._fail(f"CatBoost inference failed: {type(exc).__name__}: {exc}")
            return {}
        return {
            pair: round(max(PREDICTION_MIN_KG, min(PREDICTION_MAX_KG, float(value))), 3)
            for pair, value in zip(pairs, values)
        }

    def prediction_details_many(
        self,
        pairs: Iterable[tuple[str, str]],
        planning_date: str,
    ) -> dict[tuple[str, str], dict[str, float]]:
        pairs = list(dict.fromkeys(pairs))
        predictions = self.predict_many(pairs, planning_date)
        confidence = self.confidence_many(pairs, planning_date)
        test = (self.metadata or {}).get("base_test_metrics") or (self.metadata or {}).get("test_metrics", {})
        holdout_mae = max(0.5, _number(test.get("model_mae_kg"), 5.0))
        details: dict[tuple[str, str], dict[str, float]] = {}
        for pair, expected in predictions.items():
            score = confidence.get(pair, CONFIDENCE_MIN)
            uncertainty = holdout_mae * (1.25 - 0.55 * score)
            details[pair] = {
                "expected_kg": expected,
                "confidence": round(score, 4),
                "uncertainty_kg": round(uncertainty, 3),
                "conservative_kg": round(max(PREDICTION_MIN_KG, expected - 0.50 * uncertainty), 3),
            }
        return details

    def status(self, planning_date: str | None = None) -> dict[str, Any]:
        eligible = self.eligible_for_date(planning_date) if planning_date else None
        weather_result = self._weather_features(planning_date)
        weather_active = self._weather_active(planning_date)
        active = self.ready and (eligible is not False)
        if weather_active:
            method = "weather-enhanced CatBoost productivity forecast"
            test = (self.metadata or {}).get("weather_test_metrics", {})
        elif active and self.base_model is not None:
            method = "CatBoost productivity forecast (approved base model)"
            test = (self.metadata or {}).get("base_test_metrics") or (self.metadata or {}).get("test_metrics", {})
        else:
            method = "historical median fallback"
            test = {}
        horizon_days = self.forecast_horizon_days(planning_date) if planning_date else None
        return {
            "ready": self.ready,
            "eligible_for_planning_date": eligible,
            "forecast_horizon_days": horizon_days,
            "maximum_forecast_horizon_days": MAX_FORECAST_HORIZON_DAYS,
            "method": method,
            "state_as_of": self.state_as_of,
            "planning_date": planning_date,
            "approved": bool((self.metadata or {}).get("approved")),
            "base_ready": self.base_model is not None,
            "weather_ready": self.weather_model is not None,
            "weather_active": weather_active,
            "weather_station": (self.weather_history.metadata.get("station_label") if self.weather_history else None),
            "weather_as_of": self.weather_history.date_max if self.weather_history else None,
            "weather_age_days": weather_result.age_days if weather_result else None,
            "weather_observed_days_7d": weather_result.observed_days_7d if weather_result else None,
            "morning_weather_available": weather_result.morning_available if weather_result else None,
            "test_mae_kg": test.get("model_mae_kg"),
            "baseline_test_mae_kg": test.get("baseline_mae_kg") or test.get("comparison_mae_kg"),
            "mae_improvement_pct": test.get("mae_improvement_pct"),
            "training_device": (self.metadata or {}).get("training_device"),
            "gpu_name": (self.metadata or {}).get("gpu_name"),
            "error": self.error,
            "base_error": self.base_error,
            "weather_error": self.weather_error,
        }
