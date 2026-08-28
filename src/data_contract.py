"""Data contract and quality checks for multi-estate GAP forecasting inputs."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

import pandas as pd


@dataclass
class ValidationIssue:
    dataset: str
    severity: str
    check: str
    message: str
    row_count: int | None = None


CONTRACTS = {
    "estate_master": {
        "sheet": "Estate Master",
        "required": ["plantation_code", "region_code", "estate_code", "estate_name", "weather_station_code", "manager_id", "tea_extent_ha", "active"],
        "dates": [],
        "numeric": ["latitude", "longitude", "mean_elevation_m", "tea_extent_ha"],
        "unique": ["estate_code"],
    },
    "field_master": {
        "sheet": "Field Master",
        "required": ["estate_code", "division_code", "field_code", "field_name", "extent_ha", "elevation_m", "tea_type", "last_pruning_date", "active"],
        "dates": ["last_pruning_date"],
        "numeric": ["extent_ha", "elevation_m", "planting_year", "pruning_cycle_year"],
        "unique": ["estate_code", "field_code"],
    },
    "crop_daily": {
        "sheet": "Crop Daily",
        "required": ["date", "estate_code", "division_code", "field_code", "green_leaf_kg"],
        "dates": ["date"],
        "numeric": ["green_leaf_kg", "made_tea_kg", "plucker_count", "plucking_round_days"],
        "unique": ["date", "estate_code", "field_code"],
    },
    "practice_log": {
        "sheet": "Practice Log",
        "required": ["actual_date", "estate_code", "division_code", "field_code", "operation", "area_ha", "completion_status", "manager_id", "source_type"],
        "dates": ["planned_date", "actual_date"],
        "numeric": ["rate", "area_ha", "quantity_used"],
        "unique": [],
    },
    "sundry_work": {
        "sheet": "Sundry Work",
        "required": ["date", "estate_code", "division_code", "field_code", "work_category", "employee_count", "man_days", "manager_id"],
        "dates": ["date"],
        "numeric": ["employee_count", "man_days", "hours", "cost_lkr", "completed_quantity"],
        "unique": [],
    },
    "manager_assignment": {
        "sheet": "Manager Assignment",
        "required": ["manager_id", "estate_code", "role", "start_date", "active"],
        "dates": ["start_date", "end_date"],
        "numeric": [],
        "unique": [],
    },
    "weather_map": {
        "sheet": "Weather Map",
        "required": ["estate_code", "weather_station_code", "valid_from", "mapping_quality"],
        "dates": ["valid_from", "valid_to"],
        "numeric": ["distance_km", "elevation_difference_m"],
        "unique": [],
    },
    "fertilizer_plan": {
        "sheet": "Fertilizer Plan",
        "required": ["plan_year", "estate_code", "field_code", "fertilizer_type", "recommended_rate", "rate_unit", "planned_window_start", "planned_window_end", "approval_status"],
        "dates": ["planned_window_start", "planned_window_end"],
        "numeric": ["plan_year", "recommended_rate", "planned_area_ha"],
        "unique": [],
    },
    "monthly_financials": {
        "sheet": "Monthly Financials",
        "required": ["month", "estate_code", "crop_revenue_lkr", "agricultural_cost_lkr", "labour_cost_lkr", "input_cost_lkr", "operating_profit_lkr"],
        "dates": ["month"],
        "numeric": ["crop_revenue_lkr", "agricultural_cost_lkr", "labour_cost_lkr", "input_cost_lkr", "operating_profit_lkr"],
        "unique": ["month", "estate_code"],
    },
}


def empty_frames() -> dict[str, pd.DataFrame]:
    frames = {}
    for name, spec in CONTRACTS.items():
        columns = list(dict.fromkeys(spec["required"] + spec["dates"] + spec["numeric"] + spec["unique"]))
        frames[name] = pd.DataFrame(columns=columns)
    return frames


def validate_frame(dataset: str, frame: pd.DataFrame) -> tuple[pd.DataFrame, list[ValidationIssue]]:
    if dataset not in CONTRACTS:
        raise KeyError(f"Unknown dataset: {dataset}")
    spec = CONTRACTS[dataset]
    df = frame.copy()
    df.columns = [str(c).strip() for c in df.columns]
    issues: list[ValidationIssue] = []
    missing_columns = [c for c in spec["required"] if c not in df.columns]
    if missing_columns:
        issues.append(ValidationIssue(dataset, "ERROR", "required_columns", f"Missing required columns: {missing_columns}"))
        return df, issues

    df = df.dropna(how="all").copy()
    if df.empty:
        severity = "WARNING" if dataset == "monthly_financials" else "ERROR"
        issues.append(ValidationIssue(dataset, severity, "empty_dataset", "Dataset contains no records.", 0))
        return df, issues
    for col in spec["required"]:
        blank = df[col].isna() | df[col].astype(str).str.strip().eq("")
        if blank.any():
            issues.append(ValidationIssue(dataset, "ERROR", "required_values", f"Blank values in required column '{col}'.", int(blank.sum())))

    for col in spec["dates"]:
        if col not in df.columns:
            continue
        parsed = pd.to_datetime(df[col], errors="coerce")
        bad = df[col].notna() & parsed.isna()
        if bad.any():
            issues.append(ValidationIssue(dataset, "ERROR", "date_type", f"Invalid dates in '{col}'.", int(bad.sum())))
        df[col] = parsed

    for col in spec["numeric"]:
        if col not in df.columns:
            continue
        parsed = pd.to_numeric(df[col], errors="coerce")
        bad = df[col].notna() & parsed.isna()
        if bad.any():
            issues.append(ValidationIssue(dataset, "ERROR", "numeric_type", f"Non-numeric values in '{col}'.", int(bad.sum())))
        df[col] = parsed

    if spec["unique"] and all(c in df.columns for c in spec["unique"]):
        duplicate = df.duplicated(spec["unique"], keep=False)
        if duplicate.any():
            issues.append(ValidationIssue(dataset, "ERROR", "duplicate_key", f"Duplicate key: {spec['unique']}", int(duplicate.sum())))

    if "green_leaf_kg" in df.columns:
        bad = df["green_leaf_kg"].fillna(0) < 0
        if bad.any():
            issues.append(ValidationIssue(dataset, "ERROR", "negative_crop", "Negative green-leaf kilograms.", int(bad.sum())))
    if "area_ha" in df.columns:
        bad = df["area_ha"].fillna(0) < 0
        if bad.any():
            issues.append(ValidationIssue(dataset, "ERROR", "negative_area", "Negative treated area.", int(bad.sum())))
    return df, issues


def validate_bundle(frames: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    cleaned: dict[str, pd.DataFrame] = {}
    issues: list[ValidationIssue] = []
    for dataset, frame in frames.items():
        if dataset not in CONTRACTS:
            continue
        cleaned[dataset], frame_issues = validate_frame(dataset, frame)
        issues.extend(frame_issues)

    estate_codes = set(cleaned.get("estate_master", pd.DataFrame()).get("estate_code", pd.Series(dtype=str)).dropna().astype(str))
    field_keys = set(zip(
        cleaned.get("field_master", pd.DataFrame()).get("estate_code", pd.Series(dtype=str)).astype(str),
        cleaned.get("field_master", pd.DataFrame()).get("field_code", pd.Series(dtype=str)).astype(str),
    ))
    for name, df in cleaned.items():
        if name != "estate_master" and "estate_code" in df.columns and estate_codes:
            bad = ~df["estate_code"].astype(str).isin(estate_codes)
            if bad.any():
                issues.append(ValidationIssue(name, "ERROR", "estate_reference", "Estate codes not found in Estate Master.", int(bad.sum())))
        if name in {"crop_daily", "practice_log", "sundry_work", "fertilizer_plan"} and {"estate_code", "field_code"}.issubset(df.columns) and field_keys:
            keys = list(zip(df["estate_code"].astype(str), df["field_code"].astype(str)))
            missing = sum(key not in field_keys for key in keys)
            if missing:
                issues.append(ValidationIssue(name, "ERROR", "field_reference", "Estate/field combinations not found in Field Master.", missing))

    issue_df = pd.DataFrame([asdict(issue) for issue in issues], columns=["dataset", "severity", "check", "message", "row_count"])
    return cleaned, issue_df


def read_input_bundle(path: str | Path) -> dict[str, pd.DataFrame]:
    path = Path(path)
    frames: dict[str, pd.DataFrame] = {}
    if path.is_file() and path.suffix.lower() == ".xlsx":
        workbook = pd.ExcelFile(path)
        for name, spec in CONTRACTS.items():
            if spec["sheet"] in workbook.sheet_names:
                frames[name] = pd.read_excel(path, sheet_name=spec["sheet"], header=3)
        return frames
    if path.is_dir():
        for name in CONTRACTS:
            csv_path = path / f"{name}.csv"
            if csv_path.exists():
                frames[name] = pd.read_csv(csv_path)
        return frames
    raise ValueError("Provide the standardized XLSX template or a directory containing contract-named CSV files.")
