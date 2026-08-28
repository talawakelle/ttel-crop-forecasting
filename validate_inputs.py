from __future__ import annotations

import argparse
from pathlib import Path

from src.data_contract import CONTRACTS, read_input_bundle, validate_bundle


def main():
    parser = argparse.ArgumentParser(description="Validate multi-estate GAP forecasting inputs before model training.")
    parser.add_argument("input", help="Standard collection workbook or directory of CSV files")
    parser.add_argument("--report", default="outputs/input_validation_report.csv")
    args = parser.parse_args()

    frames = read_input_bundle(args.input)
    missing = sorted(set(CONTRACTS) - set(frames))
    _, issues = validate_bundle(frames)
    for dataset in missing:
        issues.loc[len(issues)] = [dataset, "WARNING", "missing_dataset", "Dataset was not supplied.", None]

    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    issues.to_csv(report, index=False)
    errors = int((issues["severity"] == "ERROR").sum()) if not issues.empty else 0
    warnings = int((issues["severity"] == "WARNING").sum()) if not issues.empty else 0
    print(f"Validation complete: {errors} errors, {warnings} warnings. Report: {report.resolve()}")
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()

