from __future__ import annotations

import argparse
import io
import json
import re
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook


ALIASES = {
    "bambrakelly": "bambarakelly",
    "eildonhall": "eildonhall",
    "glassugh": "glassaugh",
    "nuwaraeliya": "nuwaraeliya",
    "oliphant": "oilphant",
}


def normalized(value: str) -> str:
    key = re.sub(r"[^a-z0-9]", "", value.lower())
    return ALIASES.get(key, key)


def workbook_sources(source: Path):
    if source.is_dir():
        for path in sorted(source.glob("*.xlsx")):
            yield path.name, path
    elif source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as archive:
            members = [
                name for name in archive.namelist()
                if "/output/" in name.replace("\\", "/") and name.lower().endswith(".xlsx")
            ]
            for name in sorted(members):
                yield Path(name).name, io.BytesIO(archive.read(name))
    else:
        raise ValueError("Source must be the prompt_automation ZIP or its output directory.")


def estate_from_filename(filename: str, project_lookup: dict[str, str]):
    stem = Path(filename).stem
    estate_part = stem.split("_", 1)[1] if "_" in stem else stem
    return project_lookup.get(normalized(estate_part))


def read_workbook(file_object, filename: str, estate: str):
    wb = load_workbook(file_object, read_only=True, data_only=True, keep_links=False)
    if "All Records" not in wb.sheetnames:
        wb.close()
        return [], {"file": filename, "estate": estate, "status": "skipped_no_all_records"}
    ws = wb["All Records"]
    header = [str(value).strip() if value is not None else "" for value in next(ws.iter_rows(min_row=1, max_row=1, values_only=True))]
    index = {name: position for position, name in enumerate(header)}
    required = ["date", "weighing_id", "net_weight"]
    missing = [column for column in required if column not in index]
    if missing:
        wb.close()
        raise ValueError(f"{filename} is missing {missing}")
    daily = defaultdict(lambda: {"actual_kg": 0.0, "crop_records": 0})
    seen = set()
    duplicate_rows = 0
    raw_rows = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        raw_rows += 1
        day = pd.to_datetime(row[index["date"]], errors="coerce")
        if pd.isna(day):
            continue
        weighing_id = str(row[index["weighing_id"]])
        if weighing_id in seen:
            duplicate_rows += 1
            continue
        seen.add(weighing_id)
        try:
            net = float(row[index["net_weight"]] or 0)
        except (TypeError, ValueError):
            continue
        record = daily[day.date().isoformat()]
        record["actual_kg"] += net
        record["crop_records"] += 1

    summary_daily = {}
    if "Monthly Summary" in wb.sheetnames:
        summary = wb["Monthly Summary"]
        for values in summary.iter_rows(min_row=2, values_only=True):
            label = values[0]
            if not isinstance(label, str) or not label.endswith(" - Net Kg"):
                continue
            month_text = label.removesuffix(" - Net Kg")
            month = datetime.strptime(month_text, "%B %Y")
            for day_number, value in enumerate(values[1:32], start=1):
                if value in (None, ""):
                    continue
                try:
                    date_text = datetime(month.year, month.month, day_number).date().isoformat()
                except ValueError:
                    continue
                summary_daily[date_text] = float(value)
    wb.close()

    rows = [{
        "estate": estate,
        "date": day,
        "actual_kg": round(values["actual_kg"], 2),
        "crop_records": int(values["crop_records"]),
        "source_system": "PROMPT",
        "source_workbook": filename,
    } for day, values in sorted(daily.items())]
    differences = [abs(values["actual_kg"] - summary_daily.get(day, values["actual_kg"])) for day, values in daily.items()]
    audit = {
        "file": filename,
        "estate": estate,
        "status": "imported" if rows else "empty",
        "raw_rows": raw_rows,
        "daily_rows": len(rows),
        "date_min": rows[0]["date"] if rows else None,
        "date_max": rows[-1]["date"] if rows else None,
        "duplicate_weighing_ids_removed": duplicate_rows,
        "max_daily_summary_difference_kg": round(max(differences), 2) if differences else 0.0,
    }
    return rows, audit


def main():
    parser = argparse.ArgumentParser(description="Import privacy-safe daily estate crop totals from PROMPT automation outputs.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--portfolio", type=Path, default=Path("outputs/portfolio_summary.csv"))
    parser.add_argument("--output", type=Path, default=Path("outputs/prompt_daily_actuals.csv"))
    parser.add_argument("--audit", type=Path, default=Path("outputs/prompt_actuals_import_audit.json"))
    args = parser.parse_args()

    portfolio = pd.read_csv(args.portfolio)
    project_lookup = {normalized(estate): estate for estate in portfolio["estate"].astype(str)}
    all_rows = []
    audits = []
    ignored = []
    for filename, file_object in workbook_sources(args.source):
        estate = estate_from_filename(filename, project_lookup)
        if estate is None:
            ignored.append(filename)
            continue
        rows, audit = read_workbook(file_object, filename, estate)
        all_rows.extend(rows)
        audits.append(audit)
    if not all_rows:
        raise ValueError("No mapped estate actual records were found.")
    frame = pd.DataFrame(all_rows).sort_values(["estate", "date"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output, index=False)
    report = {
        "imported_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": args.source.name,
        "privacy_control": "Only estate/date aggregate net kg and record counts retained; no employee identifiers retained.",
        "mapped_estates": int(frame["estate"].nunique()),
        "daily_rows": int(len(frame)),
        "date_min": frame["date"].min(),
        "date_max": frame["date"].max(),
        "max_daily_summary_difference_kg": max(float(a["max_daily_summary_difference_kg"]) for a in audits),
        "workbooks": audits,
        "ignored_non_project_workbooks": ignored,
    }
    args.audit.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in [
        "mapped_estates", "daily_rows", "date_min", "date_max", "max_daily_summary_difference_kg"
    ]}, indent=2))


if __name__ == "__main__":
    main()
