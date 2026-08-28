from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path


def choose_split(date_min: str, date_max: str) -> dict:
    start = date.fromisoformat(date_min)
    end = date.fromisoformat(date_max)
    span_days = (end - start).days + 1
    if span_days < 300:
        raise ValueError(f"At least 300 calendar days are required; found {span_days}")
    if span_days >= 900:
        holdout_days = 180
    elif span_days >= 730:
        holdout_days = 150
    else:
        holdout_days = 60
    # Retain at least 180 calendar days for training even for short-history estates.
    holdout_days = min(holdout_days, max(45, (span_days - 180) // 2))
    test_start = end - timedelta(days=holdout_days - 1)
    validation_end = test_start - timedelta(days=1)
    validation_start = validation_end - timedelta(days=holdout_days - 1)
    train_end = validation_start - timedelta(days=1)
    training_days = (train_end - start).days + 1
    if training_days < 180:
        raise ValueError(f"Split leaves only {training_days} training days")
    return {
        "date_min": date_min,
        "date_max": date_max,
        "calendar_span_days": span_days,
        "train_end": train_end.isoformat(),
        "validation_start": validation_start.isoformat(),
        "validation_end": validation_end.isoformat(),
        "test_start": test_start.isoformat(),
        "holdout_days_each": holdout_days,
        "training_days": training_days,
        "history_class": "standard" if span_days >= 730 else "conditional short-history provisional",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    metadata = profile["metadata"]
    result = choose_split(metadata["date_min"], metadata["date_max"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
