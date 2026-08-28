from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import time
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable

try:
    import openpyxl
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: openpyxl. Install it with: py -m pip install openpyxl"
    ) from exc


PACKAGE_VERSION = "3.0.1"
SCHEMA_VERSION = 2
REQUIRED_COLUMNS = {
    "date",
    "employee_id",
    "net_weight",
    "field_code",
    "division_name",
    "type",
}
OPTIONAL_COLUMNS = {
    "weighing_id",
    "employee_internal_no",
    "estate_id",
    "division_id",
    "field_name",
    "code",
}


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def normalize_header(value: Any) -> str:
    return re.sub(r"\s+", "_", text(value).strip().lower())


def clean_estate_name(value: str) -> str:
    stem = Path(value).stem
    stem = re.sub(r"(?i)(?:_output|-output|\soutput)$", "", stem)
    stem = re.sub(r"(?i)(?:[_\-\s]?(?:19|20)\d{2})$", "", stem)
    return re.sub(r"[^a-z0-9]+", "", stem.casefold())


def display_estate_name(value: str) -> str:
    stem = Path(value).stem
    stem = re.sub(r"(?i)(?:_output|-output|\soutput)$", "", stem)
    stem = re.sub(r"(?i)(?:[_\-\s]?(?:19|20)\d{2})$", "", stem)
    return stem.strip()


def parse_day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = text(value)
    if not raw:
        return None
    for fmt in (
        "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d",
        "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S",
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


def number(value: Any) -> float | None:
    try:
        result = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def employee_alias(value: Any) -> str:
    raw = text(value)
    if not raw:
        return ""
    digest = hashlib.sha256(
        f"tte-data-audit-v3|{raw}".encode("utf-8", errors="ignore")
    ).hexdigest()[:12]
    return f"EMP-{digest.upper()}"


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


@dataclass
class WorkbookAudit:
    archive_estate: str
    archive_name: str
    workbook_name: str
    workbook_estate_guess: str
    identity_status: str
    all_records_sheet_found: bool
    readable: bool
    required_columns_found: str
    missing_required_columns: str
    rows_scanned: int = 0
    plucking_rows: int = 0
    valid_rows: int = 0
    invalid_required_values: int = 0
    non_positive_net_weight: int = 0
    duplicate_weighing_id: int = 0
    date_min: str = ""
    date_max: str = ""
    employee_count: int = 0
    field_count: int = 0
    division_count: int = 0
    estate_id_count: int = 0
    estate_ids: str = ""
    total_net_kg: float = 0.0
    error: str = ""


@dataclass
class EstateAccumulator:
    estate: str
    archive_name: str
    workbook_count: int = 0
    readable_workbooks: int = 0
    failed_workbooks: int = 0
    all_records_sheets: int = 0
    rows_scanned: int = 0
    plucking_rows: int = 0
    valid_rows: int = 0
    invalid_required_values: int = 0
    non_positive_net_weight: int = 0
    duplicate_weighing_id: int = 0
    total_net_kg: float = 0.0
    date_min: date | None = None
    date_max: date | None = None
    employees: set[str] = field(default_factory=set)
    fields: set[str] = field(default_factory=set)
    divisions: set[str] = field(default_factory=set)
    estate_ids: set[str] = field(default_factory=set)
    identity_mismatches: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def absorb(
        self,
        audit: WorkbookAudit,
        raw_date_min: date | None,
        raw_date_max: date | None,
        employees: set[str],
        fields: set[str],
        divisions: set[str],
        estate_ids: set[str],
    ) -> None:
        self.workbook_count += 1
        self.readable_workbooks += int(audit.readable)
        self.failed_workbooks += int(not audit.readable)
        self.all_records_sheets += int(audit.all_records_sheet_found)

        self.rows_scanned += int(audit.rows_scanned)
        self.plucking_rows += int(audit.plucking_rows)
        self.valid_rows += int(audit.valid_rows)
        self.invalid_required_values += int(audit.invalid_required_values)
        self.non_positive_net_weight += int(audit.non_positive_net_weight)
        self.duplicate_weighing_id += int(audit.duplicate_weighing_id)
        self.total_net_kg += float(audit.total_net_kg)

        self.employees.update(employees)
        self.fields.update(fields)
        self.divisions.update(divisions)
        self.estate_ids.update(estate_ids)

        if audit.identity_status == "MISMATCH":
            self.identity_mismatches.append(audit.workbook_name)
        if audit.error:
            self.errors.append(f"{audit.workbook_name}: {audit.error}")

        if raw_date_min and (self.date_min is None or raw_date_min < self.date_min):
            self.date_min = raw_date_min
        if raw_date_max and (self.date_max is None or raw_date_max > self.date_max):
            self.date_max = raw_date_max


def audit_workbook(
    archive_estate: str,
    archive_name: str,
    workbook_name: str,
    workbook_bytes: bytes,
    seen_weighing_ids: set[str],
    rejected_samples: list[dict[str, Any]],
    max_rejected_samples: int,
) -> tuple[WorkbookAudit, date | None, date | None, set[str], set[str], set[str], set[str]]:
    workbook_guess_display = display_estate_name(Path(workbook_name).name)
    identity_status = (
        "MATCH"
        if clean_estate_name(workbook_guess_display) == clean_estate_name(archive_estate)
        else "MISMATCH"
    )

    try:
        workbook = openpyxl.load_workbook(
            BytesIO(workbook_bytes), read_only=True, data_only=True
        )
    except Exception as exc:
        return (
            WorkbookAudit(
                archive_estate=archive_estate,
                archive_name=archive_name,
                workbook_name=Path(workbook_name).name,
                workbook_estate_guess=workbook_guess_display,
                identity_status=identity_status,
                all_records_sheet_found=False,
                readable=False,
                required_columns_found="",
                missing_required_columns="",
                error=f"Workbook open failed: {type(exc).__name__}: {exc}",
            ),
            None, None, set(), set(), set(), set(),
        )

    try:
        if "All Records" not in workbook.sheetnames:
            return (
                WorkbookAudit(
                    archive_estate=archive_estate,
                    archive_name=archive_name,
                    workbook_name=Path(workbook_name).name,
                    workbook_estate_guess=workbook_guess_display,
                    identity_status=identity_status,
                    all_records_sheet_found=False,
                    readable=True,
                    required_columns_found="",
                    missing_required_columns=",".join(sorted(REQUIRED_COLUMNS)),
                    error="Required 'All Records' sheet is missing",
                ),
                None, None, set(), set(), set(), set(),
            )

        worksheet = workbook["All Records"]
        values = worksheet.iter_rows(values_only=True)
        headers = [normalize_header(value) for value in next(values, ())]
        positions = {header: index for index, header in enumerate(headers) if header}
        missing = sorted(REQUIRED_COLUMNS.difference(positions))
        found = sorted(REQUIRED_COLUMNS.intersection(positions))

        if missing:
            return (
                WorkbookAudit(
                    archive_estate=archive_estate,
                    archive_name=archive_name,
                    workbook_name=Path(workbook_name).name,
                    workbook_estate_guess=workbook_guess_display,
                    identity_status=identity_status,
                    all_records_sheet_found=True,
                    readable=True,
                    required_columns_found=",".join(found),
                    missing_required_columns=",".join(missing),
                    error="Missing required columns: " + ", ".join(missing),
                ),
                None, None, set(), set(), set(), set(),
            )

        def get(row: tuple[Any, ...], name: str) -> Any:
            index = positions.get(name)
            return row[index] if index is not None and index < len(row) else None

        rows_scanned = plucking_rows = valid_rows = 0
        invalid_required_values = non_positive_net_weight = duplicate_weighing_id = 0
        total_net_kg = 0.0
        date_min: date | None = None
        date_max: date | None = None
        employees: set[str] = set()
        fields: set[str] = set()
        divisions: set[str] = set()
        estate_ids: set[str] = set()

        for row_number, row in enumerate(values, start=2):
            rows_scanned += 1
            work_type = text(get(row, "type"))
            if "PLUCK" not in work_type.upper():
                continue
            plucking_rows += 1

            weighing_id = text(get(row, "weighing_id"))
            if weighing_id:
                if weighing_id in seen_weighing_ids:
                    duplicate_weighing_id += 1
                    if len(rejected_samples) < max_rejected_samples:
                        rejected_samples.append({
                            "archive_estate": archive_estate,
                            "archive_name": archive_name,
                            "workbook_name": Path(workbook_name).name,
                            "row_number": row_number,
                            "employee_alias": employee_alias(
                                get(row, "employee_id") or get(row, "employee_internal_no")
                            ),
                            "division": text(get(row, "division_name"))[:80],
                            "field": text(
                                get(row, "field_code") or get(row, "field_name")
                            )[:80],
                            "date_value": text(get(row, "date"))[:80],
                            "net_weight_value": text(get(row, "net_weight"))[:80],
                            "reason": "duplicate_weighing_id",
                        })
                    continue
                seen_weighing_ids.add(weighing_id)

            kilos = number(get(row, "net_weight"))
            if kilos is None or kilos <= 0:
                non_positive_net_weight += 1
                if len(rejected_samples) < max_rejected_samples:
                    rejected_samples.append({
                        "archive_estate": archive_estate,
                        "archive_name": archive_name,
                        "workbook_name": Path(workbook_name).name,
                        "row_number": row_number,
                        "employee_alias": employee_alias(
                            get(row, "employee_id") or get(row, "employee_internal_no")
                        ),
                        "division": text(get(row, "division_name"))[:80],
                        "field": text(
                            get(row, "field_code") or get(row, "field_name")
                        )[:80],
                        "date_value": text(get(row, "date"))[:80],
                        "net_weight_value": text(get(row, "net_weight"))[:80],
                        "reason": "non_positive_or_invalid_net_weight",
                    })
                continue

            employee_value = text(
                get(row, "employee_id") or get(row, "employee_internal_no")
            )
            division_value = text(get(row, "division_name"))
            field_value = text(get(row, "field_code") or get(row, "field_name"))
            row_date = parse_day(get(row, "date"))
            estate_id = text(get(row, "estate_id"))

            reasons: list[str] = []
            if not employee_value:
                reasons.append("missing_employee")
            if not division_value:
                reasons.append("missing_division")
            if not field_value:
                reasons.append("missing_field")
            if row_date is None:
                reasons.append("missing_or_invalid_date")

            if reasons:
                invalid_required_values += 1
                if len(rejected_samples) < max_rejected_samples:
                    rejected_samples.append({
                        "archive_estate": archive_estate,
                        "archive_name": archive_name,
                        "workbook_name": Path(workbook_name).name,
                        "row_number": row_number,
                        "employee_alias": employee_alias(employee_value),
                        "division": division_value[:80],
                        "field": field_value[:80],
                        "date_value": text(get(row, "date"))[:80],
                        "net_weight_value": text(get(row, "net_weight"))[:80],
                        "reason": "|".join(reasons),
                    })
                continue

            valid_rows += 1
            total_net_kg += kilos
            employees.add(employee_value)
            divisions.add(division_value)
            fields.add(field_value)
            if estate_id:
                estate_ids.add(estate_id)
            if date_min is None or row_date < date_min:
                date_min = row_date
            if date_max is None or row_date > date_max:
                date_max = row_date

        audit = WorkbookAudit(
            archive_estate=archive_estate,
            archive_name=archive_name,
            workbook_name=Path(workbook_name).name,
            workbook_estate_guess=workbook_guess_display,
            identity_status=identity_status,
            all_records_sheet_found=True,
            readable=True,
            required_columns_found=",".join(found),
            missing_required_columns="",
            rows_scanned=rows_scanned,
            plucking_rows=plucking_rows,
            valid_rows=valid_rows,
            invalid_required_values=invalid_required_values,
            non_positive_net_weight=non_positive_net_weight,
            duplicate_weighing_id=duplicate_weighing_id,
            date_min=date_min.isoformat() if date_min else "",
            date_max=date_max.isoformat() if date_max else "",
            employee_count=len(employees),
            field_count=len(fields),
            division_count=len(divisions),
            estate_id_count=len(estate_ids),
            estate_ids="|".join(sorted(estate_ids)),
            total_net_kg=round(total_net_kg, 4),
        )
        return (
            audit, date_min, date_max, employees, fields, divisions, estate_ids
        )
    finally:
        workbook.close()


def audit_archive(
    archive_path: Path,
    rejected_samples: list[dict[str, Any]],
    max_rejected_samples: int,
) -> tuple[EstateAccumulator, list[WorkbookAudit], list[dict[str, str]]]:
    archive_estate_display = display_estate_name(archive_path.name)
    accumulator = EstateAccumulator(
        estate=archive_estate_display,
        archive_name=archive_path.name,
    )
    workbook_rows: list[WorkbookAudit] = []
    aliases: list[dict[str, str]] = []
    seen_weighing_ids: set[str] = set()

    try:
        with zipfile.ZipFile(archive_path) as archive:
            workbook_names = sorted(
                name for name in archive.namelist()
                if not name.endswith("/") and name.lower().endswith((".xlsx", ".xlsm"))
            )
            if not workbook_names:
                accumulator.errors.append("No XLSX/XLSM workbooks found in archive")
                return accumulator, workbook_rows, aliases

            for workbook_name in workbook_names:
                workbook_guess = display_estate_name(Path(workbook_name).name)
                identity_status = (
                    "MATCH"
                    if clean_estate_name(workbook_guess) == clean_estate_name(archive_estate_display)
                    else "MISMATCH"
                )
                aliases.append({
                    "archive_estate": archive_estate_display,
                    "archive_name": archive_path.name,
                    "internal_workbook": Path(workbook_name).name,
                    "internal_path": workbook_name,
                    "internal_estate_guess": workbook_guess,
                    "canonical_estate": archive_estate_display,
                    "identity_status": identity_status,
                })

                audit, dmin, dmax, employees, fields, divisions, estate_ids = audit_workbook(
                    archive_estate=archive_estate_display,
                    archive_name=archive_path.name,
                    workbook_name=workbook_name,
                    workbook_bytes=archive.read(workbook_name),
                    seen_weighing_ids=seen_weighing_ids,
                    rejected_samples=rejected_samples,
                    max_rejected_samples=max_rejected_samples,
                )
                workbook_rows.append(audit)
                accumulator.absorb(
                    audit, dmin, dmax, employees, fields, divisions, estate_ids
                )
    except zipfile.BadZipFile as exc:
        accumulator.errors.append(f"Invalid ZIP archive: {exc}")
    except Exception as exc:
        accumulator.errors.append(
            f"Archive processing failed: {type(exc).__name__}: {exc}"
        )

    return accumulator, workbook_rows, aliases


def score_estate(acc: EstateAccumulator, today: date) -> tuple[int, str, list[str]]:
    score = 0
    reasons: list[str] = []

    if acc.workbook_count > 0:
        score += 10
    else:
        reasons.append("No workbooks found")

    if acc.readable_workbooks == acc.workbook_count and acc.workbook_count > 0:
        score += 10
    elif acc.readable_workbooks > 0:
        score += 5
        reasons.append("One or more workbooks could not be fully audited")
    else:
        reasons.append("No readable workbooks")

    if acc.all_records_sheets == acc.workbook_count and acc.workbook_count > 0:
        score += 15
    elif acc.all_records_sheets > 0:
        score += 7
        reasons.append("One or more workbooks are missing the All Records sheet")
    else:
        reasons.append("No All Records sheet found")

    if not acc.errors:
        score += 10
    else:
        reasons.extend(acc.errors[:5])

    if acc.valid_rows >= 5000:
        score += 15
    elif acc.valid_rows >= 1000:
        score += 8
        reasons.append("Limited valid plucking rows")
    else:
        reasons.append("Very limited valid plucking rows")

    invalid_rate = acc.invalid_required_values / max(1, acc.plucking_rows)
    if invalid_rate <= 0.01:
        score += 10
    elif invalid_rate <= 0.05:
        score += 6
        reasons.append(f"Invalid required-value rate: {invalid_rate:.2%}")
    else:
        reasons.append(f"High invalid required-value rate: {invalid_rate:.2%}")

    duplicate_rate = acc.duplicate_weighing_id / max(1, acc.rows_scanned)
    if duplicate_rate <= 0.001:
        score += 5
    elif duplicate_rate <= 0.01:
        score += 3
        reasons.append(f"Duplicate weighing-ID rate: {duplicate_rate:.2%}")
    else:
        reasons.append(f"High duplicate weighing-ID rate: {duplicate_rate:.2%}")

    if acc.date_min and acc.date_max:
        history_days = (acc.date_max - acc.date_min).days
        if history_days >= 730:
            score += 10
        elif history_days >= 300:
            score += 6
            reasons.append("Less than two years of history")
        else:
            score += 2
            reasons.append("Short history: less than 300 days")

        age_days = (today - acc.date_max).days
        if age_days <= 60:
            score += 5
        elif age_days <= 180:
            score += 3
            reasons.append(f"Latest data is {age_days} days old")
        else:
            reasons.append(f"Stale latest data: {age_days} days old")
    else:
        reasons.append("No valid date range")

    if acc.employees and acc.fields and acc.divisions:
        score += 10
    else:
        reasons.append("Employee, field or division identities are missing")

    if not acc.identity_mismatches:
        score += 5
    else:
        reasons.append(
            "Archive/workbook identity mismatch: "
            + ", ".join(acc.identity_mismatches[:8])
        )

    score = max(0, min(100, score))

    hard_failure = (
        acc.valid_rows == 0
        or acc.all_records_sheets == 0
        or acc.readable_workbooks == 0
    )
    if hard_failure or score < 60:
        status = "NOT_READY"
    elif acc.identity_mismatches or score < 85:
        status = "CONDITIONAL"
    else:
        status = "READY"
    return score, status, reasons


def main() -> int:
    parser = argparse.ArgumentParser(
        description="TTE all-estate data identity and readiness audit v3.0.1."
    )
    parser.add_argument("--crop-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--expected-estates", type=int, default=33)
    parser.add_argument("--max-rejected-samples", type=int, default=660)
    args = parser.parse_args()

    crop_root = Path(args.crop_root).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    if not crop_root.exists():
        raise SystemExit(f"Crop root does not exist: {crop_root}")

    archives = sorted(
        crop_root.glob("*.zip"), key=lambda path: clean_estate_name(path.name)
    )
    if not archives:
        raise SystemExit(f"No ZIP archives found directly under: {crop_root}")

    run_folder = output_root / datetime.now().strftime(
        "estate_audit_v301_%Y%m%d_%H%M%S"
    )
    run_folder.mkdir(parents=True, exist_ok=False)

    print(f"Audit run folder: {run_folder}")
    print(f"ZIP archives found: {len(archives)}")
    print("Reader mode: exact historical 'All Records' schema")
    print("This audit is read-only and changes no live model or portal.")

    started = time.time()
    rejected_samples: list[dict[str, Any]] = []
    estate_rows: list[dict[str, Any]] = []
    workbook_rows: list[WorkbookAudit] = []
    alias_rows: list[dict[str, str]] = []
    readiness_json: list[dict[str, Any]] = []

    today = date.today()
    for index, archive_path in enumerate(archives, start=1):
        print(f"[{index}/{len(archives)}] Auditing {archive_path.name}", flush=True)
        acc, workbooks, aliases = audit_archive(
            archive_path, rejected_samples, args.max_rejected_samples
        )
        workbook_rows.extend(workbooks)
        alias_rows.extend(aliases)

        score, status, reasons = score_estate(acc, today)
        invalid_rate = (
            acc.invalid_required_values / max(1, acc.plucking_rows) * 100
        )
        duplicate_rate = acc.duplicate_weighing_id / max(1, acc.rows_scanned) * 100

        estate_row = {
            "estate": acc.estate,
            "archive_name": acc.archive_name,
            "readiness_status": status,
            "readiness_score": score,
            "workbook_count": acc.workbook_count,
            "readable_workbooks": acc.readable_workbooks,
            "failed_workbooks": acc.failed_workbooks,
            "all_records_sheets": acc.all_records_sheets,
            "rows_scanned": acc.rows_scanned,
            "plucking_rows": acc.plucking_rows,
            "valid_rows": acc.valid_rows,
            "invalid_required_values": acc.invalid_required_values,
            "invalid_required_rate_pct": round(invalid_rate, 4),
            "non_positive_net_weight": acc.non_positive_net_weight,
            "duplicate_weighing_id": acc.duplicate_weighing_id,
            "duplicate_weighing_rate_pct": round(duplicate_rate, 4),
            "date_min": acc.date_min.isoformat() if acc.date_min else "",
            "date_max": acc.date_max.isoformat() if acc.date_max else "",
            "data_age_days": (today - acc.date_max).days if acc.date_max else "",
            "employee_count": len(acc.employees),
            "field_count": len(acc.fields),
            "division_count": len(acc.divisions),
            "estate_id_count": len(acc.estate_ids),
            "estate_ids": "|".join(sorted(acc.estate_ids)),
            "total_net_kg": round(acc.total_net_kg, 4),
            "identity_mismatch_count": len(acc.identity_mismatches),
            "identity_mismatch_workbooks": "|".join(acc.identity_mismatches),
            "blocking_reasons": " | ".join(reasons),
            "errors": " | ".join(acc.errors),
        }
        estate_rows.append(estate_row)
        readiness_json.append({
            "estate": acc.estate,
            "status": status,
            "score": score,
            "blocking_reasons": reasons,
            "identity_mismatch_workbooks": acc.identity_mismatches,
            "date_max": estate_row["date_max"],
            "valid_rows": acc.valid_rows,
        })

    estate_fields = [
        "estate", "archive_name", "readiness_status", "readiness_score",
        "workbook_count", "readable_workbooks", "failed_workbooks",
        "all_records_sheets", "rows_scanned", "plucking_rows", "valid_rows",
        "invalid_required_values", "invalid_required_rate_pct",
        "non_positive_net_weight", "duplicate_weighing_id",
        "duplicate_weighing_rate_pct", "date_min", "date_max", "data_age_days",
        "employee_count", "field_count", "division_count", "estate_id_count",
        "estate_ids", "total_net_kg", "identity_mismatch_count",
        "identity_mismatch_workbooks", "blocking_reasons", "errors",
    ]
    workbook_fields = list(asdict(workbook_rows[0]).keys()) if workbook_rows else [
        field.name for field in WorkbookAudit.__dataclass_fields__.values()
    ]
    alias_fields = [
        "archive_estate", "archive_name", "internal_workbook", "internal_path",
        "internal_estate_guess", "canonical_estate", "identity_status",
    ]
    rejected_fields = [
        "archive_estate", "archive_name", "workbook_name", "row_number",
        "employee_alias", "division", "field", "date_value",
        "net_weight_value", "reason",
    ]

    write_csv(run_folder / "estate_data_audit.csv", estate_rows, estate_fields)
    write_csv(
        run_folder / "estate_file_identity_audit.csv",
        [asdict(row) for row in workbook_rows],
        workbook_fields,
    )
    write_csv(run_folder / "estate_alias_mapping.csv", alias_rows, alias_fields)
    write_csv(
        run_folder / "rejected_rows_sample.csv",
        rejected_samples,
        rejected_fields,
    )

    counts = Counter(row["readiness_status"] for row in estate_rows)
    mismatch_estates = [
        row["estate"] for row in estate_rows
        if int(row["identity_mismatch_count"]) > 0
    ]
    duration_minutes = round((time.time() - started) / 60, 2)

    summary = {
        "status": (
            "PASS"
            if len(archives) == args.expected_estates
            and counts.get("NOT_READY", 0) == 0
            else "CONDITIONAL"
        ),
        "package_version": PACKAGE_VERSION,
        "run_folder": str(run_folder),
        "archives_found": len(archives),
        "expected_estates": args.expected_estates,
        "ready": counts.get("READY", 0),
        "conditional": counts.get("CONDITIONAL", 0),
        "not_ready": counts.get("NOT_READY", 0),
        "identity_mismatch_estates": mismatch_estates,
        "rejected_row_samples": len(rejected_samples),
        "duration_minutes": duration_minutes,
        "live_models_changed": False,
        "portal_changed": False,
        "rl_started": False,
    }
    (run_folder / "audit_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    (run_folder / "estate_readiness.json").write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "package_version": PACKAGE_VERSION,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "estates": readiness_json,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    report_lines = [
        "# TTE Data Identity and Readiness Audit v3.0.1",
        "",
        f"- Archives: **{len(archives)} / {args.expected_estates}**",
        f"- READY: **{counts.get('READY', 0)}**",
        f"- CONDITIONAL: **{counts.get('CONDITIONAL', 0)}**",
        f"- NOT READY: **{counts.get('NOT_READY', 0)}**",
        f"- Duration: **{duration_minutes} minutes**",
        "",
        "## Identity mismatches",
        "",
    ]
    report_lines.extend(
        [f"- {estate}" for estate in mismatch_estates]
        or ["- None detected"]
    )
    report_lines.extend([
        "",
        "## Safety",
        "",
        "This audit is read-only. No crop model, productivity model, portal, "
        "live allocator or RL policy was changed.",
    ])
    (run_folder / "data_quality_report.md").write_text(
        "\n".join(report_lines) + "\n", encoding="utf-8"
    )

    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "LATEST_DATA_AUDIT.txt").write_text(
        str(run_folder), encoding="utf-8"
    )

    print("")
    print("DATA IDENTITY AND READINESS AUDIT v3.0.1 FINISHED")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
