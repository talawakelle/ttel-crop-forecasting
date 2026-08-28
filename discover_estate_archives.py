from __future__ import annotations

import argparse
import csv
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "workforce_planner" / "v2" / "config" / "estate_source_manifest.csv"
ALIASES = ROOT / "workforce_planner" / "v2" / "config" / "estate_alias_mapping.csv"


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def load_registry() -> tuple[list[str], dict[str, list[str]]]:
    with MANIFEST.open(newline="", encoding="utf-8-sig") as handle:
        estates = [row["estate"] for row in csv.DictReader(handle) if row["enabled"].upper() == "TRUE"]
    aliases: dict[str, list[str]] = defaultdict(list)
    with ALIASES.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            aliases[row["canonical_estate"]].append(normalized(row["alias"]))
    for estate in estates:
        aliases[estate].append(normalized(estate))
    return estates, aliases


def archive_score(path: Path, estate_aliases: list[str]) -> tuple[int, float]:
    stem = normalized(path.stem)
    simplified = re.sub(r"output\d*$", "", stem)
    exact = any(stem == alias or simplified == alias for alias in estate_aliases)
    return (2 if exact else 0, path.stat().st_mtime)


def validate_zip(path: Path) -> tuple[bool, int, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            workbooks = [name for name in archive.namelist() if name.casefold().endswith(".xlsx")]
            if not workbooks:
                return False, 0, "No XLSX workbooks inside archive"
            bad = archive.testzip()
            if bad:
                return False, len(workbooks), f"Corrupt member: {bad}"
            return True, len(workbooks), ""
    except (OSError, zipfile.BadZipFile) as exc:
        return False, 0, str(exc)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crop-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.crop_root.is_dir():
        raise FileNotFoundError(args.crop_root)
    estates, aliases = load_registry()
    archives = list(args.crop_root.rglob("*.zip"))
    results = []
    missing = []
    for estate in estates:
        scored = sorted(
            ((archive_score(path, aliases[estate]), path) for path in archives),
            key=lambda item: item[0],
            reverse=True,
        )
        candidates = [path for score, path in scored if score[0] > 0]
        if not candidates:
            missing.append(estate)
            results.append({
                "estate": estate, "crop_source": "", "source_status": "MISSING",
                "workbook_count": 0, "alternative_matches": "",
            })
            continue
        selected = None
        workbook_count = 0
        rejected = []
        last_error = "No valid ZIP candidate"
        for candidate in candidates:
            valid, candidate_count, error = validate_zip(candidate)
            if valid:
                selected = candidate
                workbook_count = candidate_count
                break
            rejected.append(f"{candidate.resolve()} [INVALID: {error}]")
            last_error = error
        if selected is None:
            selected = candidates[0]
        alternatives = []
        for candidate in candidates:
            if candidate == selected:
                continue
            candidate_valid, _, candidate_error = validate_zip(candidate)
            suffix = "READY" if candidate_valid else f"INVALID: {candidate_error}"
            alternatives.append(f"{candidate.resolve()} [{suffix}]")
        results.append({
            "estate": estate,
            "crop_source": str(selected.resolve()),
            "source_status": "READY" if workbook_count else f"INVALID: {last_error}",
            "workbook_count": workbook_count,
            "alternative_matches": "; ".join(alternatives),
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    invalid = [row for row in results if row["source_status"] != "READY"]
    print(json.dumps({
        "status": "PASS" if not invalid and len(results) == 33 else "FAIL",
        "crop_root": str(args.crop_root.resolve()),
        "archives_scanned": len(archives),
        "estates": len(results),
        "ready": len(results) - len(invalid),
        "invalid_or_missing": invalid,
        "output": str(args.output.resolve()),
    }, indent=2))
    if invalid or len(results) != 33:
        raise SystemExit("All 33 valid estate ZIP archives are required")


if __name__ == "__main__":
    main()
