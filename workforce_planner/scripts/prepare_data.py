from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable
import argparse
import csv
import hashlib
import json
import statistics
import zipfile

import openpyxl


DIVISION_CODES = {
    "avoca": "AD",
    "lower": "LD",
    "upper": "UD",
}
DIVISION_ID_CODES = {
    "67": "AD",
    "68": "LD",
    "69": "UD",
}


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_day(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raw = text(value)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def median(values: Iterable[float], default: float = 0.0) -> float:
    clean = [float(value) for value in values if value is not None]
    return round(float(statistics.median(clean)), 4) if clean else float(default)


def normalize_field_code(value: Any) -> str:
    return "".join(text(value).upper().split())


def normalize_division(name: Any, division_id: Any = None) -> str:
    normalized = text(name).casefold()
    if normalized in DIVISION_CODES:
        return DIVISION_CODES[normalized]
    identifier = text(division_id)
    if identifier in DIVISION_ID_CODES:
        return DIVISION_ID_CODES[identifier]
    cleaned = "".join(character for character in text(name).upper() if character.isalnum())
    return cleaned[:3]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def anonymous_aliases(employee_numbers: set[str]) -> dict[str, str]:
    ordered = sorted(
        employee_numbers,
        key=lambda value: hashlib.sha256(f"tte-workforce-rl-v2|{value}".encode()).hexdigest(),
    )
    width = max(3, len(str(len(ordered))))
    return {value: f"EMP-{index:0{width}d}" for index, value in enumerate(ordered, start=1)}


def _csv_rows(source: Path) -> tuple[list[tuple], dict[str, Any]]:
    rows: list[tuple] = []
    scanned = 0
    invalid = Counter()
    with source.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"Division", "Field Code", "Employee_No", "Weighing_Date", "Kilos"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")
        for row in reader:
            scanned += 1
            employee = text(row.get("Employee_No"))
            division = text(row.get("Division")).upper()
            field_code = normalize_field_code(row.get("Field Code"))
            day = parse_day(row.get("Weighing_Date"))
            kilos = max(0.0, number(row.get("Kilos")))
            if not employee or not division or not field_code or not day:
                invalid["invalid_required_values"] += 1
                continue
            rows.append((
                employee,
                day,
                division,
                f"{division}/{field_code}",
                field_code,
                text(row.get("Home Division")).upper(),
                kilos,
                text(row.get("Work_Type")),
            ))
    return rows, {
        "source_kind": "employee_plucking_csv",
        "source_name": source.name,
        "source_files": [source.name],
        "source_sha256": sha256_file(source),
        "source_rows_scanned": scanned,
        "source_rows_used": len(rows),
        "source_net_kg_used": round(sum(row[6] for row in rows), 4),
        "excluded_rows": dict(invalid),
        "weight_measure": "Kilos",
        "work_filter": "All rows in the supplied plucking CSV",
    }


def _historical_workbook_rows(
    workbook,
    source_name: str,
    seen_weighing_ids: set[str],
) -> tuple[list[tuple], Counter]:
    if "All Records" not in workbook.sheetnames:
        raise ValueError(f"{source_name}: required 'All Records' sheet is missing")
    worksheet = workbook["All Records"]
    values = worksheet.iter_rows(values_only=True)
    headers = [text(value).lower() for value in next(values, ())]
    positions = {header: index for index, header in enumerate(headers)}
    required = {"date", "employee_id", "net_weight", "field_code", "division_name", "type"}
    missing = required.difference(positions)
    if missing:
        raise ValueError(f"{source_name}: missing required columns: {', '.join(sorted(missing))}")

    def get(row, name: str):
        index = positions.get(name)
        return row[index] if index is not None and index < len(row) else None

    rows: list[tuple] = []
    stats = Counter()
    for row in values:
        stats["rows_scanned"] += 1
        weighing_id = text(get(row, "weighing_id"))
        if weighing_id and weighing_id in seen_weighing_ids:
            stats["duplicate_weighing_id"] += 1
            continue
        if weighing_id:
            seen_weighing_ids.add(weighing_id)

        work_type = text(get(row, "type"))
        if "PLUCK" not in work_type.upper():
            stats["non_plucking_work"] += 1
            continue
        kilos = number(get(row, "net_weight"))
        if kilos <= 0:
            stats["non_positive_net_weight"] += 1
            continue
        employee = text(get(row, "employee_id") or get(row, "employee_internal_no"))
        estate = text(get(row, "estate_id"))
        employee_key = f"{estate}|{employee}" if estate else employee
        division = normalize_division(get(row, "division_name"), get(row, "division_id"))
        field_code = normalize_field_code(get(row, "field_code") or get(row, "field_name"))
        day = parse_day(get(row, "date"))
        if not employee_key or not division or not field_code or not day:
            stats["invalid_required_values"] += 1
            continue
        rows.append((
            employee_key,
            day,
            division,
            f"{division}/{field_code}",
            field_code,
            "",
            kilos,
            text(get(row, "code")) or work_type,
        ))
        stats["rows_used"] += 1
        stats["net_weight_used"] += kilos
    return rows, stats


def _xlsx_rows(source: Path) -> tuple[list[tuple], dict[str, Any]]:
    all_rows: list[tuple] = []
    totals = Counter()
    files: list[str] = []
    seen_weighing_ids: set[str] = set()

    if source.is_dir():
        paths = sorted(source.rglob("*.xlsx"))
        if not paths:
            raise ValueError("No .xlsx workbooks were found in the supplied directory")
        inputs = [(path.name, path) for path in paths]
    elif source.suffix.lower() == ".xlsx":
        inputs = [(source.name, source)]
    elif source.suffix.lower() == ".zip":
        inputs = []
        with zipfile.ZipFile(source) as archive:
            names = sorted(name for name in archive.namelist() if name.lower().endswith(".xlsx"))
            if not names:
                raise ValueError("No .xlsx workbooks were found in the supplied ZIP archive")
            for name in names:
                inputs.append((Path(name).name, BytesIO(archive.read(name))))
    else:
        raise ValueError("Expected an estate .zip, .xlsx, directory, or employee plucking .csv")

    for name, workbook_input in inputs:
        workbook = openpyxl.load_workbook(workbook_input, read_only=True, data_only=True)
        try:
            rows, stats = _historical_workbook_rows(workbook, name, seen_weighing_ids)
        finally:
            workbook.close()
        all_rows.extend(rows)
        totals.update(stats)
        files.append(name)

    source_hash = sha256_file(source) if source.is_file() else None
    return all_rows, {
        "source_kind": "historical_estate_xlsx_archive",
        "source_name": source.name,
        "source_files": files,
        "source_sha256": source_hash,
        "source_rows_scanned": totals["rows_scanned"],
        "source_rows_used": totals["rows_used"],
        "source_net_kg_used": round(float(totals["net_weight_used"]), 4),
        "excluded_rows": {
            "non_plucking_work": totals["non_plucking_work"],
            "non_positive_net_weight": totals["non_positive_net_weight"],
            "invalid_required_values": totals["invalid_required_values"],
            "duplicate_weighing_id": totals["duplicate_weighing_id"],
        },
        "weight_measure": "net_weight",
        "work_filter": "Rows whose work type contains PLUCK; SACKING F2F is excluded",
    }


def load_source_rows(source: Path) -> tuple[list[tuple], dict[str, Any]]:
    if source.suffix.lower() == ".csv":
        return _csv_rows(source)
    return _xlsx_rows(source)


def build_profile(source: Path) -> dict:
    raw_rows, source_metadata = load_source_rows(source)
    if not raw_rows:
        raise ValueError("The source produced no usable employee plucking rows")
    employee_numbers = {row[0] for row in raw_rows}
    aliases = anonymous_aliases(employee_numbers)

    employee_day = defaultdict(float)
    employee_field_day = defaultdict(float)
    employee_division_day = defaultdict(float)
    employee_divisions = defaultdict(Counter)
    employee_home = defaultdict(Counter)
    daily_field = defaultdict(lambda: defaultdict(float))
    daily_employees = defaultdict(set)
    field_workers = defaultdict(list)
    work_types = Counter()

    for employee_key, record_date, division, field_id, _field_code, home_division, kilos, work_type in raw_rows:
        alias = aliases[employee_key]
        employee_day[(alias, record_date)] += kilos
        employee_field_day[(alias, field_id, record_date)] += kilos
        employee_division_day[(alias, division, record_date)] += kilos
        employee_divisions[alias][division] += 1
        if home_division:
            employee_home[alias][home_division] += 1
        daily_field[record_date][field_id] += kilos
        daily_employees[record_date].add(alias)
        if work_type:
            work_types[work_type] += 1
    del raw_rows

    employee_overall_values = defaultdict(list)
    employee_field_values = defaultdict(lambda: defaultdict(list))
    employee_division_values = defaultdict(lambda: defaultdict(list))
    for (employee, _date), kilos in employee_day.items():
        employee_overall_values[employee].append(kilos)
    for (employee, field_id, _date), kilos in employee_field_day.items():
        employee_field_values[employee][field_id].append(kilos)
        field_workers[field_id].append(kilos)
    for (employee, division, _date), kilos in employee_division_day.items():
        employee_division_values[employee][division].append(kilos)

    employees = []
    for employee in sorted(employee_overall_values):
        field_productivity = {
            field_id: {"median_kg": median(values), "days": len(values)}
            for field_id, values in sorted(employee_field_values[employee].items())
        }
        division_productivity = {
            division: {"median_kg": median(values), "days": len(values)}
            for division, values in sorted(employee_division_values[employee].items())
        }
        observed_division = employee_divisions[employee].most_common(1)[0][0]
        home_division = employee_home[employee].most_common(1)[0][0] if employee_home[employee] else observed_division
        employees.append({
            "id": employee,
            "home_division": home_division,
            "overall_median_kg": median(employee_overall_values[employee]),
            "days_observed": len(employee_overall_values[employee]),
            "field_productivity": field_productivity,
            "division_productivity": division_productivity,
        })

    field_daily_values = defaultdict(list)
    for field_map in daily_field.values():
        for field_id, kilos in field_map.items():
            field_daily_values[field_id].append(kilos)
    fields = []
    for field_id in sorted(field_daily_values):
        division, field_code = field_id.split("/", 1)
        fields.append({
            "id": field_id,
            "division": division,
            "field_code": field_code,
            "median_active_day_demand_kg": median(field_daily_values[field_id]),
            "active_days": len(field_daily_values[field_id]),
            "median_worker_kg": median(field_workers[field_id], default=12.0),
        })

    daily_totals = {record_date: sum(field_map.values()) for record_date, field_map in daily_field.items()}
    typical_total = median(daily_totals.values())
    typical_workers = median(len(values) for values in daily_employees.values())
    days = []
    for record_date in sorted(daily_employees):
        demand = {
            field_id: round(kilos, 4)
            for field_id, kilos in sorted(daily_field[record_date].items())
            if kilos > 0
        }
        total = daily_totals[record_date]
        worker_count = len(daily_employees[record_date])
        incomplete = total < typical_total * 0.5 or worker_count < typical_workers * 0.5
        days.append({
            "date": record_date,
            "demand_kg": demand,
            "available_employee_ids": sorted(daily_employees[record_date]),
            "total_kg": round(total, 4),
            "employee_count": worker_count,
            "incomplete": incomplete,
        })

    complete_days = [item for item in days if not item["incomplete"]]
    if not complete_days:
        raise ValueError("No complete workdays remain after profile validation")
    metadata = {
        "schema_version": 2,
        **source_metadata,
        "date_min": days[0]["date"],
        "date_max": days[-1]["date"],
        "day_count": len(days),
        "complete_day_count": len(complete_days),
        "employee_count": len(employees),
        "field_count": len(fields),
        "division_count": len({field["division"] for field in fields}),
        "typical_daily_kg": typical_total,
        "typical_daily_workers": typical_workers,
        "default_template_date": complete_days[-1]["date"],
        "work_type_counts": dict(sorted(work_types.items())),
        "privacy": (
            "Pseudonymized employee aliases are generated. Names, EPF numbers, image names, "
            "source employee identifiers and the alias mapping are excluded from this profile."
        ),
    }
    return {"metadata": metadata, "fields": fields, "employees": employees, "days": days}


def main():
    parser = argparse.ArgumentParser(description="Create a pseudonymized TTE workforce profile")
    parser.add_argument("source", type=Path, help="Estate ZIP/XLSX/directory or employee plucking CSV")
    parser.add_argument("output_json", type=Path)
    args = parser.parse_args()
    profile = build_profile(args.source)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    print(json.dumps(profile["metadata"], indent=2))


if __name__ == "__main__":
    main()
