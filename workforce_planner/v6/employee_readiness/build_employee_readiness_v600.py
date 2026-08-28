from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import random
import statistics
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


VERSION = "6.0.0"
TECHNICAL_STATUS = "DEVELOPMENT_INPUT_PREPARATION_ONLY"


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def estate_key(value: str) -> str:
    return "".join(ch for ch in clean(value).lower() if ch.isalnum())


def parse_date(value: Any) -> date | None:
    text = clean(value)
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(clean(value).replace(",", ""))
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def as_bool(value: Any) -> bool:
    return clean(value).lower() in {"1", "true", "yes", "y", "approved"}


def quantile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def stream_gzip_csv(path: Path):
    with gzip.open(path, "rt", newline="", encoding="utf-8-sig") as handle:
        yield from csv.DictReader(handle)


def reservoir_target_sample(path: Path, sample_size: int, seed: int) -> list[float]:
    rng = random.Random(seed)
    sample: list[float] = []
    seen = 0
    for row in stream_gzip_csv(path):
        target = parse_float(row.get("target_kg"))
        if target is None or target <= 0:
            continue
        seen += 1
        if len(sample) < sample_size:
            sample.append(target)
        else:
            index = rng.randint(1, seen)
            if index <= sample_size:
                sample[index - 1] = target
    return sample


def update_stat(stat: dict[str, Any], day: date, value: float, alpha: float = 0.10) -> None:
    stat["count"] += 1
    stat["sum"] += value
    stat["sum_sq"] += value * value
    if stat["ewma"] is None:
        stat["ewma"] = value
    else:
        stat["ewma"] = alpha * value + (1.0 - alpha) * stat["ewma"]
    if stat["first_date"] is None or day < stat["first_date"]:
        stat["first_date"] = day
    if stat["last_date"] is None or day > stat["last_date"]:
        stat["last_date"] = day
        stat["last_value"] = value


def new_stat() -> dict[str, Any]:
    return {
        "count": 0,
        "sum": 0.0,
        "sum_sq": 0.0,
        "ewma": None,
        "first_date": None,
        "last_date": None,
        "last_value": None,
    }


def final_stat(stat: dict[str, Any]) -> dict[str, float]:
    count = int(stat["count"])
    mean = stat["sum"] / count if count else 0.0
    variance = max(0.0, stat["sum_sq"] / count - mean * mean) if count else 0.0
    return {
        "count": count,
        "mean": mean,
        "std": math.sqrt(variance),
        "ewma": float(stat["ewma"] or 0.0),
    }


def activity_class(last_day: date | None, history_end: date) -> str:
    if last_day is None:
        return "NO_ACTIVITY_DATE"
    age = (history_end - last_day).days
    if age <= 180:
        return "ACTIVE_WITHIN_180_DAYS"
    if age <= 365:
        return "RECENT_WITHIN_365_DAYS"
    return "INACTIVE_OVER_365_DAYS"


def model_policy(portfolio_row: dict[str, str] | None) -> tuple[str, str]:
    if not portfolio_row:
        return "HISTORICAL_FALLBACK_ONLY", "PORTFOLIO_STATUS_MISSING"
    if as_bool(portfolio_row.get("base_approved")):
        return "CATBOOST_SHADOW_CANDIDATE_AVAILABLE", "APPROVED_DEVELOPMENT_CANDIDATE"
    return "HISTORICAL_FALLBACK_ONLY", "MODEL_REJECTED_OR_NOT_APPROVED"


def select_home_division(
    source_home_counter: Counter[str],
    observed_division_counter: Counter[str],
) -> tuple[str, str]:
    valid_source = Counter({
        key: value
        for key, value in source_home_counter.items()
        if key and key.upper() not in {"UNK", "UNKNOWN", "NA", "N/A", "NONE"}
    })
    if valid_source:
        return valid_source.most_common(1)[0][0], "SOURCE_HOME_DIVISION_MODE"
    if observed_division_counter:
        return (
            observed_division_counter.most_common(1)[0][0],
            "INFERRED_MODAL_FIELD_DIVISION",
        )
    return "UNKNOWN", "UNAVAILABLE"


def candidate_expected(
    pair: dict[str, Any] | None,
    division: dict[str, Any] | None,
    employee: dict[str, Any],
) -> tuple[float, float, str, int, date | None]:
    emp = final_stat(employee)
    employee_mean = emp["mean"]
    employee_ewma = emp["ewma"]

    if pair and pair["count"] >= 5:
        pair_final = final_stat(pair)
        reliability = pair["count"] / (pair["count"] + 20.0)
        expected = (
            reliability * pair_final["mean"]
            + (1.0 - reliability) * employee_mean
        )
        recent = pair_final["ewma"]
        source = "EMPLOYEE_FIELD_SHRUNK_MEAN"
        count = int(pair["count"])
        last_day = pair["last_date"]
    elif division and division["count"] >= 5:
        division_final = final_stat(division)
        reliability = division["count"] / (division["count"] + 30.0)
        expected = (
            reliability * division_final["mean"]
            + (1.0 - reliability) * employee_mean
        )
        recent = division_final["ewma"]
        source = "EMPLOYEE_DIVISION_SHRUNK_MEAN"
        count = int(division["count"])
        last_day = division["last_date"]
    else:
        expected = employee_mean
        recent = employee_ewma
        source = "EMPLOYEE_ESTATE_HISTORY_MEAN"
        count = int(employee["count"])
        last_day = employee["last_date"]

    expected = max(1.0, expected)
    conservative = max(1.0, min(expected, recent if recent > 0 else expected) * 0.90)
    return expected, conservative, source, count, last_day


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build employee readiness and constraint inputs for CP-SAT shadow planning."
    )
    parser.add_argument("--productivity-run", required=True)
    parser.add_argument("--planning-run", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--sample-size", type=int, default=20000)
    parser.add_argument("--max-candidates-per-field", type=int, default=250)
    args = parser.parse_args()

    productivity_run = Path(args.productivity_run).resolve()
    planning_run = Path(args.planning_run).resolve()
    output_root = Path(args.output_root).resolve()

    demand_path = planning_run / "planning" / "field_required_plucker_assignments.csv"
    portfolio_path = productivity_run / "productivity_portfolio_summary.csv"
    training_files = sorted(productivity_run.glob("*/data/productivity_training.csv.gz"))

    if not demand_path.exists():
        raise SystemExit(f"Missing final field demand: {demand_path}")
    if not portfolio_path.exists():
        raise SystemExit(f"Missing productivity portfolio summary: {portfolio_path}")
    if len(training_files) != 33:
        raise SystemExit(
            f"Expected 33 productivity training files but found {len(training_files)}"
        )

    run_folder = output_root / datetime.now().strftime(
        "employee_readiness_%Y%m%d_%H%M%S"
    )
    registers_dir = run_folder / "registers"
    templates_dir = run_folder / "templates"
    candidates_dir = run_folder / "candidates"
    quality_dir = run_folder / "quality"
    for folder in (registers_dir, templates_dir, candidates_dir, quality_dir):
        folder.mkdir(parents=True, exist_ok=True)

    started = time.time()
    print(f"Employee readiness run: {run_folder}")
    print(f"Productivity source: {productivity_run}")
    print(f"Planning source: {planning_run}")
    print("No CP-SAT allocation or RL policy will run.")

    portfolio_rows = read_csv(portfolio_path)
    portfolio = {estate_key(row["estate"]): row for row in portfolio_rows}

    demand_rows = read_csv(demand_path)
    demand_dates = sorted({parse_date(row.get("date")) for row in demand_rows if parse_date(row.get("date"))})
    if not demand_dates:
        raise SystemExit("No valid dates in field demand file.")
    first_date = demand_dates[0]
    first_date_demand = [
        row for row in demand_rows
        if parse_date(row.get("date")) == first_date
        and int(parse_float(row.get("recommended_plucker_assignments"), 0.0) or 0) > 0
    ]

    employee_stats: dict[tuple[str, str], dict[str, Any]] = {}
    employee_division_stats: dict[tuple[str, str, str], dict[str, Any]] = {}
    employee_field_stats: dict[tuple[str, str, str], dict[str, Any]] = {}
    employee_division_counter: defaultdict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    employee_home_counter: defaultdict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    employee_field_counter: defaultdict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    estate_display: dict[str, str] = {}
    estate_history_end: dict[str, date] = {}
    estate_clip_register: list[dict[str, Any]] = []
    source_rows = 0
    retained_rows = 0
    invalid_rows = 0

    for index, training_path in enumerate(training_files, start=1):
        estate_name = training_path.parent.parent.name
        key = estate_key(estate_name)
        estate_display[key] = estate_name
        print(f"[{index}/33] Reading {estate_name}", flush=True)

        sample = reservoir_target_sample(
            training_path,
            max(1000, args.sample_size),
            seed=sum(ord(ch) for ch in estate_name),
        )
        if not sample:
            raise RuntimeError(f"No positive target values in {training_path}")

        lower_clip = max(0.5, quantile(sample, 0.01))
        upper_clip = max(lower_clip + 1.0, quantile(sample, 0.99))
        clipped_low = 0
        clipped_high = 0
        estate_rows = 0

        for row in stream_gzip_csv(training_path):
            source_rows += 1
            estate_rows += 1
            employee_id = clean(row.get("employee_id"))
            field_id = clean(row.get("field_id"))
            field_division = clean(row.get("field_division")) or "UNKNOWN"
            source_home = clean(row.get("home_division")) or "UNKNOWN"
            day = parse_date(row.get("date"))
            target = parse_float(row.get("target_kg"))

            if not employee_id or not field_id or day is None or target is None or target <= 0:
                invalid_rows += 1
                continue

            value = target
            if value < lower_clip:
                value = lower_clip
                clipped_low += 1
            elif value > upper_clip:
                value = upper_clip
                clipped_high += 1

            retained_rows += 1
            estate_history_end[key] = max(estate_history_end.get(key, day), day)
            emp_key = (key, employee_id)
            div_key = (key, employee_id, field_division)
            field_key = (key, employee_id, field_id)

            employee_stats.setdefault(emp_key, new_stat())
            employee_division_stats.setdefault(div_key, new_stat())
            employee_field_stats.setdefault(field_key, new_stat())

            update_stat(employee_stats[emp_key], day, value)
            update_stat(employee_division_stats[div_key], day, value)
            update_stat(employee_field_stats[field_key], day, value)

            employee_division_counter[emp_key][field_division] += 1
            employee_home_counter[emp_key][source_home] += 1
            employee_field_counter[emp_key][field_id] += 1

            employee_field_stats[field_key]["field_division"] = field_division

        estate_clip_register.append({
            "estate": estate_name,
            "sample_values": len(sample),
            "lower_clip_kg": round(lower_clip, 4),
            "upper_clip_kg": round(upper_clip, 4),
            "source_rows": estate_rows,
            "clipped_low_rows": clipped_low,
            "clipped_high_rows": clipped_high,
        })

    employee_master_rows: list[dict[str, Any]] = []
    employee_master_lookup: dict[tuple[str, str], dict[str, Any]] = {}

    for emp_key in sorted(employee_stats):
        key, employee_id = emp_key
        stat = employee_stats[emp_key]
        final = final_stat(stat)
        history_end = estate_history_end[key]
        home_division, home_source = select_home_division(
            employee_home_counter[emp_key],
            employee_division_counter[emp_key],
        )
        policy, model_status = model_policy(portfolio.get(key))
        last_day = stat["last_date"]
        row = {
            "estate": estate_display[key],
            "employee_id": employee_id,
            "inferred_home_division": home_division,
            "home_division_source": home_source,
            "first_observed_date": stat["first_date"].isoformat(),
            "last_observed_date": last_day.isoformat(),
            "days_since_last_observed": (history_end - last_day).days,
            "activity_class": activity_class(last_day, history_end),
            "observation_count": final["count"],
            "distinct_fields": len(employee_field_counter[emp_key]),
            "distinct_divisions": len(employee_division_counter[emp_key]),
            "historical_mean_kg": round(final["mean"], 4),
            "recent_ewma_kg": round(final["ewma"], 4),
            "historical_std_kg": round(final["std"], 4),
            "productivity_model_policy": policy,
            "estate_model_status": model_status,
            "allocation_status": "BLOCKED_PENDING_AVAILABILITY_AND_CONSTRAINTS",
        }
        employee_master_rows.append(row)
        employee_master_lookup[emp_key] = row

    field_experience_rows: list[dict[str, Any]] = []
    field_index: defaultdict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    division_index: defaultdict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    estate_index: defaultdict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)

    for (key, employee_id), emp_stat in employee_stats.items():
        estate_index[key].append((employee_id, emp_stat))

    for (key, employee_id, division), stat in employee_division_stats.items():
        division_index[(key, division)].append((employee_id, stat))

    for (key, employee_id, field_id), stat in employee_field_stats.items():
        final = final_stat(stat)
        division = clean(stat.get("field_division")) or "UNKNOWN"
        field_experience_rows.append({
            "estate": estate_display[key],
            "employee_id": employee_id,
            "field_id": field_id,
            "field_division": division,
            "observation_count": final["count"],
            "first_observed_date": stat["first_date"].isoformat(),
            "last_observed_date": stat["last_date"].isoformat(),
            "historical_mean_kg": round(final["mean"], 4),
            "recent_ewma_kg": round(final["ewma"], 4),
            "historical_std_kg": round(final["std"], 4),
        })
        field_index[(key, field_id)].append((employee_id, stat))

    availability_rows = []
    constraint_rows = []
    for row in employee_master_rows:
        if row["activity_class"] == "INACTIVE_OVER_365_DAYS":
            continue
        availability_rows.append({
            "date": first_date.isoformat(),
            "estate": row["estate"],
            "employee_id": row["employee_id"],
            "inferred_home_division": row["inferred_home_division"],
            "available_status": "UNKNOWN",
            "leave_status": "UNKNOWN",
            "medically_fit_for_plucking": "UNKNOWN",
            "supervisor_confirmed": "NO",
            "confirmation_time": "",
            "notes": "",
        })
        constraint_rows.append({
            "estate": row["estate"],
            "employee_id": row["employee_id"],
            "inferred_home_division": row["inferred_home_division"],
            "cross_division_allowed": "UNKNOWN",
            "allowed_divisions": "",
            "prohibited_fields": "",
            "restriction_status": "UNKNOWN",
            "max_daily_assignments": 1,
            "supervisor_confirmed": "NO",
            "notes": "",
        })

    candidate_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []

    for demand_index, demand in enumerate(first_date_demand, start=1):
        estate_name = clean(demand.get("estate"))
        key = estate_key(estate_name)
        division = clean(demand.get("division")) or "UNKNOWN"
        field_id = clean(demand.get("field"))
        recommended = int(parse_float(demand.get("recommended_plucker_assignments"), 0.0) or 0)
        required_limit = min(
            max(30, int(math.ceil(recommended * 2.0))),
            max(30, args.max_candidates_per_field),
        )

        candidates: dict[str, dict[str, Any]] = {}

        for employee_id, pair_stat in field_index.get((key, field_id), []):
            emp_stat = employee_stats[(key, employee_id)]
            div_stat = employee_division_stats.get((key, employee_id, division))
            expected, conservative, source, count, last_day = candidate_expected(
                pair_stat, div_stat, emp_stat
            )
            candidates[employee_id] = {
                "scope": "FIELD_HISTORY",
                "scope_rank": 3,
                "expected": expected,
                "conservative": conservative,
                "source": source,
                "experience_count": count,
                "last_day": last_day,
            }

        for employee_id, div_stat in division_index.get((key, division), []):
            if employee_id in candidates:
                continue
            emp_stat = employee_stats[(key, employee_id)]
            expected, conservative, source, count, last_day = candidate_expected(
                None, div_stat, emp_stat
            )
            candidates[employee_id] = {
                "scope": "DIVISION_HISTORY",
                "scope_rank": 2,
                "expected": expected,
                "conservative": conservative,
                "source": source,
                "experience_count": count,
                "last_day": last_day,
            }

        for employee_id, emp_stat in estate_index.get(key, []):
            if employee_id in candidates:
                continue
            expected, conservative, source, count, last_day = candidate_expected(
                None, None, emp_stat
            )
            candidates[employee_id] = {
                "scope": "ESTATE_HISTORY",
                "scope_rank": 1,
                "expected": expected,
                "conservative": conservative,
                "source": source,
                "experience_count": count,
                "last_day": last_day,
            }

        scored: list[tuple[float, str, dict[str, Any]]] = []
        history_end = estate_history_end.get(key, first_date)
        for employee_id, candidate in candidates.items():
            master = employee_master_lookup[(key, employee_id)]
            activity = master["activity_class"]
            if activity == "INACTIVE_OVER_365_DAYS":
                activity_multiplier = 0.25
            elif activity == "RECENT_WITHIN_365_DAYS":
                activity_multiplier = 0.75
            else:
                activity_multiplier = 1.0

            recency_days = (
                max(0, (history_end - candidate["last_day"]).days)
                if candidate["last_day"] else 9999
            )
            recency_multiplier = math.exp(-min(recency_days, 730) / 180.0)
            experience_multiplier = math.log1p(candidate["experience_count"])
            scope_multiplier = {3: 1.0, 2: 0.82, 1: 0.62}[candidate["scope_rank"]]
            score = (
                candidate["conservative"]
                * experience_multiplier
                * recency_multiplier
                * activity_multiplier
                * scope_multiplier
            )
            scored.append((score, employee_id, candidate))

        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        selected = scored[:required_limit]
        exact_count = sum(1 for _, _, item in selected if item["scope"] == "FIELD_HISTORY")
        division_count = sum(1 for _, _, item in selected if item["scope"] == "DIVISION_HISTORY")
        estate_count = sum(1 for _, _, item in selected if item["scope"] == "ESTATE_HISTORY")

        for rank, (score, employee_id, candidate) in enumerate(selected, start=1):
            master = employee_master_lookup[(key, employee_id)]
            candidate_rows.append({
                "date": first_date.isoformat(),
                "estate": estate_name,
                "division": division,
                "field": field_id,
                "recommended_plucker_assignments": recommended,
                "employee_id": employee_id,
                "candidate_rank": rank,
                "candidate_scope": candidate["scope"],
                "inferred_home_division": master["inferred_home_division"],
                "activity_class": master["activity_class"],
                "experience_count": candidate["experience_count"],
                "last_experience_date": candidate["last_day"].isoformat() if candidate["last_day"] else "",
                "expected_productivity_kg": round(candidate["expected"], 4),
                "conservative_productivity_kg": round(candidate["conservative"], 4),
                "productivity_source": candidate["source"],
                "candidate_score": round(score, 6),
                "availability_status": "UNKNOWN",
                "constraint_status": "UNKNOWN",
                "eligibility_status": "BLOCKED_PENDING_CONFIRMATION",
            })

        candidate_pool = len(selected)
        coverage_rows.append({
            "date": first_date.isoformat(),
            "estate": estate_name,
            "division": division,
            "field": field_id,
            "recommended_plucker_assignments": recommended,
            "candidate_pool": candidate_pool,
            "candidate_pool_ratio": round(candidate_pool / recommended, 4) if recommended else 0.0,
            "field_history_candidates": exact_count,
            "division_history_candidates": division_count,
            "estate_history_candidates": estate_count,
            "historical_candidate_coverage_status": (
                "PASS"
                if candidate_pool >= recommended
                else "INSUFFICIENT_HISTORICAL_CANDIDATES"
            ),
            "operational_eligibility_status": "BLOCKED_PENDING_AVAILABILITY_AND_CONSTRAINTS",
        })

    availability_ids_by_estate: defaultdict[str, set[str]] = defaultdict(set)
    for row in availability_rows:
        availability_ids_by_estate[estate_key(row["estate"])].add(row["employee_id"])

    demand_by_estate: defaultdict[str, int] = defaultdict(int)
    fields_by_estate: defaultdict[str, int] = defaultdict(int)
    fields_pass_by_estate: defaultdict[str, int] = defaultdict(int)
    candidate_ids_by_estate: defaultdict[str, set[str]] = defaultdict(set)

    for row in coverage_rows:
        key = estate_key(row["estate"])
        demand_by_estate[key] += int(row["recommended_plucker_assignments"])
        fields_by_estate[key] += 1
        if row["historical_candidate_coverage_status"] == "PASS":
            fields_pass_by_estate[key] += 1

    for row in candidate_rows:
        candidate_ids_by_estate[estate_key(row["estate"])].add(row["employee_id"])

    readiness_rows = []
    for key in sorted(demand_by_estate):
        estate_name = estate_display.get(key, key)
        fields_total = fields_by_estate[key]
        fields_pass = fields_pass_by_estate[key]
        readiness_rows.append({
            "date": first_date.isoformat(),
            "estate": estate_name,
            "recommended_assignment_demand": demand_by_estate[key],
            "recent_employee_pool": len(availability_ids_by_estate.get(key, set())),
            "historical_candidate_pool": len(candidate_ids_by_estate.get(key, set())),
            "active_fields": fields_total,
            "fields_with_historical_candidate_coverage": fields_pass,
            "historical_field_coverage_pct": round(
                fields_pass / fields_total * 100, 2
            ) if fields_total else 0.0,
            "availability_confirmed_employees": 0,
            "constraints_confirmed_employees": 0,
            "eligible_employee_pool": 0,
            "cp_sat_readiness": "NOT_READY_AVAILABILITY_AND_CONSTRAINTS_REQUIRED",
            "cp_sat_started": "FALSE",
        })

    employee_master_count = write_csv(
        registers_dir / "employee_master.csv",
        employee_master_rows,
        [
            "estate", "employee_id", "inferred_home_division",
            "home_division_source", "first_observed_date", "last_observed_date",
            "days_since_last_observed", "activity_class", "observation_count",
            "distinct_fields", "distinct_divisions", "historical_mean_kg",
            "recent_ewma_kg", "historical_std_kg",
            "productivity_model_policy", "estate_model_status",
            "allocation_status",
        ],
    )
    field_experience_count = write_csv(
        registers_dir / "employee_field_experience.csv",
        field_experience_rows,
        [
            "estate", "employee_id", "field_id", "field_division",
            "observation_count", "first_observed_date", "last_observed_date",
            "historical_mean_kg", "recent_ewma_kg", "historical_std_kg",
        ],
    )
    availability_count = write_csv(
        templates_dir / "employee_availability_template.csv",
        availability_rows,
        [
            "date", "estate", "employee_id", "inferred_home_division",
            "available_status", "leave_status", "medically_fit_for_plucking",
            "supervisor_confirmed", "confirmation_time", "notes",
        ],
    )
    constraint_count = write_csv(
        templates_dir / "employee_constraints_template.csv",
        constraint_rows,
        [
            "estate", "employee_id", "inferred_home_division",
            "cross_division_allowed", "allowed_divisions",
            "prohibited_fields", "restriction_status",
            "max_daily_assignments", "supervisor_confirmed", "notes",
        ],
    )
    candidate_count = write_csv(
        candidates_dir / "first_date_field_employee_candidate_matrix.csv",
        candidate_rows,
        [
            "date", "estate", "division", "field",
            "recommended_plucker_assignments", "employee_id",
            "candidate_rank", "candidate_scope", "inferred_home_division",
            "activity_class", "experience_count", "last_experience_date",
            "expected_productivity_kg", "conservative_productivity_kg",
            "productivity_source", "candidate_score",
            "availability_status", "constraint_status", "eligibility_status",
        ],
    )
    write_csv(
        quality_dir / "field_candidate_coverage.csv",
        coverage_rows,
        [
            "date", "estate", "division", "field",
            "recommended_plucker_assignments", "candidate_pool",
            "candidate_pool_ratio", "field_history_candidates",
            "division_history_candidates", "estate_history_candidates",
            "historical_candidate_coverage_status",
            "operational_eligibility_status",
        ],
    )
    write_csv(
        quality_dir / "cp_sat_readiness_gate.csv",
        readiness_rows,
        [
            "date", "estate", "recommended_assignment_demand",
            "recent_employee_pool", "historical_candidate_pool",
            "active_fields", "fields_with_historical_candidate_coverage",
            "historical_field_coverage_pct",
            "availability_confirmed_employees",
            "constraints_confirmed_employees", "eligible_employee_pool",
            "cp_sat_readiness", "cp_sat_started",
        ],
    )
    write_csv(
        quality_dir / "estate_productivity_clipping_register.csv",
        estate_clip_register,
        [
            "estate", "sample_values", "lower_clip_kg", "upper_clip_kg",
            "source_rows", "clipped_low_rows", "clipped_high_rows",
        ],
    )

    historical_coverage_failures = sum(
        1 for row in coverage_rows
        if row["historical_candidate_coverage_status"] != "PASS"
    )
    duration_minutes = round((time.time() - started) / 60.0, 2)
    summary = {
        "status": (
            "PASS_EMPLOYEE_READINESS_INPUTS_CREATED"
            if historical_coverage_failures == 0
            else "PASS_WITH_HISTORICAL_CANDIDATE_GAPS"
        ),
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "productivity_run": str(productivity_run),
        "planning_run": str(planning_run),
        "planning_date": first_date.isoformat(),
        "training_files": len(training_files),
        "source_rows": source_rows,
        "retained_rows": retained_rows,
        "invalid_rows": invalid_rows,
        "employee_master_rows": employee_master_count,
        "employee_field_experience_rows": field_experience_count,
        "availability_template_rows": availability_count,
        "constraint_template_rows": constraint_count,
        "candidate_matrix_rows": candidate_count,
        "active_field_demand_rows_first_date": len(first_date_demand),
        "historical_candidate_coverage_failures": historical_coverage_failures,
        "cp_sat_readiness": "NOT_READY_AVAILABILITY_AND_CONSTRAINTS_REQUIRED",
        "operational_status": TECHNICAL_STATUS,
        "cp_sat_started": False,
        "rl_started": False,
        "important_interpretation": [
            "Employee IDs, field history and productivity are derived from all 33 compressed productivity training files.",
            "Home division is inferred from the modal observed field division when source home_division is unknown.",
            "The candidate matrix is a historical suitability matrix, not a named employee allocation.",
            "Availability, leave, medical fitness and movement constraints remain UNKNOWN until confirmed by estate management.",
            "CP-SAT must not start until the edited templates pass the input recheck.",
        ],
    }
    (run_folder / "run_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    (run_folder / "README.txt").write_text(
        "\n".join([
            "TTE EMPLOYEE READINESS LAYER v6.0.0",
            "",
            f"Planning date: {first_date.isoformat()}",
            "",
            "1. Open templates\\employee_availability_template.csv",
            "2. Confirm available_status, leave_status, medically_fit_for_plucking and supervisor_confirmed.",
            "3. Open templates\\employee_constraints_template.csv",
            "4. Confirm cross_division_allowed, allowed_divisions, prohibited_fields, restriction_status and supervisor_confirmed.",
            "5. Run RECHECK_EMPLOYEE_INPUT_READINESS_v6.0.0.ps1.",
            "",
            "No CP-SAT allocation or RL policy has been started.",
        ]) + "\n",
        encoding="utf-8",
    )
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "LATEST_EMPLOYEE_READINESS_RUN.txt").write_text(
        str(run_folder), encoding="utf-8"
    )

    print("")
    print("EMPLOYEE READINESS INPUT BUILD FINISHED")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
