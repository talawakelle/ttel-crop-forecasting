from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import openpyxl


CRITICAL_COLUMNS = {
    "date", "employee_id", "net_weight", "field_code", "division_name", "type"
}


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = text(value)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw[:10], fmt).date()
        except ValueError:
            continue
    return None


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and result not in (float("inf"), float("-inf")) else None


def normalized(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", text(value).lower())


def sha256_paths(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: str(item).lower()):
        digest.update(path.name.encode("utf-8"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    enabled = [row for row in rows if row.get("enabled", "").upper() == "TRUE"]
    if len(enabled) != 33:
        raise ValueError(f"Expected 33 enabled estates; found {len(enabled)}")
    if len({row["estate"] for row in enabled}) != len(enabled):
        raise ValueError("Estate names are not unique")
    if len({(row["plantation_id"], row["estate_id"]) for row in enabled}) != len(enabled):
        raise ValueError("Plantation/estate ID pairs are not unique")
    return enabled


def sources_for(row: dict[str, str], upload_root: Path, workspace_root: Path):
    kind = row["source_kind"]
    locator = row["source_locator"]
    if kind == "zip":
        archive = upload_root / locator
        if not archive.exists():
            raise FileNotFoundError(archive)
        with zipfile.ZipFile(archive) as bundle:
            members = sorted(name for name in bundle.namelist() if name.lower().endswith(".xlsx"))
            if not members:
                raise ValueError(f"No XLSX members in {archive}")
            for name in members:
                yield Path(name).name, io.BytesIO(bundle.read(name))
        return
    if kind == "files":
        paths = [upload_root / value for value in locator.split(";") if value]
    elif kind == "directory":
        paths = sorted((workspace_root / locator).glob("*.xlsx"))
    else:
        raise ValueError(f"Unsupported source kind: {kind}")
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError("; ".join(missing))
    if not paths:
        raise ValueError(f"No source workbooks for {row['estate']}")
    for path in paths:
        yield path.name, path


def source_hash(row: dict[str, str], upload_root: Path, workspace_root: Path) -> str:
    if row["source_kind"] == "zip":
        paths = [upload_root / row["source_locator"]]
    elif row["source_kind"] == "files":
        paths = [upload_root / value for value in row["source_locator"].split(";") if value]
    else:
        paths = sorted((workspace_root / row["source_locator"]).glob("*.xlsx"))
    return sha256_paths(paths)


def audit_estate(payload: dict[str, Any]) -> dict[str, Any]:
    row = payload["manifest"]
    upload_root = Path(payload["upload_root"])
    workspace_root = Path(payload["workspace_root"])
    estate = row["estate"]
    expected_estate_id = row["estate_id"]
    expected_plantation_id = row["plantation_id"]

    counts = Counter()
    missing_columns: dict[str, list[str]] = {}
    workbook_names: list[str] = []
    workbook_estate_ids: set[str] = set()
    workbook_plantation_ids: set[str] = set()
    dates: set[date] = set()
    employees: set[str] = set()
    divisions: set[str] = set()
    fields: set[str] = set()
    work_codes: set[str] = set()
    weighing_ids: set[str] = set()
    employee_internal_links: dict[str, set[str]] = defaultdict(set)

    for workbook_name, workbook_input in sources_for(row, upload_root, workspace_root):
        workbook_names.append(workbook_name)
        workbook = openpyxl.load_workbook(
            workbook_input, read_only=True, data_only=True, keep_links=False
        )
        try:
            if "All Records" not in workbook.sheetnames:
                missing_columns[workbook_name] = ["All Records sheet"]
                continue
            worksheet = workbook["All Records"]
            values = worksheet.iter_rows(values_only=True)
            headers = [text(value).lower() for value in next(values, ())]
            positions = {header: index for index, header in enumerate(headers)}
            missing = sorted(CRITICAL_COLUMNS.difference(positions))
            if missing:
                missing_columns[workbook_name] = missing
                continue

            def get(record, column):
                index = positions.get(column)
                return record[index] if index is not None and index < len(record) else None

            for record in values:
                counts["raw_rows"] += 1
                estate_id = text(get(record, "estate_id"))
                plantation_id = text(get(record, "plantation_id"))
                if estate_id:
                    workbook_estate_ids.add(estate_id)
                if plantation_id:
                    workbook_plantation_ids.add(plantation_id)

                weighing_id = text(get(record, "weighing_id"))
                if not weighing_id:
                    counts["missing_weighing_id"] += 1
                elif weighing_id in weighing_ids:
                    counts["duplicate_weighing_id"] += 1
                    continue
                else:
                    weighing_ids.add(weighing_id)

                weight = number(get(record, "net_weight"))
                if weight is None:
                    counts["missing_or_invalid_weight"] += 1
                elif weight <= 0:
                    counts["zero_or_negative_weight"] += 1

                work_type = text(get(record, "type"))
                work_code = text(get(record, "code")) or work_type
                if work_code:
                    work_codes.add(work_code)
                if "PLUCK" not in work_type.upper():
                    counts["non_plucking_work"] += 1
                    continue
                counts["plucking_rows"] += 1

                employee_id = text(get(record, "employee_id"))
                internal_number = text(get(record, "employee_internal_no"))
                employee = employee_id or internal_number
                division = text(get(record, "division_id")) or text(get(record, "division_name"))
                field = text(get(record, "field_code")) or text(get(record, "field_name"))
                record_date = day(get(record, "date"))
                if not employee:
                    counts["missing_employee_id"] += 1
                if not division:
                    counts["missing_division_id"] += 1
                if not field:
                    counts["missing_field_id"] += 1
                if record_date is None:
                    counts["missing_or_invalid_date"] += 1
                if weight is None or weight <= 0:
                    counts["invalid_plucking_weight"] += 1
                if not employee or not division or not field or record_date is None or weight is None or weight <= 0:
                    counts["rejected_plucking_rows"] += 1
                    continue

                key = f"{expected_plantation_id}|{expected_estate_id}|{employee}"
                employees.add(key)
                divisions.add(division)
                fields.add(f"{division}|{field}")
                dates.add(record_date)
                if employee_id and internal_number:
                    employee_internal_links[employee_id].add(internal_number)
                counts["valid_plucking_rows"] += 1
                counts["valid_plucking_kg"] += weight
        finally:
            workbook.close()

    identity_mismatch = (
        workbook_estate_ids != {expected_estate_id}
        or workbook_plantation_ids != {expected_plantation_id}
    )
    conflicting_employee_identities = sum(
        1 for values in employee_internal_links.values() if len(values) > 1
    )
    ordered_dates = sorted(dates)
    date_min = ordered_dates[0] if ordered_dates else None
    date_max = ordered_dates[-1] if ordered_dates else None
    calendar_days = (date_max - date_min).days + 1 if date_min and date_max else 0
    calendar_dates_without_plucking = calendar_days - len(dates)

    if date_max:
        test_start = date_max - timedelta(days=181)
        validation_end = test_start - timedelta(days=1)
        validation_start = test_start - timedelta(days=182)
        training_end = validation_start - timedelta(days=1)
    else:
        test_start = validation_start = validation_end = training_end = None
    split_counts = {
        "training_days": sum(item <= training_end for item in dates) if training_end else 0,
        "validation_days": sum(validation_start <= item <= validation_end for item in dates) if validation_start else 0,
        "test_days": sum(item >= test_start for item in dates) if test_start else 0,
    }

    blockers = []
    if missing_columns:
        blockers.append("critical columns or All Records sheet missing")
    if identity_mismatch:
        blockers.append("estate or plantation identity mismatch")
    if counts["valid_plucking_rows"] == 0:
        blockers.append("no valid plucking rows")
    if len(employees) < 20:
        blockers.append("fewer than 20 employees")
    if len(fields) < 5:
        blockers.append("fewer than 5 fields")

    if blockers:
        readiness = "NOT_READY"
    elif len(dates) >= 730 and split_counts["training_days"] >= 365 and split_counts["validation_days"] >= 90 and split_counts["test_days"] >= 90:
        readiness = "READY_FOR_MODEL_COMPARISON"
    elif len(dates) >= 270:
        readiness = "CONDITIONAL_SHORT_HISTORY"
    else:
        readiness = "NOT_READY_SHORT_HISTORY"

    audit = {
        "estate": estate,
        "plantation_id": expected_plantation_id,
        "estate_id": expected_estate_id,
        "operational_category": row["operational_category"],
        "identity_status": row["identity_status"],
        "source_kind": row["source_kind"],
        "source_locator": row["source_locator"],
        "source_sha256": source_hash(row, upload_root, workspace_root),
        "workbook_count": len(workbook_names),
        "workbook_names": workbook_names,
        "observed_estate_ids": sorted(workbook_estate_ids),
        "observed_plantation_ids": sorted(workbook_plantation_ids),
        "identity_mismatch": identity_mismatch,
        "missing_columns": missing_columns,
        "raw_rows": int(counts["raw_rows"]),
        "valid_plucking_rows": int(counts["valid_plucking_rows"]),
        "valid_plucking_kg": round(float(counts["valid_plucking_kg"]), 3),
        "employees": len(employees),
        "divisions": len(divisions),
        "fields": len(fields),
        "work_codes": len(work_codes),
        "date_min": date_min.isoformat() if date_min else None,
        "date_max": date_max.isoformat() if date_max else None,
        "observed_plucking_days": len(dates),
        "calendar_days": calendar_days,
        "calendar_dates_without_valid_plucking": calendar_dates_without_plucking,
        "missing_employee_ids": int(counts["missing_employee_id"]),
        "missing_field_ids": int(counts["missing_field_id"]),
        "missing_division_ids": int(counts["missing_division_id"]),
        "missing_or_invalid_weights": int(counts["missing_or_invalid_weight"]),
        "zero_or_negative_weights": int(counts["zero_or_negative_weight"]),
        "duplicate_weighments": int(counts["duplicate_weighing_id"]),
        "duplicate_employee_identities": conflicting_employee_identities,
        "non_plucking_rows": int(counts["non_plucking_work"]),
        "rejected_plucking_rows": int(counts["rejected_plucking_rows"]),
        "training_start": date_min.isoformat() if date_min else None,
        "training_end": training_end.isoformat() if training_end else None,
        "validation_start": validation_start.isoformat() if validation_start else None,
        "validation_end": validation_end.isoformat() if validation_end else None,
        "untouched_test_start": test_start.isoformat() if test_start else None,
        "untouched_test_end": date_max.isoformat() if date_max else None,
        **split_counts,
        "data_leakage_control": "Temporal split by whole date; threshold selection restricted to validation; untouched test remains sealed",
        "readiness": readiness,
        "blockers": blockers,
        "notes": row.get("notes", ""),
    }
    return audit


def flatten(audit: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "estate", "plantation_id", "estate_id", "operational_category", "identity_status",
        "source_kind", "source_locator", "workbook_count", "raw_rows", "valid_plucking_rows",
        "valid_plucking_kg", "employees", "divisions", "fields", "work_codes", "date_min",
        "date_max", "observed_plucking_days", "calendar_days",
        "calendar_dates_without_valid_plucking", "missing_employee_ids", "missing_field_ids",
        "missing_division_ids", "missing_or_invalid_weights", "zero_or_negative_weights",
        "duplicate_weighments", "duplicate_employee_identities", "non_plucking_rows",
        "rejected_plucking_rows", "training_start", "training_end", "validation_start",
        "validation_end", "untouched_test_start", "untouched_test_end", "training_days",
        "validation_days", "test_days", "identity_mismatch", "readiness", "notes"
    ]
    result = {key: audit.get(key) for key in keys}
    result["blockers"] = "; ".join(audit.get("blockers", []))
    result["missing_columns"] = json.dumps(audit.get("missing_columns", {}), separators=(",", ":"))
    return result


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def report_markdown(audits: list[dict[str, Any]], portfolio: dict[str, dict[str, str]]) -> str:
    statuses = Counter(item["readiness"] for item in audits)
    lines = [
        "# TTE Workforce Planner v2.0 — Multi-Estate Data Quality Report",
        "",
        "## Portfolio result",
        "",
        f"- Estates audited: **{len(audits)}**",
        f"- Raw records scanned: **{sum(item['raw_rows'] for item in audits):,}**",
        f"- Valid plucking records: **{sum(item['valid_plucking_rows'] for item in audits):,}**",
        f"- Ready for model comparison: **{statuses['READY_FOR_MODEL_COMPARISON']}**",
        f"- Conditional short history: **{statuses['CONDITIONAL_SHORT_HISTORY']}**",
        f"- Not ready: **{sum(value for key, value in statuses.items() if key.startswith('NOT_READY'))}**",
        "",
        "All 33 current crop-forecasting units are green-leaf tea estate labour datasets. Factory, bought-leaf, combined, rubber, cinnamon and reprocessing units from the workforce handover are **not present in this 33-estate crop portfolio** and must remain separate if supplied later.",
        "",
        "## Estate readiness",
        "",
        "| Estate | IDs | Period | Employees | Divisions | Fields | Valid rows | Workforce readiness | Crop forecast |",
        "|---|---:|---|---:|---:|---:|---:|---|---|",
    ]
    for item in audits:
        crop = portfolio.get(item["estate"], {})
        crop_status = crop.get("operational_status", "NOT FOUND")
        lines.append(
            f"| {item['estate']} | {item['plantation_id']}/{item['estate_id']} | "
            f"{item['date_min']} to {item['date_max']} | {item['employees']:,} | {item['divisions']:,} | "
            f"{item['fields']:,} | {item['valid_plucking_rows']:,} | {item['readiness']} | {crop_status} |"
        )
    lines += [
        "",
        "## Controls applied",
        "",
        "- Estate identity is based on plantation_id + estate_id, not member filenames.",
        "- Employee identity is scoped to plantation + estate and never merged across estates.",
        "- Duplicate weighing IDs are removed within each estate audit.",
        "- Training, validation and untouched-test periods are separated by complete dates.",
        "- No employee names or raw employee identifiers are written to audit outputs.",
        "- No GPU or RL training is authorized by this audit.",
        "- Calsay and Udaradella use recovered sources for this checkpoint and require valid replacement archives before production training.",
        "",
        "## Blocking production limitations",
        "",
        "1. Current crop forecasts are stale and must be retrained from refreshed actual crop and weather inputs.",
        "2. Employee attendance, leave, skill restrictions, legal constraints and supervisor approvals are not available in the crop archives.",
        "3. Field-level future demand is still an allocation of the estate crop forecast; it is not an independently validated field/day crop model.",
        "4. Estate-specific productivity model selection and untouched tests have not yet run.",
        "5. RL remains disabled until each estate passes deterministic planner, safety and shadow-mode gates.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--upload-root", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--portfolio-summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    payloads = [
        {
            "manifest": row,
            "upload_root": str(args.upload_root.resolve()),
            "workspace_root": str(args.workspace_root.resolve()),
        }
        for row in manifest
    ]
    audits = []
    if args.workers > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(audit_estate, payload): payload["manifest"]["estate"] for payload in payloads}
            for future in as_completed(futures):
                estate = futures[future]
                audit = future.result()
                audits.append(audit)
                print(f"AUDITED {estate}: {audit['readiness']}", flush=True)
    else:
        for payload in payloads:
            audit = audit_estate(payload)
            audits.append(audit)
            print(f"AUDITED {audit['estate']}: {audit['readiness']}", flush=True)
    audits.sort(key=lambda item: item["estate"])

    with args.portfolio_summary.open(newline="", encoding="utf-8-sig") as handle:
        portfolio = {row["estate"]: row for row in csv.DictReader(handle)}
    for item in audits:
        crop = portfolio.get(item["estate"], {})
        item["crop_forecast_training_status"] = crop.get("training_status")
        item["crop_forecast_origin"] = crop.get("forecast_origin")
        item["crop_forecast_data_freshness_status"] = crop.get("operational_status")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "estate_data_audit.csv", [flatten(item) for item in audits])
    rejected = []
    for item in audits:
        for reason in [
            "missing_employee_ids", "missing_field_ids", "missing_division_ids",
            "missing_or_invalid_weights", "zero_or_negative_weights", "duplicate_weighments",
            "rejected_plucking_rows",
        ]:
            rejected.append({"estate": item["estate"], "reason": reason, "row_count": item[reason]})
    write_csv(args.output_dir / "rejected_rows.csv", rejected)
    readiness = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "status": "PASS" if len(audits) == 33 and not any(item["identity_mismatch"] for item in audits) else "FAIL",
        "estates": len(audits),
        "raw_rows": sum(item["raw_rows"] for item in audits),
        "valid_plucking_rows": sum(item["valid_plucking_rows"] for item in audits),
        "readiness_counts": dict(Counter(item["readiness"] for item in audits)),
        "gpu_training_authorized": False,
        "rl_training_authorized": False,
        "estates_detail": audits,
    }
    (args.output_dir / "estate_readiness.json").write_text(json.dumps(readiness, indent=2), encoding="utf-8")
    (args.output_dir / "data_quality_report.md").write_text(
        report_markdown(audits, portfolio), encoding="utf-8"
    )
    print(json.dumps({key: readiness[key] for key in ["status", "estates", "raw_rows", "valid_plucking_rows", "readiness_counts", "gpu_training_authorized", "rl_training_authorized"]}, indent=2))


if __name__ == "__main__":
    main()
