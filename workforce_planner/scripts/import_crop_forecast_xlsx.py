from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import argparse
import hashlib
import json
import re

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CELL_RE = re.compile(r"([A-Z]+)([0-9]+)")


def excel_date(value: object) -> str:
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    number = float(value)
    return (datetime(1899, 12, 30) + timedelta(days=number)).date().isoformat()


def column_index(cell_ref: str) -> int:
    match = CELL_RE.fullmatch(cell_ref)
    if not match:
        raise ValueError(f"Invalid cell reference: {cell_ref}")
    result = 0
    for char in match.group(1):
        result = result * 26 + ord(char) - 64
    return result - 1


def read_shared_strings(archive: ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    values = []
    for item in root.findall(f"{{{NS_MAIN}}}si"):
        values.append("".join(node.text or "" for node in item.iter(f"{{{NS_MAIN}}}t")))
    return values


def sheet_path(archive: ZipFile, sheet_name: str) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationship_id = None
    for node in workbook.findall(f".//{{{NS_MAIN}}}sheet"):
        if node.attrib.get("name") == sheet_name:
            relationship_id = node.attrib.get(f"{{{NS_REL}}}id")
            break
    if not relationship_id:
        raise ValueError(f"Worksheet not found: {sheet_name}")
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    for node in relationships.findall(f"{{{NS_PKG_REL}}}Relationship"):
        if node.attrib.get("Id") == relationship_id:
            target = node.attrib["Target"].lstrip("/")
            if target.startswith("xl/"):
                return target
            return f"xl/{target}"
    raise ValueError(f"Worksheet relationship missing: {sheet_name}")


def read_sheet_rows(path: Path, sheet_name: str) -> list[list[object | None]]:
    with ZipFile(path) as archive:
        shared = read_shared_strings(archive)
        root = ET.fromstring(archive.read(sheet_path(archive, sheet_name)))
    rows: list[list[object | None]] = []
    for row_node in root.findall(f".//{{{NS_MAIN}}}row"):
        cells: dict[int, object | None] = {}
        max_index = -1
        for cell in row_node.findall(f"{{{NS_MAIN}}}c"):
            ref = cell.attrib.get("r", "")
            index = column_index(ref)
            max_index = max(max_index, index)
            kind = cell.attrib.get("t")
            value_node = cell.find(f"{{{NS_MAIN}}}v")
            if kind == "inlineStr":
                inline = cell.find(f"{{{NS_MAIN}}}is")
                value = "".join(node.text or "" for node in inline.iter(f"{{{NS_MAIN}}}t")) if inline is not None else ""
            elif value_node is None:
                value = None
            elif kind == "s":
                value = shared[int(value_node.text or 0)]
            elif kind == "b":
                value = (value_node.text == "1")
            else:
                raw = value_node.text or ""
                try:
                    numeric = float(raw)
                    value = int(numeric) if numeric.is_integer() else numeric
                except ValueError:
                    value = raw
            cells[index] = value
        rows.append([cells.get(index) for index in range(max_index + 1)] if max_index >= 0 else [])
    return rows


def normalize_forecast(source: Path) -> dict:
    rows = read_sheet_rows(source, "Forecast")
    header_index = next(
        index for index, row in enumerate(rows)
        if row and row[0] == "Estate" and "Forecast kg" in row
    )
    headers = [str(value) if value is not None else "" for value in rows[header_index]]
    records = []
    for row in rows[header_index + 1:]:
        if not row or not row[0]:
            break
        record = dict(zip(headers, row))
        records.append({
            "estate": str(record["Estate"]),
            "horizon": int(record["Horizon"]),
            "origin_week_ending": excel_date(record["Origin week ending"]),
            "forecast_start": excel_date(record["Forecast start"]),
            "forecast_end": excel_date(record["Forecast end"]),
            "forecast_kg": float(record["Forecast kg"]),
            "lower_80_kg": float(record["Lower 80% kg"]),
            "upper_80_kg": float(record["Upper 80% kg"]),
            "selected_method": str(record["Selected method"]),
            "validation_wape": float(record["Validation WAPE"]),
        })
    if not records:
        raise ValueError("No forecast rows were found")
    return {
        "schema_version": 1,
        "estate": records[0]["estate"],
        "forecast_origin": records[0]["origin_week_ending"],
        "source_file": source.name,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_model_scope": "estate-level weekly net green-leaf crop",
        "field_schedule_scope": "not modelled; supervisor-selected template-day mix required",
        "imported_at": datetime.now().isoformat(timespec="seconds"),
        "periods": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import the Forecast worksheet into the employee planner")
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "crop_forecast_clarendon.json",
    )
    args = parser.parse_args()
    payload = normalize_forecast(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "estate": payload["estate"],
        "forecast_origin": payload["forecast_origin"],
        "forecast_start": payload["periods"][0]["forecast_start"],
        "forecast_end": payload["periods"][-1]["forecast_end"],
        "periods": len(payload["periods"]),
    }, indent=2))


if __name__ == "__main__":
    main()
