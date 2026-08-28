from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import statistics
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


PACKAGE_VERSION = "5.0.0"
METHODS = (
    "RECENT_SAME_WEEKDAY_MEDIAN",
    "RECENT_28_OPERATING_MEDIAN",
    "SEASONAL_364_DAY_MEDIAN",
    "BLENDED_RECENT_SEASONAL",
)


def clean_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def estate_key(value: str) -> str:
    return "".join(ch for ch in clean_text(value).lower() if ch.isalnum())


def parse_date(value: Any) -> date:
    return datetime.strptime(clean_text(value), "%Y-%m-%d").date()


def parse_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(clean_text(value).replace(",", ""))
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def quantile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def winsorized(values: list[float]) -> list[float]:
    positive = [float(v) for v in values if v is not None and v > 0 and math.isfinite(v)]
    if len(positive) < 8:
        return positive
    low = quantile(positive, 0.05)
    high = quantile(positive, 0.95)
    return [min(high, max(low, value)) for value in positive]


def robust_stats(values: list[float]) -> dict[str, float]:
    cleaned = winsorized(values)
    if not cleaned:
        return {"n": 0, "median": 0.0, "p35": 0.0, "p25": 0.0}
    return {
        "n": len(cleaned),
        "median": statistics.median(cleaned),
        "p35": quantile(cleaned, 0.35),
        "p25": quantile(cleaned, 0.25),
    }


def median_or_none(values: Iterable[float | None]) -> float | None:
    cleaned = [float(v) for v in values if v is not None and v >= 0]
    return statistics.median(cleaned) if cleaned else None


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def read_gzip_csv(path: Path):
    with gzip.open(path, "rt", newline="", encoding="utf-8") as handle:
        yield from csv.DictReader(handle)


def allocate_exact(total: float, weights: dict[str, float]) -> dict[str, float]:
    if total <= 0 or not weights:
        return {key: 0.0 for key in weights}
    positive = {key: max(0.0, float(value)) for key, value in weights.items()}
    denominator = sum(positive.values())
    if denominator <= 0:
        equal = 1.0 / len(positive)
        positive = {key: equal for key in positive}
        denominator = 1.0
    shares = {key: value / denominator for key, value in positive.items()}
    allocations = {key: round(total * shares[key], 4) for key in sorted(shares)}
    difference = round(total - sum(allocations.values()), 4)
    if allocations and abs(difference) > 0:
        largest = max(shares, key=shares.get)
        allocations[largest] = round(allocations[largest] + difference, 4)
    return allocations


def value_before(series: dict[date, float], target: date, method: str) -> float | None:
    historical_dates = [day for day in series if day < target]
    if not historical_dates:
        return None

    if method == "RECENT_SAME_WEEKDAY_MEDIAN":
        candidates = sorted(
            (day for day in historical_dates if day.weekday() == target.weekday()),
            reverse=True,
        )[:8]
        return median_or_none(series[day] for day in candidates)

    if method == "RECENT_28_OPERATING_MEDIAN":
        cutoff = target - timedelta(days=35)
        candidates = [
            series[day] for day in historical_dates if cutoff <= day < target
        ]
        if len(candidates) < 5:
            candidates = [series[day] for day in sorted(historical_dates)[-20:]]
        return median_or_none(candidates)

    if method == "SEASONAL_364_DAY_MEDIAN":
        candidates: list[float] = []
        for years_back in (1, 2, 3, 4):
            anchor = target - timedelta(days=364 * years_back)
            for offset in (-14, -7, 0, 7, 14):
                candidate = anchor + timedelta(days=offset)
                if (
                    candidate < target
                    and candidate in series
                    and candidate.weekday() == target.weekday()
                ):
                    candidates.append(series[candidate])
        return median_or_none(candidates)

    if method == "BLENDED_RECENT_SEASONAL":
        recent = value_before(series, target, "RECENT_SAME_WEEKDAY_MEDIAN")
        seasonal = value_before(series, target, "SEASONAL_364_DAY_MEDIAN")
        if recent is not None and seasonal is not None:
            return 0.65 * recent + 0.35 * seasonal
        return recent if recent is not None else seasonal

    raise ValueError(f"Unknown forecasting method: {method}")


def method_policy(gate: str) -> tuple[str, int]:
    if gate == "ACCEPTED_DEVELOPMENT_CANDIDATE":
        return "WEIGHTED_TOP_2", 2
    if gate == "ACCEPTED_WITH_REVIEW":
        return "WEIGHTED_TOP_3", 3
    if gate == "PROVISIONAL_DAILY_CANDIDATE":
        return "ROBUST_MEDIAN_TOP_3", 3
    if gate == "PROVISIONAL_SHORT_HISTORY":
        return "SHORT_HISTORY_RECENT_MEDIAN", 2
    return "REJECTED_BASELINE_CONSERVATIVE_RECENT", 2


def ensemble_prediction(
    series: dict[date, float],
    target: date,
    method_metrics: list[dict[str, Any]],
    gate: str,
) -> tuple[float, str, str]:
    valid_predictions: list[tuple[str, float, float]] = []
    for row in sorted(method_metrics, key=lambda item: item["wape"]):
        prediction = value_before(series, target, row["method"])
        if prediction is not None:
            valid_predictions.append((row["method"], prediction, row["wape"]))

    recent_predictions = [
        item for item in valid_predictions
        if item[0] in {
            "RECENT_SAME_WEEKDAY_MEDIAN",
            "RECENT_28_OPERATING_MEDIAN",
        }
    ]

    policy, top_n = method_policy(gate)

    if gate in {"PROVISIONAL_SHORT_HISTORY", "REJECTED_DAILY_BASELINE"}:
        usable = recent_predictions[:top_n] or valid_predictions[:top_n]
        prediction = median_or_none(item[1] for item in usable)
        methods_used = "|".join(item[0] for item in usable)
        return float(prediction or 0.0), policy, methods_used

    usable = valid_predictions[:top_n]
    if not usable:
        fallback = median_or_none(series.values()) or 0.0
        return fallback, "ESTATE_HISTORY_MEDIAN_FALLBACK", "HISTORICAL_MEDIAN"

    if gate == "PROVISIONAL_DAILY_CANDIDATE":
        prediction = statistics.median(item[1] for item in usable)
    else:
        # Lower-WAPE methods receive more weight, but no single method is allowed
        # to dominate completely.
        raw_weights = [1.0 / max(1.0, item[2]) ** 2 for item in usable]
        total_weight = sum(raw_weights)
        weights = [weight / total_weight for weight in raw_weights]
        prediction = sum(item[1] * weight for item, weight in zip(usable, weights))

    methods_used = "|".join(item[0] for item in usable)
    return max(0.0, prediction), policy, methods_used


def uncertainty_factor(gate: str, best_wape: float, data_age_days: int) -> float:
    gate_multiplier = {
        "ACCEPTED_DEVELOPMENT_CANDIDATE": 1.00,
        "ACCEPTED_WITH_REVIEW": 1.15,
        "PROVISIONAL_DAILY_CANDIDATE": 1.35,
        "PROVISIONAL_SHORT_HISTORY": 1.55,
        "REJECTED_DAILY_BASELINE": 1.80,
    }.get(gate, 1.80)
    freshness_multiplier = 1.0 + min(0.50, max(0, data_age_days - 14) / 90.0)
    return min(0.80, max(0.10, best_wape / 100.0 * gate_multiplier * freshness_multiplier))


def blend_rate(
    field_stats: dict[str, float],
    division_stats: dict[str, float],
    estate_stats: dict[str, float],
    key: str,
) -> tuple[float, str]:
    field_n = int(field_stats["n"])
    division_value = division_stats.get(key, 0.0)
    estate_value = estate_stats.get(key, 0.0)

    fallback = division_value if division_value > 0 else estate_value
    if fallback <= 0:
        fallback = field_stats.get(key, 0.0)

    if field_n >= 60 and field_stats.get(key, 0.0) > 0:
        return field_stats[key], "FIELD"
    if field_n >= 15 and field_stats.get(key, 0.0) > 0 and fallback > 0:
        weight = field_n / (field_n + 30.0)
        value = weight * field_stats[key] + (1 - weight) * fallback
        return value, "FIELD_SHRUNK_TO_DIVISION"
    if fallback > 0:
        return fallback, "DIVISION_OR_ESTATE_FALLBACK"
    return 1.0, "EMERGENCY_RATE_FALLBACK"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Best-available planning outputs using the existing TTE data only."
    )
    parser.add_argument("--v4-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()

    v4_root = Path(args.v4_root).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    pointer = v4_root / "LATEST_DAILY_HIERARCHY_RUN.txt"
    if not pointer.exists():
        raise SystemExit(f"Missing v4 run pointer: {pointer}")

    v4_run = Path(pointer.read_text(encoding="utf-8").strip())
    required_paths = {
        "estate_history": v4_run / "historical" / "estate_daily.csv.gz",
        "field_history": v4_run / "historical" / "field_daily.csv.gz",
        "estate_forecast": v4_run / "forecast" / "estate_daily_forecast.csv",
        "division_forecast": v4_run / "forecast" / "division_daily_forecast.csv",
        "metrics": v4_run / "backtest" / "estate_candidate_metrics.csv",
        "gate": v4_run / "backtest" / "daily_candidate_gate.csv",
    }
    missing = [str(path) for path in required_paths.values() if not path.exists()]
    if missing:
        raise SystemExit("Required v4 outputs are missing:\n" + "\n".join(missing))

    run_folder = output_root / datetime.now().strftime(
        "best_available_planning_%Y%m%d_%H%M%S"
    )
    planning_dir = run_folder / "planning"
    quality_dir = run_folder / "quality"
    planning_dir.mkdir(parents=True, exist_ok=True)
    quality_dir.mkdir(parents=True, exist_ok=True)

    started = time.time()
    print(f"Best-available planning run: {run_folder}")
    print(f"Source v4 run: {v4_run}")
    print("Using the existing data only.")
    print("No live model, portal, allocator, CP-SAT or RL policy will change.")

    # Gate register.
    gate_rows = read_csv(required_paths["gate"])
    gate_by_estate = {estate_key(row["estate"]): row for row in gate_rows}

    # Candidate metrics.
    metrics_by_estate: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in read_csv(required_paths["metrics"]):
        wape = parse_float(row.get("wape_pct"))
        if wape is None:
            continue
        metrics_by_estate[estate_key(row["estate"])].append({
            "estate": row["estate"],
            "method": row["method"],
            "wape": wape,
            "mae": parse_float(row.get("mae_kg"), 0.0) or 0.0,
            "rmse": parse_float(row.get("rmse_kg"), 0.0) or 0.0,
        })

    # Estate historical series.
    estate_series: defaultdict[str, dict[date, float]] = defaultdict(dict)
    estate_display: dict[str, str] = {}
    for row in read_gzip_csv(required_paths["estate_history"]):
        key = estate_key(row["estate"])
        estate_display[key] = row["estate"]
        estate_series[key][parse_date(row["date"])] = (
            parse_float(row["green_leaf_kg"], 0.0) or 0.0
        )

    # Existing v4 operating-day signal.
    operating_rows = read_csv(required_paths["estate_forecast"])
    operating_by_key: dict[tuple[str, date], dict[str, str]] = {}
    for row in operating_rows:
        operating_by_key[(estate_key(row["estate"]), parse_date(row["date"]))] = row

    # Existing division shares.
    division_share_by_key: defaultdict[tuple[str, date], dict[str, float]] = defaultdict(dict)
    for row in read_csv(required_paths["division_forecast"]):
        key = (estate_key(row["estate"]), parse_date(row["date"]))
        division_share_by_key[key][row["division"]] = (
            parse_float(row.get("share_of_estate"), 0.0) or 0.0
        )

    # First pass over field history: recent schedule and productivity features.
    estate_max_date = {key: max(series) for key, series in estate_series.items()}
    field_records: defaultdict[tuple[str, str, str], list[tuple[date, float, int, float]]] = defaultdict(list)
    division_day_fields: defaultdict[tuple[str, str, date], int] = defaultdict(int)
    division_operating_dates: defaultdict[tuple[str, str], set[date]] = defaultdict(set)
    estate_rate_values: defaultdict[str, list[float]] = defaultdict(list)
    division_rate_values: defaultdict[tuple[str, str], list[float]] = defaultdict(list)
    field_rate_values: defaultdict[tuple[str, str, str], list[float]] = defaultdict(list)

    for row in read_gzip_csv(required_paths["field_history"]):
        key = estate_key(row["estate"])
        row_date = parse_date(row["date"])
        if key not in estate_max_date:
            continue
        if row_date < estate_max_date[key] - timedelta(days=400):
            continue

        division = row["division"]
        field_code = row["field"]
        crop = parse_float(row["green_leaf_kg"], 0.0) or 0.0
        pluckers = int(parse_float(row.get("plucker_count"), 0.0) or 0)
        rate = crop / pluckers if crop > 0 and pluckers > 0 else 0.0

        field_key = (key, division, field_code)
        field_records[field_key].append((row_date, crop, pluckers, rate))
        division_day_fields[(key, division, row_date)] += 1
        division_operating_dates[(key, division)].add(row_date)

        if rate > 0:
            estate_rate_values[key].append(rate)
            division_rate_values[(key, division)].append(rate)
            field_rate_values[field_key].append(rate)

    estate_rate_stats = {
        key: robust_stats(values) for key, values in estate_rate_values.items()
    }
    division_rate_stats = {
        key: robust_stats(values) for key, values in division_rate_values.items()
    }
    field_rate_stats = {
        key: robust_stats(values) for key, values in field_rate_values.items()
    }

    fields_by_division: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
    field_schedule_features: dict[tuple[str, str, str], dict[str, Any]] = {}
    division_crop_totals: defaultdict[tuple[str, str], float] = defaultdict(float)

    for (key, division, field_code), records in field_records.items():
        fields_by_division[(key, division)].append(field_code)
        records.sort(key=lambda item: item[0])
        dates = [item[0] for item in records]
        crops = [item[1] for item in records]
        division_crop_totals[(key, division)] += sum(crops)

        intervals = [
            (later - earlier).days
            for earlier, later in zip(dates, dates[1:])
            if (later - earlier).days > 0
        ]
        median_interval = statistics.median(intervals) if intervals else 7.0
        field_schedule_features[(key, division, field_code)] = {
            "last_date": max(dates),
            "median_interval": max(1.0, median_interval),
            "crop_total": sum(crops),
            "active_dates": set(dates),
            "records": len(records),
        }

    # Historical expected active-field count by division and weekday.
    active_count_by_weekday: defaultdict[tuple[str, str, int], list[int]] = defaultdict(list)
    active_count_all: defaultdict[tuple[str, str], list[int]] = defaultdict(list)
    for (key, division, row_date), count in division_day_fields.items():
        active_count_by_weekday[(key, division, row_date.weekday())].append(count)
        active_count_all[(key, division)].append(count)

    method_register: list[dict[str, Any]] = []
    estate_plan: list[dict[str, Any]] = []
    division_plan: list[dict[str, Any]] = []
    field_plan: list[dict[str, Any]] = []
    field_demand: list[dict[str, Any]] = []
    reconciliation: list[dict[str, Any]] = []
    schedule_diagnostics: list[dict[str, Any]] = []

    forecast_dates = sorted({parse_date(row["date"]) for row in operating_rows})
    estates = sorted(estate_series)

    for estate_index, key in enumerate(estates, start=1):
        display = estate_display.get(key, key)
        print(f"[{estate_index}/{len(estates)}] Planning {display}", flush=True)
        gate_row = gate_by_estate.get(key)
        if gate_row is None:
            raise RuntimeError(f"Missing daily candidate gate for {display}")
        gate = gate_row["development_gate"]
        best_wape = parse_float(gate_row.get("wape_pct"), 100.0) or 100.0
        series = estate_series[key]
        history_end = max(series)
        metrics = metrics_by_estate.get(key, [])
        policy, _ = method_policy(gate)

        method_register.append({
            "estate": display,
            "development_gate": gate,
            "best_selected_wape_pct": round(best_wape, 4),
            "ensemble_policy": policy,
            "source_history_end": history_end.isoformat(),
            "source_status": "EXISTING_DATA_ONLY_STALE_SCENARIO",
            "operational_status": "DEVELOPMENT_PLANNING_ONLY",
        })

        for target in forecast_dates:
            operating = operating_by_key.get((key, target), {})
            planned_operating = clean_text(operating.get("planned_operating_day")).upper() == "TRUE"
            operating_probability = parse_float(
                operating.get("operating_day_probability"), 0.0
            ) or 0.0
            data_age_days = (target - history_end).days

            central_if_operating, ensemble_policy, methods_used = ensemble_prediction(
                series, target, metrics, gate
            )
            central_crop = central_if_operating if planned_operating else 0.0
            risk = uncertainty_factor(gate, best_wape, data_age_days)
            lower_crop = max(0.0, central_crop * (1.0 - risk))
            upper_crop = central_crop * (1.0 + risk)

            estate_plan.append({
                "date": target.isoformat(),
                "estate": display,
                "development_gate": gate,
                "ensemble_policy": ensemble_policy,
                "methods_used": methods_used,
                "best_selected_wape_pct": round(best_wape, 4),
                "planned_operating_day": str(planned_operating).upper(),
                "operating_day_probability": round(operating_probability, 4),
                "central_crop_kg": round(central_crop, 4),
                "lower_crop_kg": round(lower_crop, 4),
                "upper_conservative_crop_kg": round(upper_crop, 4),
                "uncertainty_pct": round(risk * 100, 4),
                "source_history_end": history_end.isoformat(),
                "source_age_days": data_age_days,
                "source_status": "EXISTING_DATA_ONLY_STALE_SCENARIO",
                "output_status": "DEVELOPMENT_PLANNING_ONLY",
            })

            division_shares = division_share_by_key.get((key, target), {})
            if not division_shares and central_crop > 0:
                divisions = sorted(
                    division for estate, division in fields_by_division if estate == key
                )
                equal = 1.0 / len(divisions) if divisions else 0.0
                division_shares = {division: equal for division in divisions}

            division_central = allocate_exact(central_crop, division_shares)
            division_lower = allocate_exact(lower_crop, division_shares)
            division_upper = allocate_exact(upper_crop, division_shares)

            estate_field_central = 0.0
            estate_field_lower = 0.0
            estate_field_upper = 0.0
            estate_expected_assignments = 0
            estate_recommended_assignments = 0

            for division in sorted(division_central):
                central_div = division_central[division]
                lower_div = division_lower.get(division, 0.0)
                upper_div = division_upper.get(division, 0.0)
                available_fields = sorted(set(fields_by_division.get((key, division), [])))

                if not planned_operating or central_div <= 0 or not available_fields:
                    active_fields: list[str] = []
                    expected_active_count = 0
                    selected_weights: dict[str, float] = {}
                else:
                    same_weekday_counts = active_count_by_weekday.get(
                        (key, division, target.weekday()), []
                    )
                    all_counts = active_count_all.get((key, division), [])
                    source_counts = same_weekday_counts if len(same_weekday_counts) >= 4 else all_counts
                    expected_active_count = int(round(statistics.median(source_counts))) if source_counts else 1
                    expected_active_count = max(1, min(len(available_fields), expected_active_count))

                    division_dates = division_operating_dates.get((key, division), set())
                    same_weekday_denominator = max(
                        1, sum(1 for day in division_dates if day.weekday() == target.weekday())
                    )
                    total_division_crop = max(1.0, division_crop_totals.get((key, division), 0.0))
                    scores: dict[str, float] = {}
                    allocation_scores: dict[str, float] = {}

                    for field_code in available_fields:
                        feature = field_schedule_features[(key, division, field_code)]
                        active_same_weekday = sum(
                            1 for day in feature["active_dates"]
                            if day.weekday() == target.weekday()
                        )
                        frequency = min(1.0, active_same_weekday / same_weekday_denominator)
                        days_since = max(0, (target - feature["last_date"]).days)
                        due = min(1.0, days_since / max(1.0, feature["median_interval"] * 2.0))
                        share = feature["crop_total"] / total_division_crop
                        scores[field_code] = 0.45 * frequency + 0.35 * due + 0.20 * min(1.0, share * len(available_fields))
                        allocation_scores[field_code] = (
                            0.45 * share
                            + 0.30 * frequency / max(1, len(available_fields))
                            + 0.25 * due / max(1, len(available_fields))
                        )

                    active_fields = [
                        field_code for field_code, _ in sorted(
                            scores.items(), key=lambda item: item[1], reverse=True
                        )[:expected_active_count]
                    ]
                    selected_weights = {
                        field_code: allocation_scores[field_code]
                        for field_code in active_fields
                    }

                field_central_alloc = allocate_exact(central_div, selected_weights)
                field_lower_alloc = allocate_exact(lower_div, selected_weights)
                field_upper_alloc = allocate_exact(upper_div, selected_weights)

                division_expected_assignments = 0
                division_recommended_assignments = 0
                for field_code in active_fields:
                    central_field = field_central_alloc.get(field_code, 0.0)
                    lower_field = field_lower_alloc.get(field_code, 0.0)
                    upper_field = field_upper_alloc.get(field_code, 0.0)
                    field_key = (key, division, field_code)
                    fstats = field_rate_stats.get(
                        field_key, {"n": 0, "median": 0.0, "p35": 0.0, "p25": 0.0}
                    )
                    dstats = division_rate_stats.get(
                        (key, division), {"n": 0, "median": 0.0, "p35": 0.0, "p25": 0.0}
                    )
                    estats = estate_rate_stats.get(
                        key, {"n": 0, "median": 0.0, "p35": 0.0, "p25": 0.0}
                    )
                    expected_rate, expected_rate_source = blend_rate(
                        fstats, dstats, estats, "median"
                    )
                    conservative_rate, conservative_rate_source = blend_rate(
                        fstats, dstats, estats, "p35"
                    )
                    conservative_rate = min(expected_rate, conservative_rate) if expected_rate > 0 else conservative_rate
                    expected_rate = max(1.0, expected_rate)
                    conservative_rate = max(1.0, conservative_rate)

                    expected_assignments = (
                        int(math.ceil(central_field / expected_rate))
                        if central_field > 0 else 0
                    )
                    recommended_assignments = (
                        int(math.ceil(upper_field / conservative_rate))
                        if upper_field > 0 else 0
                    )
                    buffer_assignments = max(0, recommended_assignments - expected_assignments)

                    sample_count = int(fstats["n"])
                    confidence = "LOW"
                    if sample_count >= 60 and gate in {
                        "ACCEPTED_DEVELOPMENT_CANDIDATE",
                        "ACCEPTED_WITH_REVIEW",
                    }:
                        confidence = "MEDIUM"
                    if sample_count >= 120 and gate == "ACCEPTED_DEVELOPMENT_CANDIDATE":
                        confidence = "MEDIUM_HIGH"
                    if gate in {
                        "PROVISIONAL_DAILY_CANDIDATE",
                        "PROVISIONAL_SHORT_HISTORY",
                        "REJECTED_DAILY_BASELINE",
                    }:
                        confidence = "LOW"

                    field_plan.append({
                        "date": target.isoformat(),
                        "estate": display,
                        "division": division,
                        "field": field_code,
                        "active_field": "TRUE",
                        "central_crop_kg": round(central_field, 4),
                        "lower_crop_kg": round(lower_field, 4),
                        "upper_conservative_crop_kg": round(upper_field, 4),
                        "field_schedule_method": "HISTORICAL_ACTIVE_FIELD_COUNT_PLUS_DUE_SCORE",
                        "output_status": "DEVELOPMENT_PLANNING_ONLY",
                    })
                    field_demand.append({
                        "date": target.isoformat(),
                        "estate": display,
                        "division": division,
                        "field": field_code,
                        "central_crop_kg": round(central_field, 4),
                        "upper_conservative_crop_kg": round(upper_field, 4),
                        "expected_productivity_kg_per_plucker": round(expected_rate, 4),
                        "conservative_productivity_kg_per_plucker": round(conservative_rate, 4),
                        "productivity_source": expected_rate_source,
                        "conservative_productivity_source": conservative_rate_source,
                        "field_productivity_sample_days": sample_count,
                        "expected_plucker_assignments": expected_assignments,
                        "recommended_plucker_assignments": recommended_assignments,
                        "buffer_assignments": buffer_assignments,
                        "planning_confidence": confidence,
                        "development_gate": gate,
                        "source_status": "EXISTING_DATA_ONLY_STALE_SCENARIO",
                        "assignment_note": "Headcount-equivalent field assignments; unique employees require availability and CP-SAT.",
                    })

                    division_expected_assignments += expected_assignments
                    division_recommended_assignments += recommended_assignments

                division_plan.append({
                    "date": target.isoformat(),
                    "estate": display,
                    "division": division,
                    "central_crop_kg": round(central_div, 4),
                    "lower_crop_kg": round(lower_div, 4),
                    "upper_conservative_crop_kg": round(upper_div, 4),
                    "available_field_count": len(available_fields),
                    "planned_active_field_count": len(active_fields),
                    "expected_plucker_assignments": division_expected_assignments,
                    "recommended_plucker_assignments": division_recommended_assignments,
                    "development_gate": gate,
                    "output_status": "DEVELOPMENT_PLANNING_ONLY",
                })
                schedule_diagnostics.append({
                    "date": target.isoformat(),
                    "estate": display,
                    "division": division,
                    "available_field_count": len(available_fields),
                    "historical_expected_active_field_count": expected_active_count,
                    "selected_active_field_count": len(active_fields),
                    "selected_fields": "|".join(active_fields),
                    "schedule_status": (
                        "PASS" if central_div == 0 or len(active_fields) > 0 else "FAIL"
                    ),
                })

                estate_field_central += sum(field_central_alloc.values())
                estate_field_lower += sum(field_lower_alloc.values())
                estate_field_upper += sum(field_upper_alloc.values())
                estate_expected_assignments += division_expected_assignments
                estate_recommended_assignments += division_recommended_assignments

            reconciliation.append({
                "date": target.isoformat(),
                "estate": display,
                "estate_central_crop_kg": round(central_crop, 4),
                "field_central_sum_kg": round(estate_field_central, 4),
                "estate_lower_crop_kg": round(lower_crop, 4),
                "field_lower_sum_kg": round(estate_field_lower, 4),
                "estate_upper_crop_kg": round(upper_crop, 4),
                "field_upper_sum_kg": round(estate_field_upper, 4),
                "central_difference_kg": round(central_crop - estate_field_central, 6),
                "lower_difference_kg": round(lower_crop - estate_field_lower, 6),
                "upper_difference_kg": round(upper_crop - estate_field_upper, 6),
                "reconciliation_status": (
                    "PASS"
                    if abs(central_crop - estate_field_central) <= 0.02
                    and abs(lower_crop - estate_field_lower) <= 0.02
                    and abs(upper_crop - estate_field_upper) <= 0.02
                    else "FAIL"
                ),
                "expected_plucker_assignments": estate_expected_assignments,
                "recommended_plucker_assignments": estate_recommended_assignments,
            })

    # Summaries from division rows.
    estate_demand: list[dict[str, Any]] = []
    division_demand = [
        {
            "date": row["date"],
            "estate": row["estate"],
            "division": row["division"],
            "central_crop_kg": row["central_crop_kg"],
            "upper_conservative_crop_kg": row["upper_conservative_crop_kg"],
            "planned_active_field_count": row["planned_active_field_count"],
            "expected_plucker_assignments": row["expected_plucker_assignments"],
            "recommended_plucker_assignments": row["recommended_plucker_assignments"],
            "buffer_assignments": max(
                0,
                int(row["recommended_plucker_assignments"])
                - int(row["expected_plucker_assignments"]),
            ),
            "development_gate": row["development_gate"],
            "output_status": row["output_status"],
        }
        for row in division_plan
    ]

    estate_plan_lookup = {
        (row["estate"], row["date"]): row for row in estate_plan
    }
    for row in reconciliation:
        source = estate_plan_lookup[(row["estate"], row["date"])]
        estate_demand.append({
            "date": row["date"],
            "estate": row["estate"],
            "central_crop_kg": row["estate_central_crop_kg"],
            "upper_conservative_crop_kg": row["estate_upper_crop_kg"],
            "expected_plucker_assignments": row["expected_plucker_assignments"],
            "recommended_plucker_assignments": row["recommended_plucker_assignments"],
            "buffer_assignments": max(
                0,
                int(row["recommended_plucker_assignments"])
                - int(row["expected_plucker_assignments"]),
            ),
            "development_gate": source["development_gate"],
            "best_selected_wape_pct": source["best_selected_wape_pct"],
            "source_age_days": source["source_age_days"],
            "source_status": source["source_status"],
            "output_status": "DEVELOPMENT_PLANNING_ONLY",
        })

    # Write outputs.
    write_csv(
        planning_dir / "estate_crop_planning.csv",
        estate_plan,
        [
            "date", "estate", "development_gate", "ensemble_policy", "methods_used",
            "best_selected_wape_pct", "planned_operating_day",
            "operating_day_probability", "central_crop_kg", "lower_crop_kg",
            "upper_conservative_crop_kg", "uncertainty_pct",
            "source_history_end", "source_age_days", "source_status", "output_status",
        ],
    )
    write_csv(
        planning_dir / "division_crop_and_plucker_demand.csv",
        division_demand,
        [
            "date", "estate", "division", "central_crop_kg",
            "upper_conservative_crop_kg", "planned_active_field_count",
            "expected_plucker_assignments", "recommended_plucker_assignments",
            "buffer_assignments", "development_gate", "output_status",
        ],
    )
    write_csv(
        planning_dir / "field_crop_planning.csv",
        field_plan,
        [
            "date", "estate", "division", "field", "active_field",
            "central_crop_kg", "lower_crop_kg", "upper_conservative_crop_kg",
            "field_schedule_method", "output_status",
        ],
    )
    write_csv(
        planning_dir / "field_required_plucker_assignments.csv",
        field_demand,
        [
            "date", "estate", "division", "field", "central_crop_kg",
            "upper_conservative_crop_kg", "expected_productivity_kg_per_plucker",
            "conservative_productivity_kg_per_plucker", "productivity_source",
            "conservative_productivity_source", "field_productivity_sample_days",
            "expected_plucker_assignments", "recommended_plucker_assignments",
            "buffer_assignments", "planning_confidence", "development_gate",
            "source_status", "assignment_note",
        ],
    )
    write_csv(
        planning_dir / "estate_required_plucker_assignments.csv",
        estate_demand,
        [
            "date", "estate", "central_crop_kg", "upper_conservative_crop_kg",
            "expected_plucker_assignments", "recommended_plucker_assignments",
            "buffer_assignments", "development_gate", "best_selected_wape_pct",
            "source_age_days", "source_status", "output_status",
        ],
    )
    write_csv(
        quality_dir / "method_and_gate_register.csv",
        method_register,
        [
            "estate", "development_gate", "best_selected_wape_pct",
            "ensemble_policy", "source_history_end", "source_status",
            "operational_status",
        ],
    )
    write_csv(
        quality_dir / "field_schedule_diagnostics.csv",
        schedule_diagnostics,
        [
            "date", "estate", "division", "available_field_count",
            "historical_expected_active_field_count", "selected_active_field_count",
            "selected_fields", "schedule_status",
        ],
    )
    write_csv(
        quality_dir / "hierarchy_reconciliation.csv",
        reconciliation,
        [
            "date", "estate", "estate_central_crop_kg", "field_central_sum_kg",
            "estate_lower_crop_kg", "field_lower_sum_kg",
            "estate_upper_crop_kg", "field_upper_sum_kg",
            "central_difference_kg", "lower_difference_kg", "upper_difference_kg",
            "reconciliation_status", "expected_plucker_assignments",
            "recommended_plucker_assignments",
        ],
    )

    reconciliation_failures = sum(
        1 for row in reconciliation if row["reconciliation_status"] != "PASS"
    )
    schedule_failures = sum(
        1 for row in schedule_diagnostics if row["schedule_status"] != "PASS"
    )
    duration_minutes = round((time.time() - started) / 60, 2)
    gate_counts: defaultdict[str, int] = defaultdict(int)
    for row in method_register:
        gate_counts[row["development_gate"]] += 1

    summary = {
        "status": (
            "PASS_DEVELOPMENT_OUTPUTS"
            if reconciliation_failures == 0 and schedule_failures == 0
            else "FAIL"
        ),
        "package_version": PACKAGE_VERSION,
        "run_folder": str(run_folder),
        "source_v4_run": str(v4_run),
        "estates": len(estates),
        "forecast_dates": len(forecast_dates),
        "estate_planning_rows": len(estate_plan),
        "division_planning_rows": len(division_demand),
        "active_field_planning_rows": len(field_plan),
        "field_plucker_demand_rows": len(field_demand),
        "reconciliation_failures": reconciliation_failures,
        "schedule_failures": schedule_failures,
        "development_gate_counts": dict(sorted(gate_counts.items())),
        "data_policy": "USE_EXISTING_DATA_ONLY",
        "source_status": "STALE_SOURCE_ACCEPTED_BY_USER_FOR_DEVELOPMENT_OUTPUTS",
        "operational_status": "DEVELOPMENT_AND_SCENARIO_PLANNING_ONLY",
        "duration_minutes": duration_minutes,
        "live_models_changed": False,
        "portal_changed": False,
        "allocator_changed": False,
        "cp_sat_started": False,
        "rl_started": False,
        "important_interpretation": [
            "Recommended plucker values are headcount-equivalent field assignments, not a unique employee roster.",
            "Field activation is inferred from historical active-field counts, weekday frequency and plucking-due score.",
            "Crop forecasts use risk-gated ensembles or robust historical fallbacks according to the saved daily candidate gate.",
            "The upper conservative crop and lower productivity rate are used for recommended assignment counts.",
            "Stale source data increases uncertainty but is not silently presented as current operational data.",
        ],
    }
    (run_folder / "run_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    (run_folder / "README.txt").write_text(
        "\n".join([
            "TTE BEST-AVAILABLE PLANNING OUTPUTS v5.0.0",
            "",
            "These outputs use the currently available data only.",
            "They are development/scenario-planning outputs, not live allocations.",
            "",
            "Use estate_required_plucker_assignments.csv for estate-day planning.",
            "Use division_crop_and_plucker_demand.csv for division-day planning.",
            "Use field_required_plucker_assignments.csv for field assignment demand.",
            "",
            "Recommended plucker counts are headcount-equivalent field assignments.",
            "A unique employee roster still requires attendance, leave, skills,",
            "medical restrictions, movement rules and CP-SAT.",
        ]) + "\n",
        encoding="utf-8",
    )
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "LATEST_BEST_AVAILABLE_PLANNING_RUN.txt").write_text(
        str(run_folder), encoding="utf-8"
    )

    print("")
    print("BEST-AVAILABLE EXISTING-DATA OUTPUTS FINISHED")
    print(json.dumps(summary, indent=2))
    return 0 if summary["status"] == "PASS_DEVELOPMENT_OUTPUTS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
