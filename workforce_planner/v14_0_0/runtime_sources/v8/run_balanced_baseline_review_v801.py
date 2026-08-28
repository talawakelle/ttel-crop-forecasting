from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


VERSION = "8.0.1"
OPERATIONAL_STATUS = "DEVELOPMENT_SIMULATION_ONLY"


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def norm(value: Any) -> str:
    return "".join(ch for ch in clean(value).lower() if ch.isalnum())


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(clean(value).replace(",", ""))
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def parse_int(value: Any, default: int = 0) -> int:
    return int(round(parse_float(value, float(default))))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-evaluate CP-SAT vs greedy with material tolerance."
    )
    parser.add_argument("--comparison-run", required=True)
    parser.add_argument("--capacity-run", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--minimum-gate-pct", type=float, default=80.0)
    parser.add_argument("--absolute-tolerance-kg", type=float, default=2.0)
    parser.add_argument("--relative-tolerance-pct", type=float, default=0.05)
    parser.add_argument("--maximum-shortfall-rate-pct", type=float, default=0.10)
    args = parser.parse_args()

    comparison_run = Path(args.comparison_run).resolve()
    capacity_run = Path(args.capacity_run).resolve()
    output_root = Path(args.output_root).resolve()

    comparison_path = (
        comparison_run / "quality" / "cp_sat_vs_greedy_comparison.csv"
    )
    method_path = comparison_run / "quality" / "method_estate_results.csv"
    capacity_summary_path = (
        capacity_run / "quality" / "cp_sat_capacity_scenario_summary.csv"
    )

    for path in (comparison_path, method_path, capacity_summary_path):
        if not path.exists():
            raise SystemExit(f"Missing required input: {path}")

    comparison_rows = read_csv(comparison_path)
    method_rows = read_csv(method_path)
    capacity_summary_rows = read_csv(capacity_summary_path)

    if len(comparison_rows) != 66:
        raise SystemExit(
            f"Expected 66 estate-scenario comparisons but found {len(comparison_rows)}."
        )

    method_lookup: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in method_rows:
        key = (
            clean(row.get("method")).upper(),
            clean(row.get("scenario")).upper(),
            norm(row.get("estate")),
        )
        method_lookup[key] = row

    review_rows: list[dict[str, Any]] = []

    for row in comparison_rows:
        scenario = clean(row.get("scenario")).upper()
        estate = clean(row.get("estate"))
        estate_norm = norm(estate)

        cp = method_lookup.get(("CP_SAT", scenario, estate_norm))
        greedy = method_lookup.get(("GREEDY", scenario, estate_norm))
        if cp is None or greedy is None:
            raise RuntimeError(
                f"Missing method results for {scenario} / {estate}"
            )

        target = parse_float(cp.get("total_target_crop_kg"))
        cp_under = parse_float(cp.get("total_under_kg"))
        greedy_under = parse_float(greedy.get("total_under_kg"))
        cp_over = parse_float(cp.get("total_over_kg"))
        greedy_over = parse_float(greedy.get("total_over_kg"))

        strict_tolerance = 0.5
        material_tolerance = max(
            args.absolute_tolerance_kg,
            target * (args.relative_tolerance_pct / 100.0),
        )

        cp_shortfall_rate = (
            cp_under / target * 100.0 if target > 0 else 0.0
        )
        greedy_shortfall_rate = (
            greedy_under / target * 100.0 if target > 0 else 0.0
        )
        cp_total_deviation = cp_under + cp_over
        greedy_total_deviation = greedy_under + greedy_over

        strict_noninferior = cp_under <= greedy_under + strict_tolerance
        material_noninferior = cp_under <= greedy_under + material_tolerance
        cp_service_safe = (
            cp_shortfall_rate <= args.maximum_shortfall_rate_pct
            and parse_int(cp.get("uncovered_fields")) == 0
            and parse_int(cp.get("duplicate_employee_assignments")) == 0
        )

        if not material_noninferior:
            preferred_method = "GREEDY"
            reason = "MATERIALLY_LOWER_UNCOVERED_CROP"
        elif not cp_service_safe:
            preferred_method = "GREEDY"
            reason = "CP_SAT_SERVICE_SAFETY_GATE_FAILED"
        elif cp_total_deviation < greedy_total_deviation - material_tolerance:
            preferred_method = "CP_SAT"
            reason = "MATERIAL_NONINFERIOR_AND_LOWER_TOTAL_DEVIATION"
        elif (
            parse_int(cp.get("cross_division_assignments"))
            < parse_int(greedy.get("cross_division_assignments"))
        ):
            preferred_method = "CP_SAT"
            reason = "MATERIAL_NONINFERIOR_AND_FEWER_CROSS_DIVISION_MOVES"
        elif (
            parse_int(cp.get("employees_assigned"))
            < parse_int(greedy.get("employees_assigned"))
        ):
            preferred_method = "CP_SAT"
            reason = "MATERIAL_NONINFERIOR_AND_FEWER_EMPLOYEES"
        else:
            preferred_method = "EITHER_BASELINE_ACCEPTABLE"
            reason = "MATERIAL_RESULTS_EQUIVALENT"

        review_rows.append({
            "scenario": scenario,
            "estate": estate,
            "total_target_crop_kg": round(target, 4),
            "cp_sat_under_kg": round(cp_under, 4),
            "greedy_under_kg": round(greedy_under, 4),
            "cp_sat_under_rate_pct": round(cp_shortfall_rate, 6),
            "greedy_under_rate_pct": round(greedy_shortfall_rate, 6),
            "strict_tolerance_kg": strict_tolerance,
            "material_tolerance_kg": round(material_tolerance, 4),
            "strict_noninferior": "YES" if strict_noninferior else "NO",
            "material_noninferior": "YES" if material_noninferior else "NO",
            "cp_sat_service_safe": "YES" if cp_service_safe else "NO",
            "cp_sat_over_kg": round(cp_over, 4),
            "greedy_over_kg": round(greedy_over, 4),
            "cp_sat_total_deviation_kg": round(cp_total_deviation, 4),
            "greedy_total_deviation_kg": round(greedy_total_deviation, 4),
            "cp_sat_employees": parse_int(cp.get("employees_assigned")),
            "greedy_employees": parse_int(greedy.get("employees_assigned")),
            "cp_sat_cross_division": parse_int(
                cp.get("cross_division_assignments")
            ),
            "greedy_cross_division": parse_int(
                greedy.get("cross_division_assignments")
            ),
            "preferred_baseline": preferred_method,
            "decision_reason": reason,
            "operational_status": OPERATIONAL_STATUS,
        })

    strict_count = sum(
        1 for row in review_rows if row["strict_noninferior"] == "YES"
    )
    material_count = sum(
        1 for row in review_rows if row["material_noninferior"] == "YES"
    )
    service_safe_count = sum(
        1 for row in review_rows if row["cp_sat_service_safe"] == "YES"
    )

    strict_rate = strict_count / len(review_rows) * 100.0
    material_rate = material_count / len(review_rows) * 100.0
    service_safe_rate = service_safe_count / len(review_rows) * 100.0

    scenario_gate_rows: list[dict[str, Any]] = []
    capacity_summary_lookup = {
        clean(row.get("scenario")).upper(): row
        for row in capacity_summary_rows
    }

    for scenario in ("EXPECTED", "CONSERVATIVE"):
        subset = [row for row in review_rows if row["scenario"] == scenario]
        cap = capacity_summary_lookup.get(scenario)
        if cap is None:
            raise RuntimeError(f"Missing capacity summary for {scenario}")

        scenario_material_rate = (
            sum(1 for row in subset if row["material_noninferior"] == "YES")
            / len(subset)
            * 100.0
        )
        scenario_service_safe_rate = (
            sum(1 for row in subset if row["cp_sat_service_safe"] == "YES")
            / len(subset)
            * 100.0
        )

        scenario_gate_rows.append({
            "scenario": scenario,
            "estate_scenarios": len(subset),
            "material_noninferiority_rate_pct": round(
                scenario_material_rate, 2
            ),
            "cp_sat_service_safe_rate_pct": round(
                scenario_service_safe_rate, 2
            ),
            "portfolio_effective_coverage_pct": parse_float(
                cap.get("effective_coverage_pct")
            ),
            "uncovered_fields": parse_int(cap.get("uncovered_fields")),
            "fields_coverage_95_plus": parse_int(
                cap.get("fields_coverage_95_plus")
            ),
            "field_rows": parse_int(cap.get("field_rows")),
            "scenario_gate": (
                "PASS"
                if scenario_material_rate >= args.minimum_gate_pct
                and scenario_service_safe_rate == 100.0
                and parse_int(cap.get("uncovered_fields")) == 0
                else "REVIEW_REQUIRED"
            ),
        })

    structural_pass = (
        len(review_rows) == 66
        and all(
            parse_int(row.get("uncovered_fields")) == 0
            for row in capacity_summary_rows
        )
    )

    if (
        structural_pass
        and material_rate >= args.minimum_gate_pct
        and service_safe_rate == 100.0
        and all(row["scenario_gate"] == "PASS" for row in scenario_gate_rows)
    ):
        rl_environment_gate = "READY_FOR_RL_ENVIRONMENT_DESIGN"
    else:
        rl_environment_gate = "NOT_READY_BASELINE_REVIEW_REQUIRED"

    run_folder = output_root / datetime.now().strftime(
        "balanced_baseline_review_%Y%m%d_%H%M%S"
    )
    quality_dir = run_folder / "quality"
    quality_dir.mkdir(parents=True, exist_ok=True)

    write_csv(
        quality_dir / "balanced_cp_sat_vs_greedy_review.csv",
        review_rows,
        [
            "scenario", "estate", "total_target_crop_kg",
            "cp_sat_under_kg", "greedy_under_kg",
            "cp_sat_under_rate_pct", "greedy_under_rate_pct",
            "strict_tolerance_kg", "material_tolerance_kg",
            "strict_noninferior", "material_noninferior",
            "cp_sat_service_safe", "cp_sat_over_kg",
            "greedy_over_kg", "cp_sat_total_deviation_kg",
            "greedy_total_deviation_kg", "cp_sat_employees",
            "greedy_employees", "cp_sat_cross_division",
            "greedy_cross_division", "preferred_baseline",
            "decision_reason", "operational_status",
        ],
    )
    write_csv(
        quality_dir / "scenario_baseline_gate.csv",
        scenario_gate_rows,
        [
            "scenario", "estate_scenarios",
            "material_noninferiority_rate_pct",
            "cp_sat_service_safe_rate_pct",
            "portfolio_effective_coverage_pct",
            "uncovered_fields", "fields_coverage_95_plus",
            "field_rows", "scenario_gate",
        ],
    )

    preference_counts: defaultdict[str, int] = defaultdict(int)
    for row in review_rows:
        preference_counts[row["preferred_baseline"]] += 1

    summary = {
        "status": "PASS_BALANCED_BASELINE_REVIEW_OUTPUTS",
        "package_version": VERSION,
        "run_folder": str(run_folder),
        "comparison_run": str(comparison_run),
        "capacity_run": str(capacity_run),
        "estate_scenario_rows": len(review_rows),
        "legacy_strict_noninferiority_rate_pct": round(strict_rate, 2),
        "material_noninferiority_rate_pct": round(material_rate, 2),
        "cp_sat_service_safe_rate_pct": round(service_safe_rate, 2),
        "minimum_gate_pct": args.minimum_gate_pct,
        "absolute_tolerance_kg": args.absolute_tolerance_kg,
        "relative_tolerance_pct": args.relative_tolerance_pct,
        "maximum_shortfall_rate_pct": args.maximum_shortfall_rate_pct,
        "scenario_gates": scenario_gate_rows,
        "preferred_baseline_counts": dict(preference_counts),
        "rl_environment_gate": rl_environment_gate,
        "operational_status": OPERATIONAL_STATUS,
        "rl_started": False,
        "important_interpretation": [
            "The legacy 0.5 kg rule is retained and reported for transparency.",
            "The material gate uses the larger of 2 kg or 0.05 percent of estate-scenario crop.",
            "CP-SAT must also have no uncovered fields, no duplicate assignments and no more than 0.10 percent estate-scenario shortfall.",
            "A pass permits RL environment design only.",
            "RL training has not started.",
        ],
    }

    (run_folder / "run_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    (run_folder / "README.txt").write_text(
        "\n".join([
            "TTE BALANCED BASELINE REVIEW v8.0.1",
            "",
            f"Legacy strict rate: {strict_rate:.2f}%",
            f"Material noninferiority rate: {material_rate:.2f}%",
            f"CP-SAT service-safe rate: {service_safe_rate:.2f}%",
            f"RL environment gate: {rl_environment_gate}",
            "",
            "This does not start RL training.",
            "This does not approve operational allocation.",
        ]) + "\n",
        encoding="utf-8",
    )

    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "LATEST_BALANCED_BASELINE_REVIEW.txt").write_text(
        str(run_folder), encoding="utf-8"
    )

    print("")
    print("BALANCED BASELINE REVIEW FINISHED")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
