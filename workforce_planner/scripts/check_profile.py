from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the active workforce profile")
    parser.add_argument("--profile", type=Path, default=ROOT / "data" / "workforce_profile.json")
    parser.add_argument("--require-full", action="store_true")
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    metadata = profile["metadata"]
    summary = {
        "source_name": metadata.get("source_name"),
        "source_kind": metadata.get("source_kind"),
        "date_min": metadata.get("date_min"),
        "date_max": metadata.get("date_max"),
        "source_rows_scanned": metadata.get("source_rows_scanned"),
        "source_rows_used": metadata.get("source_rows_used"),
        "employees": metadata.get("employee_count"),
        "fields": metadata.get("field_count"),
        "divisions": metadata.get("division_count"),
        "days": metadata.get("day_count"),
        "profile_status": "FULL HISTORICAL DATA" if metadata.get("source_rows_scanned", 0) > 400_000 else "LIMITED DATA",
    }
    print(json.dumps(summary, indent=2))
    if args.require_full:
        valid = (
            metadata.get("source_kind") == "historical_clarendon_xlsx_archive"
            and metadata.get("source_rows_scanned") == 428_401
            and metadata.get("date_min") == "2021-04-01"
            and metadata.get("date_max") == "2026-06-15"
            and metadata.get("source_sha256") == "cadfaa5ab4e783acf89ecd2f194ddc55f2e7726f1f752ee9441518db79286be3"
        )
        if not valid:
            print("PROFILE ERROR: the active profile does not match the validated full Clarendon archive.", file=sys.stderr)
            return 1
    print("PROFILE READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
