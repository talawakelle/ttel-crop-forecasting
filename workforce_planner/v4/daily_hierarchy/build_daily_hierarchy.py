from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import statistics
import time
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable

try:
    import openpyxl
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: openpyxl. Install it with: py -m pip install openpyxl"
    ) from exc


PACKAGE_VERSION = "4.0.0"
REQUIRED_COLUMNS = {
    "date",
    "employee_id",
    "net_weight",
    "field_code",
    "division_name",
    "type",
}
CANDIDATE_METHODS = (
    "RECENT_SAME_WEEKDAY_MEDIAN",
    "RECENT_28_OPERATING_MEDIAN",
    "SEASONAL_364_DAY_MEDIAN",
    "BLENDED_RECENT_SEASONAL",
)


def txt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def normalize_header(value: Any) -> str:
    return "_".join(txt(value).lower().split())


def estate_key(value: str) -> str:
    stem = Path(value).stem
    for suffix in ("_output", "-output", " output"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return "".join(ch for ch in stem.lower() if ch.isalnum())


def estate_display(value: str) -> str:
    stem = Path(value).stem
    for suffix in ("_output", "-output", " output"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return stem.strip()


def parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = txt(value)
    if not raw:
        return None
    for fmt in (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(raw.replace("T", " ")).date()
    except ValueError:
        return None


def parse_float(value: Any) -> float | None:
    try:
        result = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


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


def median_or_none(values: Iterable[float]) -> float | None:
    cleaned = [float(value) for value in values if value is not None and value >= 0]
    return statistics.median(cleaned) if cleaned else None


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def open_gzip_writer(path: Path, fieldnames: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = gzip.open(path, "wt", newline="", encoding="utf-8")
    writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    return handle, writer


def load_identity_registry(path: Path) -> dict[str, str]:
    registry: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            registry[estate_key(row["archive_estate"])] = txt(row["estate_id"])
    return registry


def load_audit_gate(audit_root: Path) -> tuple[Path, dict[str, Any], dict[str, dict[str, str]]]:
    pointer = audit_root / "LATEST_DATA_AUDIT.txt"
    if not pointer.exists():
        raise RuntimeError(
            f"Latest audit pointer is missing: {pointer}. "
            "Run the corrected v3.0.1 data audit first."
        )
    run_folder = Path(pointer.read_text(encoding="utf-8").strip())
    summary_path = run_folder / "audit_summary.json"
    estate_path = run_folder / "estate_data_audit.csv"
    if not summary_path.exists() or not estate_path.exists():
        raise RuntimeError(f"Audit outputs are incomplete: {run_folder}")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if str(summary.get("package_version")) != "3.0.1":
        raise RuntimeError(
            f"Expected audit package v3.0.1, found {summary.get('package_version')}"
        )
    if int(summary.get("archives_found", 0)) != int(summary.get("expected_estates", 33)):
        raise RuntimeError("Audit archive gate is incomplete.")
    if int(summary.get("not_ready", 0)) != 0:
        raise RuntimeError("One or more estates are NOT_READY in the data audit.")

    rows: dict[str, dict[str, str]] = {}
    with estate_path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            rows[estate_key(row["estate"])] = row
    return run_folder, summary, rows


def verify_identity_gate(
    audit_rows: dict[str, dict[str, str]],
    registry: dict[str, str],
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for key, row in sorted(audit_rows.items()):
        status = row.get("readiness_status", "")
        mismatch_count = int(row.get("identity_mismatch_count", 0) or 0)
        estate_ids = {part.strip() for part in row.get("estate_ids", "").split("|") if part.strip()}
        registry_id = registry.get(key, "")

        if status == "READY":
            resolution = "AUDIT_READY"
        elif status == "CONDITIONAL" and mismatch_count > 0:
            if not registry_id:
                raise RuntimeError(
                    f"Conditional estate {row['estate']} is missing from the verified identity registry."
                )
            if registry_id not in estate_ids:
                raise RuntimeError(
                    f"Identity registry mismatch for {row['estate']}: "
                    f"expected estate_id {registry_id}, audit found {sorted(estate_ids)}"
                )
            resolution = "VERIFIED_FILENAME_ONLY_MISMATCH"
        else:
            raise RuntimeError(
                f"Estate {row['estate']} did not pass the identity gate: {status}"
            )

        results.append({
            "estate": row["estate"],
            "audit_status": status,
            "identity_resolution": resolution,
            "estate_ids": row.get("estate_ids", ""),
            "registry_estate_id": registry_id,
            "identity_mismatch_count": str(mismatch_count),
        })
    return results


def scan_estate_archive(
    archive_path: Path,
) -> tuple[
    dict[tuple[date, str, str], list[Any]],
    dict[str, Any],
]:
    archive_name = archive_path.name
    display_name = estate_display(archive_name)
    daily: dict[tuple[date, str, str], list[Any]] = {}
    seen_weighing_ids: set[str] = set()
    workbook_count = 0
    rows_scanned = 0
    plucking_rows = 0
    duplicate_rows = 0
    invalid_rows = 0
    estate_ids: set[str] = set()
    source_workbooks: list[str] = []

    with zipfile.ZipFile(archive_path) as archive:
        workbooks = sorted(
            name for name in archive.namelist()
            if not name.endswith("/") and name.lower().endswith((".xlsx", ".xlsm"))
        )
        if not workbooks:
            raise RuntimeError(f"No Excel workbooks found inside {archive_name}")

        for workbook_name in workbooks:
            workbook_count += 1
            source_workbooks.append(workbook_name)
            workbook = openpyxl.load_workbook(
                BytesIO(archive.read(workbook_name)),
                read_only=True,
                data_only=True,
            )
            try:
                if "All Records" not in workbook.sheetnames:
                    raise RuntimeError(
                        f"{archive_name}/{workbook_name} is missing the All Records sheet"
                    )
                sheet = workbook["All Records"]
                iterator = sheet.iter_rows(values_only=True)
                headers = [normalize_header(value) for value in next(iterator, ())]
                positions = {header: index for index, header in enumerate(headers) if header}
                missing = sorted(REQUIRED_COLUMNS.difference(positions))
                if missing:
                    raise RuntimeError(
                        f"{archive_name}/{workbook_name} missing columns: {', '.join(missing)}"
                    )

                def get(row: tuple[Any, ...], name: str) -> Any:
                    index = positions.get(name)
                    return row[index] if index is not None and index < len(row) else None

                for row in iterator:
                    rows_scanned += 1
                    if "PLUCK" not in txt(get(row, "type")).upper():
                        continue
                    plucking_rows += 1

                    weighing_id = txt(get(row, "weighing_id"))
                    if weighing_id:
                        if weighing_id in seen_weighing_ids:
                            duplicate_rows += 1
                            continue
                        seen_weighing_ids.add(weighing_id)

                    row_date = parse_date(get(row, "date"))
                    kilos = parse_float(get(row, "net_weight"))
                    employee = txt(get(row, "employee_id"))
                    division = txt(get(row, "division_name"))
                    field_code = txt(get(row, "field_code"))
                    estate_id = txt(get(row, "estate_id"))

                    if (
                        row_date is None
                        or kilos is None
                        or kilos <= 0
                        or not employee
                        or not division
                        or not field_code
                    ):
                        invalid_rows += 1
                        continue

                    if estate_id:
                        estate_ids.add(estate_id)

                    key = (row_date, division, field_code)
                    if key not in daily:
                        daily[key] = [0.0, set(), 0]
                    daily[key][0] += kilos
                    daily[key][1].add(employee)
                    daily[key][2] += 1
            finally:
                workbook.close()

    if not daily:
        raise RuntimeError(f"No valid daily field crop rows were produced for {archive_name}")

    profile = {
        "estate": display_name,
        "archive_name": archive_name,
        "workbook_count": workbook_count,
        "rows_scanned": rows_scanned,
        "plucking_rows": plucking_rows,
        "duplicate_weighing_rows": duplicate_rows,
        "invalid_rows": invalid_rows,
        "estate_ids": "|".join(sorted(estate_ids)),
        "source_workbooks": "|".join(source_workbooks),
    }
    return daily, profile


def build_level_rows(
    estate: str,
    daily_field: dict[tuple[date, str, str], list[Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    field_rows: list[dict[str, Any]] = []
    division_map: dict[tuple[date, str], list[Any]] = {}
    estate_map: dict[date, list[Any]] = {}

    for (row_date, division, field_code), values in sorted(daily_field.items()):
        kilos, employees, weighing_rows = values
        field_rows.append({
            "date": row_date.isoformat(),
            "estate": estate,
            "division": division,
            "field": field_code,
            "green_leaf_kg": round(kilos, 4),
            "plucker_count": len(employees),
            "weighing_rows": weighing_rows,
            "observation_status": "OBSERVED_PLUCKING",
        })

        dkey = (row_date, division)
        if dkey not in division_map:
            division_map[dkey] = [0.0, set(), set()]
        division_map[dkey][0] += kilos
        division_map[dkey][1].update(employees)
        division_map[dkey][2].add(field_code)

        if row_date not in estate_map:
            estate_map[row_date] = [0.0, set(), set(), set()]
        estate_map[row_date][0] += kilos
        estate_map[row_date][1].update(employees)
        estate_map[row_date][2].add((division, field_code))
        estate_map[row_date][3].add(division)

    division_rows = [
        {
            "date": row_date.isoformat(),
            "estate": estate,
            "division": division,
            "green_leaf_kg": round(values[0], 4),
            "plucker_count": len(values[1]),
            "active_field_count": len(values[2]),
            "observation_status": "OBSERVED_PLUCKING",
        }
        for (row_date, division), values in sorted(division_map.items())
    ]

    estate_rows = [
        {
            "date": row_date.isoformat(),
            "estate": estate,
            "green_leaf_kg": round(values[0], 4),
            "plucker_count": len(values[1]),
            "active_field_count": len(values[2]),
            "active_division_count": len(values[3]),
            "observation_status": "OBSERVED_PLUCKING",
        }
        for row_date, values in sorted(estate_map.items())
    ]
    return field_rows, division_rows, estate_rows


def value_before(
    series: dict[date, float],
    target: date,
    method: str,
) -> float | None:
    historical_dates = [day for day in series if day < target]
    if not historical_dates:
        return None

    if method == "RECENT_SAME_WEEKDAY_MEDIAN":
        candidates = sorted(
            (
                day for day in historical_dates
                if day.weekday() == target.weekday()
            ),
            reverse=True,
        )[:8]
        return median_or_none(series[day] for day in candidates)

    if method == "RECENT_28_OPERATING_MEDIAN":
        cutoff = target - timedelta(days=35)
        candidates = [
            series[day] for day in historical_dates
            if cutoff <= day < target
        ]
        if len(candidates) < 5:
            candidates = [series[day] for day in sorted(historical_dates)[-20:]]
        return median_or_none(candidates)

    if method == "SEASONAL_364_DAY_MEDIAN":
        candidates: list[float] = []
        for years_back in (1, 2, 3, 4):
            anchor = target - timedelta(days=364 * years_back)
            for offset in (-14, -7, 0, 7, 14):
                day = anchor + timedelta(days=offset)
                if day < target and day in series and day.weekday() == target.weekday():
                    candidates.append(series[day])
        return median_or_none(candidates)

    if method == "BLENDED_RECENT_SEASONAL":
        recent = value_before(series, target, "RECENT_SAME_WEEKDAY_MEDIAN")
        seasonal = value_before(series, target, "SEASONAL_364_DAY_MEDIAN")
        if recent is not None and seasonal is not None:
            return 0.65 * recent + 0.35 * seasonal
        return recent if recent is not None else seasonal

    raise ValueError(f"Unknown method: {method}")


def backtest_estate(
    estate: str,
    series: dict[date, float],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[float]]:
    ordered_dates = sorted(series)
    if len(ordered_dates) < 80:
        raise RuntimeError(f"{estate} has too few observed crop days for backtesting")

    holdout_count = min(120, max(45, len(ordered_dates) // 8))
    test_dates = ordered_dates[-holdout_count:]
    metrics: list[dict[str, Any]] = []
    residuals_by_method: dict[str, list[float]] = {}

    for method in CANDIDATE_METHODS:
        absolute_error = 0.0
        actual_sum = 0.0
        squared_error = 0.0
        residuals: list[float] = []
        predictions = 0

        for target in test_dates:
            prediction = value_before(series, target, method)
            if prediction is None:
                continue
            actual = series[target]
            error = actual - prediction
            absolute_error += abs(error)
            squared_error += error * error
            actual_sum += actual
            residuals.append(error)
            predictions += 1

        if predictions == 0 or actual_sum <= 0:
            wape = float("inf")
            mae = float("inf")
            rmse = float("inf")
        else:
            wape = absolute_error / actual_sum * 100
            mae = absolute_error / predictions
            rmse = math.sqrt(squared_error / predictions)

        metrics.append({
            "estate": estate,
            "method": method,
            "test_observed_days": predictions,
            "mae_kg": round(mae, 4) if math.isfinite(mae) else "",
            "rmse_kg": round(rmse, 4) if math.isfinite(rmse) else "",
            "wape_pct": round(wape, 4) if math.isfinite(wape) else "",
            "test_start": test_dates[0].isoformat(),
            "test_end": test_dates[-1].isoformat(),
        })
        residuals_by_method[method] = residuals

    valid_metrics = [row for row in metrics if row["wape_pct"] != ""]
    if not valid_metrics:
        raise RuntimeError(f"No valid daily candidate backtest was produced for {estate}")
    selected = min(valid_metrics, key=lambda row: float(row["wape_pct"]))
    selected_method = selected["method"]
    selected_record = {
        "estate": estate,
        "selected_method": selected_method,
        "test_observed_days": selected["test_observed_days"],
        "selected_mae_kg": selected["mae_kg"],
        "selected_rmse_kg": selected["rmse_kg"],
        "selected_wape_pct": selected["wape_pct"],
        "selection_rule": "LOWEST_WAPE_ON_CHRONOLOGICAL_OBSERVED_DAY_HOLDOUT",
        "model_status": "DEVELOPMENT_CANDIDATE",
    }
    return metrics, selected_record, residuals_by_method[selected_method]


def operation_probability(series: dict[date, float], target: date) -> float:
    if not series:
        return 0.0
    last_actual = max(series)
    window_start = last_actual - timedelta(days=111)
    occurrences = [
        window_start + timedelta(days=offset)
        for offset in range((last_actual - window_start).days + 1)
        if (window_start + timedelta(days=offset)).weekday() == target.weekday()
    ]
    if not occurrences:
        return 0.0
    return sum(1 for day in occurrences if day in series) / len(occurrences)


def share_maps(
    field_rows: list[dict[str, Any]],
    history_end: date,
) -> tuple[
    dict[str, float],
    dict[tuple[int, int], dict[str, float]],
    dict[str, dict[str, float]],
    dict[tuple[str, int, int], dict[str, float]],
]:
    recent_start = history_end - timedelta(days=365)

    division_global_kg: defaultdict[str, float] = defaultdict(float)
    division_specific_kg: defaultdict[tuple[int, int], defaultdict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    field_global_kg: defaultdict[str, defaultdict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    field_specific_kg: defaultdict[
        tuple[str, int, int], defaultdict[str, float]
    ] = defaultdict(lambda: defaultdict(float))

    for row in field_rows:
        row_date = date.fromisoformat(row["date"])
        kilos = float(row["green_leaf_kg"])
        division = row["division"]
        field_code = row["field"]

        if row_date >= recent_start:
            division_global_kg[division] += kilos
            field_global_kg[division][field_code] += kilos

        division_specific_kg[(row_date.month, row_date.weekday())][division] += kilos
        field_specific_kg[
            (division, row_date.month, row_date.weekday())
        ][field_code] += kilos

    def normalize(values: dict[str, float]) -> dict[str, float]:
        total = sum(values.values())
        if total <= 0:
            return {}
        return {key: value / total for key, value in values.items()}

    division_global = normalize(dict(division_global_kg))
    division_specific = {
        key: normalize(dict(values))
        for key, values in division_specific_kg.items()
    }
    field_global = {
        division: normalize(dict(values))
        for division, values in field_global_kg.items()
    }
    field_specific = {
        key: normalize(dict(values))
        for key, values in field_specific_kg.items()
    }
    return division_global, division_specific, field_global, field_specific


def blend_shares(
    global_shares: dict[str, float],
    specific_shares: dict[str, float],
    specific_weight: float = 0.65,
) -> dict[str, float]:
    keys = sorted(set(global_shares) | set(specific_shares))
    if not keys:
        return {}
    blended = {
        key: (1 - specific_weight) * global_shares.get(key, 0.0)
        + specific_weight * specific_shares.get(key, 0.0)
        for key in keys
    }
    total = sum(blended.values())
    if total <= 0:
        equal = 1.0 / len(keys)
        return {key: equal for key in keys}
    return {key: value / total for key, value in blended.items()}


def allocate_exact(total: float, shares: dict[str, float]) -> dict[str, float]:
    if not shares:
        return {}
    keys = sorted(shares)
    allocations = {key: round(total * shares[key], 4) for key in keys}
    difference = round(total - sum(allocations.values()), 4)
    if abs(difference) > 0:
        largest = max(keys, key=lambda key: shares[key])
        allocations[largest] = round(allocations[largest] + difference, 4)
    return allocations


def forecast_estate(
    estate: str,
    series: dict[date, float],
    field_rows: list[dict[str, Any]],
    selected: dict[str, Any],
    residuals: list[float],
    forecast_start: date,
    forecast_days: int,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    selected_method = selected["selected_method"]
    history_end = max(series)
    data_age_days = (forecast_start - history_end).days
    q10 = quantile(residuals, 0.10)
    q90 = quantile(residuals, 0.90)

    division_global, division_specific, field_global, field_specific = share_maps(
        field_rows, history_end
    )

    estate_forecasts: list[dict[str, Any]] = []
    division_forecasts: list[dict[str, Any]] = []
    field_forecasts: list[dict[str, Any]] = []
    reconciliation: list[dict[str, Any]] = []

    for offset in range(forecast_days):
        target = forecast_start + timedelta(days=offset)
        conditional = value_before(series, target, selected_method)
        if conditional is None:
            conditional = median_or_none(series.values()) or 0.0

        op_probability = operation_probability(series, target)
        planned_operating = op_probability >= 0.50
        planning_crop = conditional if planned_operating else 0.0
        expected_crop = conditional * op_probability
        lower = max(0.0, conditional + q10) if planned_operating else 0.0
        upper = max(lower, conditional + q90) if planned_operating else 0.0

        freshness_status = (
            "CURRENT_SOURCE" if data_age_days <= 14
            else "STALE_SOURCE_REFRESH_REQUIRED"
        )
        estate_row = {
            "date": target.isoformat(),
            "estate": estate,
            "forecast_origin_data_date": history_end.isoformat(),
            "data_age_days_at_forecast_start": data_age_days,
            "data_freshness_status": freshness_status,
            "selected_method": selected_method,
            "operating_day_probability": round(op_probability, 4),
            "planned_operating_day": str(planned_operating).upper(),
            "conditional_crop_if_operating_kg": round(conditional, 4),
            "expected_daily_crop_kg": round(expected_crop, 4),
            "planning_crop_kg": round(planning_crop, 4),
            "lower_80_planning_kg": round(lower, 4),
            "upper_80_planning_kg": round(upper, 4),
            "forecast_status": "DEVELOPMENT_CANDIDATE_NOT_LIVE",
        }
        estate_forecasts.append(estate_row)

        d_specific = division_specific.get((target.month, target.weekday()), {})
        d_shares = blend_shares(division_global, d_specific)
        division_allocations = allocate_exact(planning_crop, d_shares)

        field_sum_total = 0.0
        for division, division_crop in division_allocations.items():
            division_forecasts.append({
                "date": target.isoformat(),
                "estate": estate,
                "division": division,
                "planning_crop_kg": division_crop,
                "share_of_estate": round(d_shares.get(division, 0.0), 8),
                "allocation_method": "SMOOTHED_MONTH_WEEKDAY_HISTORICAL_SHARE",
                "forecast_status": "DEVELOPMENT_CANDIDATE_NOT_LIVE",
            })

            f_specific = field_specific.get(
                (division, target.month, target.weekday()), {}
            )
            f_shares = blend_shares(field_global.get(division, {}), f_specific)
            field_allocations = allocate_exact(division_crop, f_shares)
            field_sum = sum(field_allocations.values())
            field_sum_total += field_sum

            for field_code, field_crop in field_allocations.items():
                field_forecasts.append({
                    "date": target.isoformat(),
                    "estate": estate,
                    "division": division,
                    "field": field_code,
                    "planning_crop_kg": field_crop,
                    "share_of_division": round(f_shares.get(field_code, 0.0), 8),
                    "allocation_method": "SMOOTHED_MONTH_WEEKDAY_HISTORICAL_SHARE",
                    "forecast_status": "DEVELOPMENT_CANDIDATE_NOT_LIVE",
                })

        division_sum = sum(division_allocations.values())
        reconciliation.append({
            "date": target.isoformat(),
            "estate": estate,
            "estate_planning_crop_kg": round(planning_crop, 4),
            "division_sum_kg": round(division_sum, 4),
            "field_sum_kg": round(field_sum_total, 4),
            "estate_minus_division_kg": round(planning_crop - division_sum, 6),
            "estate_minus_field_kg": round(planning_crop - field_sum_total, 6),
            "reconciliation_status": (
                "PASS"
                if abs(planning_crop - division_sum) <= 0.01
                and abs(planning_crop - field_sum_total) <= 0.01
                else "FAIL"
            ),
        })

    return estate_forecasts, division_forecasts, field_forecasts, reconciliation


def main() -> int:
    parser = argparse.ArgumentParser(
        description="TTE all-estate daily hierarchy development candidate."
    )
    parser.add_argument("--crop-root", required=True)
    parser.add_argument("--audit-root", required=True)
    parser.add_argument("--identity-registry", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--expected-estates", type=int, default=33)
    parser.add_argument("--forecast-days", type=int, default=28)
    parser.add_argument("--forecast-start", default="")
    args = parser.parse_args()

    crop_root = Path(args.crop_root).expanduser().resolve()
    audit_root = Path(args.audit_root).expanduser().resolve()
    registry_path = Path(args.identity_registry).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()

    forecast_start = (
        datetime.strptime(args.forecast_start, "%Y-%m-%d").date()
        if args.forecast_start
        else date.today() + timedelta(days=1)
    )
    if args.forecast_days < 7 or args.forecast_days > 90:
        raise SystemExit("forecast-days must be between 7 and 90")

    audit_run, audit_summary, audit_rows = load_audit_gate(audit_root)
    registry = load_identity_registry(registry_path)
    identity_results = verify_identity_gate(audit_rows, registry)

    archives = sorted(crop_root.glob("*.zip"), key=lambda path: estate_key(path.name))
    if len(archives) != args.expected_estates:
        raise RuntimeError(
            f"Expected {args.expected_estates} estate ZIP archives, found {len(archives)}"
        )

    run_folder = output_root / datetime.now().strftime(
        "daily_hierarchy_candidate_%Y%m%d_%H%M%S"
    )
    historical_dir = run_folder / "historical"
    forecast_dir = run_folder / "forecast"
    backtest_dir = run_folder / "backtest"
    profile_dir = run_folder / "profiles"
    for folder in (historical_dir, forecast_dir, backtest_dir, profile_dir):
        folder.mkdir(parents=True, exist_ok=True)

    print(f"Daily hierarchy run folder: {run_folder}")
    print(f"Audit gate: {audit_run}")
    print(f"Forecast start: {forecast_start}")
    print(f"Forecast days: {args.forecast_days}")
    print("This is a development candidate. No live portal or allocator will change.")

    field_history_fields = [
        "date", "estate", "division", "field", "green_leaf_kg",
        "plucker_count", "weighing_rows", "observation_status",
    ]
    division_history_fields = [
        "date", "estate", "division", "green_leaf_kg", "plucker_count",
        "active_field_count", "observation_status",
    ]
    estate_history_fields = [
        "date", "estate", "green_leaf_kg", "plucker_count",
        "active_field_count", "active_division_count", "observation_status",
    ]
    estate_forecast_fields = [
        "date", "estate", "forecast_origin_data_date",
        "data_age_days_at_forecast_start", "data_freshness_status",
        "selected_method", "operating_day_probability",
        "planned_operating_day", "conditional_crop_if_operating_kg",
        "expected_daily_crop_kg", "planning_crop_kg",
        "lower_80_planning_kg", "upper_80_planning_kg", "forecast_status",
    ]
    division_forecast_fields = [
        "date", "estate", "division", "planning_crop_kg",
        "share_of_estate", "allocation_method", "forecast_status",
    ]
    field_forecast_fields = [
        "date", "estate", "division", "field", "planning_crop_kg",
        "share_of_division", "allocation_method", "forecast_status",
    ]
    metric_fields = [
        "estate", "method", "test_observed_days", "mae_kg", "rmse_kg",
        "wape_pct", "test_start", "test_end",
    ]
    selected_fields = [
        "estate", "selected_method", "test_observed_days", "selected_mae_kg",
        "selected_rmse_kg", "selected_wape_pct", "selection_rule", "model_status",
    ]
    reconciliation_fields = [
        "date", "estate", "estate_planning_crop_kg", "division_sum_kg",
        "field_sum_kg", "estate_minus_division_kg", "estate_minus_field_kg",
        "reconciliation_status",
    ]

    field_handle, field_writer = open_gzip_writer(
        historical_dir / "field_daily.csv.gz", field_history_fields
    )
    division_handle, division_writer = open_gzip_writer(
        historical_dir / "division_daily.csv.gz", division_history_fields
    )
    estate_handle, estate_writer = open_gzip_writer(
        historical_dir / "estate_daily.csv.gz", estate_history_fields
    )

    all_metrics: list[dict[str, Any]] = []
    selected_models: list[dict[str, Any]] = []
    estate_forecasts_all: list[dict[str, Any]] = []
    division_forecasts_all: list[dict[str, Any]] = []
    field_forecasts_all: list[dict[str, Any]] = []
    reconciliation_all: list[dict[str, Any]] = []
    profiles: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    started = time.time()

    try:
        for index, archive_path in enumerate(archives, start=1):
            print(f"[{index}/{len(archives)}] Building {archive_path.name}", flush=True)
            try:
                daily_field, scan_profile = scan_estate_archive(archive_path)
                estate = scan_profile["estate"]
                field_rows, division_rows, estate_rows = build_level_rows(
                    estate, daily_field
                )

                for row in field_rows:
                    field_writer.writerow(row)
                for row in division_rows:
                    division_writer.writerow(row)
                for row in estate_rows:
                    estate_writer.writerow(row)

                estate_series = {
                    date.fromisoformat(row["date"]): float(row["green_leaf_kg"])
                    for row in estate_rows
                }
                metrics, selected, residuals = backtest_estate(
                    estate, estate_series
                )
                all_metrics.extend(metrics)
                selected_models.append(selected)

                estate_fc, division_fc, field_fc, reconciliation = forecast_estate(
                    estate=estate,
                    series=estate_series,
                    field_rows=field_rows,
                    selected=selected,
                    residuals=residuals,
                    forecast_start=forecast_start,
                    forecast_days=args.forecast_days,
                )
                estate_forecasts_all.extend(estate_fc)
                division_forecasts_all.extend(division_fc)
                field_forecasts_all.extend(field_fc)
                reconciliation_all.extend(reconciliation)

                profile = {
                    **scan_profile,
                    "historical_date_min": min(estate_series).isoformat(),
                    "historical_date_max": max(estate_series).isoformat(),
                    "historical_observed_days": len(estate_series),
                    "division_count": len({row["division"] for row in field_rows}),
                    "field_count": len(
                        {(row["division"], row["field"]) for row in field_rows}
                    ),
                    "historical_field_day_rows": len(field_rows),
                    "historical_division_day_rows": len(division_rows),
                    "historical_estate_day_rows": len(estate_rows),
                    "selected_method": selected["selected_method"],
                    "selected_wape_pct": selected["selected_wape_pct"],
                    "forecast_start": forecast_start.isoformat(),
                    "forecast_end": (
                        forecast_start + timedelta(days=args.forecast_days - 1)
                    ).isoformat(),
                    "data_age_days": (forecast_start - max(estate_series)).days,
                    "data_freshness_status": (
                        "CURRENT_SOURCE"
                        if (forecast_start - max(estate_series)).days <= 14
                        else "STALE_SOURCE_REFRESH_REQUIRED"
                    ),
                }
                profiles.append(profile)
            except Exception as exc:
                failures.append({
                    "estate_archive": archive_path.name,
                    "error": f"{type(exc).__name__}: {exc}",
                })
                print(f"FAILED {archive_path.name}: {type(exc).__name__}: {exc}")
    finally:
        field_handle.close()
        division_handle.close()
        estate_handle.close()

    write_csv(backtest_dir / "estate_candidate_metrics.csv", all_metrics, metric_fields)
    write_csv(backtest_dir / "estate_selected_models.csv", selected_models, selected_fields)
    write_csv(
        forecast_dir / "estate_daily_forecast.csv",
        estate_forecasts_all,
        estate_forecast_fields,
    )
    write_csv(
        forecast_dir / "division_daily_forecast.csv",
        division_forecasts_all,
        division_forecast_fields,
    )
    write_csv(
        forecast_dir / "field_daily_forecast.csv",
        field_forecasts_all,
        field_forecast_fields,
    )
    write_csv(
        run_folder / "hierarchy_reconciliation_audit.csv",
        reconciliation_all,
        reconciliation_fields,
    )

    profile_fields = sorted(
        {key for row in profiles for key in row.keys()}
    ) if profiles else ["estate"]
    write_csv(profile_dir / "estate_hierarchy_profile.csv", profiles, profile_fields)
    write_csv(
        profile_dir / "identity_gate_resolution.csv",
        identity_results,
        [
            "estate", "audit_status", "identity_resolution", "estate_ids",
            "registry_estate_id", "identity_mismatch_count",
        ],
    )
    write_csv(
        run_folder / "failures.csv",
        failures,
        ["estate_archive", "error"],
    )

    reconciliation_failures = sum(
        1 for row in reconciliation_all
        if row["reconciliation_status"] != "PASS"
    )
    stale_estates = sorted(
        row["estate"] for row in profiles
        if row["data_freshness_status"] != "CURRENT_SOURCE"
    )
    processed = len(profiles)
    duration_minutes = round((time.time() - started) / 60, 2)

    summary = {
        "status": (
            "PASS_CANDIDATE"
            if processed == args.expected_estates
            and not failures
            and reconciliation_failures == 0
            else "FAIL"
        ),
        "package_version": PACKAGE_VERSION,
        "run_folder": str(run_folder),
        "audit_run": str(audit_run),
        "archives_expected": args.expected_estates,
        "estates_processed": processed,
        "estates_failed": len(failures),
        "selected_models": len(selected_models),
        "forecast_start": forecast_start.isoformat(),
        "forecast_days": args.forecast_days,
        "estate_forecast_rows": len(estate_forecasts_all),
        "division_forecast_rows": len(division_forecasts_all),
        "field_forecast_rows": len(field_forecasts_all),
        "reconciliation_failures": reconciliation_failures,
        "stale_source_estates": stale_estates,
        "operational_status": (
            "DEVELOPMENT_ONLY_REFRESH_SOURCE_DATA_BEFORE_OPERATIONAL_USE"
            if stale_estates
            else "DEVELOPMENT_CANDIDATE_READY_FOR_REVIEW"
        ),
        "duration_minutes": duration_minutes,
        "live_models_changed": False,
        "portal_changed": False,
        "allocator_changed": False,
        "rl_started": False,
        "limitations": [
            "Estate daily candidates are selected on observed plucking-day chronological holdouts.",
            "Missing dates are not automatically treated as zero crop.",
            "Division and field forecasts are reconciled historical-share baselines, not independent field ML models.",
            "An approved operating calendar is required before live workforce demand calculation.",
            "Refresh estate source data before operational use when freshness is stale.",
        ],
    }
    (run_folder / "run_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    report = [
        "# TTE Daily Estate–Division–Field Hierarchy Candidate",
        "",
        f"- Package: {PACKAGE_VERSION}",
        f"- Estates processed: **{processed} / {args.expected_estates}**",
        f"- Forecast period: **{forecast_start} to "
        f"{forecast_start + timedelta(days=args.forecast_days - 1)}**",
        f"- Reconciliation failures: **{reconciliation_failures}**",
        f"- Stale-source estates: **{len(stale_estates)}**",
        "",
        "## Interpretation",
        "",
        "This is a development candidate. Estate-level daily methods were compared "
        "using chronological observed-plucking-day holdouts. Division and field "
        "values are reconciled historical-share baselines.",
        "",
        "WAPE, MAE and RMSE are error measures, not accuracy percentages.",
        "",
        "## Operational block",
        "",
        "Do not use these forecasts for live employee allocation until source data "
        "is refreshed, the estate operating calendar is approved, and field-level "
        "shadow-mode validation is complete.",
    ]
    (run_folder / "README.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "LATEST_DAILY_HIERARCHY_RUN.txt").write_text(
        str(run_folder), encoding="utf-8"
    )

    print("")
    print("DAILY HIERARCHY DEVELOPMENT CANDIDATE FINISHED")
    print(json.dumps(summary, indent=2))
    return 0 if summary["status"] == "PASS_CANDIDATE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
