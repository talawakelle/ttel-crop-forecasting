from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for estate_dir in sorted(p for p in args.run_root.iterdir() if p.is_dir() and (p / "data").is_dir()):
        profile_path = estate_dir / "data" / "workforce_profile.json"
        split_path = estate_dir / "data" / "temporal_split.json"
        approved_path = estate_dir / "models" / "productivity_metrics.json"
        rejected_path = estate_dir / "models" / "productivity_rejected_metrics.json"
        if not profile_path.exists() or not split_path.exists():
            continue
        profile = read_json(profile_path)["metadata"]
        split = read_json(split_path)
        report_path = approved_path if approved_path.exists() else rejected_path
        report = read_json(report_path) if report_path.exists() else {}
        test = report.get("test_metrics") or report.get("base_test_metrics") or {}
        rows.append({
            "estate": estate_dir.name,
            "status": "APPROVED_CANDIDATE" if report.get("approved") else "REJECTED_OR_FAILED",
            "history_class": split["history_class"],
            "date_min": profile.get("date_min"),
            "date_max": profile.get("date_max"),
            "employees": profile.get("employee_count"),
            "fields": profile.get("field_count"),
            "divisions": profile.get("division_count"),
            "training_device": report.get("training_device"),
            "gpu_name": report.get("gpu_name"),
            "base_approved": report.get("base_approved"),
            "weather_approved": report.get("weather_approved"),
            "test_model_mae_kg": test.get("model_mae_kg"),
            "test_baseline_mae_kg": test.get("baseline_mae_kg"),
            "test_mae_improvement_pct": test.get("mae_improvement_pct"),
            "training_seconds": report.get("training_seconds"),
            "live_use_approved": False,
            "shadow_mode_required": True,
        })
    output_csv = args.run_root / "productivity_portfolio_summary.csv"
    if rows:
        with output_csv.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    payload = {
        "estate_candidates": len(rows),
        "approved_candidates": sum(row["status"] == "APPROVED_CANDIDATE" for row in rows),
        "rejected_or_failed": sum(row["status"] != "APPROVED_CANDIDATE" for row in rows),
        "live_use_approved": False,
        "required_next_gate": "estate-specific operational shadow mode with attendance, skills, restrictions, field demand and supervisor approval",
        "rows": rows,
    }
    (args.run_root / "productivity_portfolio_summary.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
