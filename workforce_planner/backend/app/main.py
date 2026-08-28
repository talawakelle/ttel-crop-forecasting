from __future__ import annotations

from typing import Literal
import hashlib
import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from allocator.data import WorkforceData
from allocator.goal import analyze_coverage_goal
from allocator.frontier import build_coverage_frontier
from allocator.hybrid import build_candidate_plans
from allocator.optimizer import optimizer_runtime
from allocator.practical import build_practical_plan
from allocator.version import (
    ALLOCATION_STRATEGY,
    APPLICATION_VERSION,
    MODEL_SCHEMA_VERSION,
)
from .config import settings


data = WorkforceData.load(settings.profile_path)
data.configure_forecaster(
    model_path=settings.forecast_model_path,
    weather_model_path=settings.weather_forecast_model_path,
    metadata_path=settings.forecast_metrics_path,
    state_path=settings.forecast_state_path,
    weather_daily_path=settings.weather_daily_path,
    weather_metadata_path=settings.weather_metadata_path,
)
data.configure_crop_forecaster(settings.crop_forecast_path)


def model_metadata() -> dict | None:
    metrics_path = settings.model_path.with_name("training_metrics.json")
    if not metrics_path.exists():
        return None
    try:
        return json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def dynamic_model_metadata() -> dict | None:
    metrics_path = settings.dynamic_model_path.with_name("dynamic_training_metrics.json")
    if not metrics_path.exists():
        return None
    try:
        return json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def selective_hybrid_model_metadata() -> dict | None:
    metrics_path = settings.selective_hybrid_model_path.with_name(
        "selective_hybrid_training_metrics.json"
    )
    if not metrics_path.exists():
        return None
    try:
        return json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _sha256_file(path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return None


def dynamic_model_is_compatible() -> bool:
    from allocator.version import DYNAMIC_MODEL_SCHEMA_VERSION

    metrics = dynamic_model_metadata()
    forecast_metadata = getattr(data.forecaster, "metadata", None) or {}
    active_forecast_hash = (
        forecast_metadata.get("base_model_sha256")
        or forecast_metadata.get("model_sha256")
    )
    crop_hash = data.crop_forecast_status().get("source_sha256")
    return bool(
        settings.dynamic_model_path.exists()
        and metrics
        and metrics.get("approved") is True
        and metrics.get("dynamic_model_schema_version") == DYNAMIC_MODEL_SCHEMA_VERSION
        and metrics.get("profile_source_sha256") == data.metadata.get("source_sha256")
        and metrics.get("forecast_base_model_sha256") == active_forecast_hash
        and metrics.get("crop_forecast_source_sha256") == crop_hash
        and metrics.get("dynamic_environment_sha256") == _sha256_file(
            settings.project_root / "backend" / "allocator" / "dynamic_environment.py"
        )
        and metrics.get("dynamic_training_sha256") == _sha256_file(
            settings.project_root / "backend" / "allocator" / "dynamic_training.py"
        )
        and metrics.get("constraint_violations") == 0
        and metrics.get("untouched_test_evaluation") is True
        and all((metrics.get("approval_gate") or {}).values())
    )


def selective_hybrid_model_is_compatible() -> bool:
    from allocator.version import SELECTIVE_HYBRID_MODEL_SCHEMA_VERSION

    metrics = selective_hybrid_model_metadata()
    forecast_metadata = getattr(data.forecaster, "metadata", None) or {}
    active_forecast_hash = (
        forecast_metadata.get("base_model_sha256")
        or forecast_metadata.get("model_sha256")
    )
    crop_hash = data.crop_forecast_status().get("source_sha256")
    return bool(
        settings.selective_hybrid_model_path.exists()
        and metrics
        and metrics.get("approved") is True
        and metrics.get("selective_hybrid_model_schema_version")
        == SELECTIVE_HYBRID_MODEL_SCHEMA_VERSION
        and metrics.get("profile_source_sha256") == data.metadata.get("source_sha256")
        and metrics.get("forecast_base_model_sha256") == active_forecast_hash
        and metrics.get("crop_forecast_source_sha256") == crop_hash
        and metrics.get("dynamic_environment_sha256")
        == _sha256_file(settings.project_root / "backend" / "allocator" / "dynamic_environment.py")
        and metrics.get("selective_environment_sha256")
        == _sha256_file(settings.project_root / "backend" / "allocator" / "selective_environment.py")
        and metrics.get("selective_policy_sha256")
        == _sha256_file(settings.project_root / "backend" / "allocator" / "selective_policy.py")
        and metrics.get("selective_training_sha256")
        == _sha256_file(settings.project_root / "backend" / "allocator" / "selective_training.py")
        and metrics.get("constraint_violations") == 0
        and metrics.get("untouched_test_evaluation") is True
        and all((metrics.get("approval_gate") or {}).values())
    )


def model_is_compatible() -> bool:
    metrics = model_metadata()
    expected = data.metadata.get("source_sha256")
    forecast_metadata = getattr(data.forecaster, "metadata", None) or {}
    active_forecast_hash = (
        forecast_metadata.get("base_model_sha256")
        or forecast_metadata.get("model_sha256")
    )
    return bool(
        settings.model_path.exists()
        and metrics
        and metrics.get("approved") is True
        and expected
        and metrics.get("profile_source_sha256") == expected
        and metrics.get("model_schema_version") == MODEL_SCHEMA_VERSION
        and metrics.get("rl_constraint_violations") == 0
        and metrics.get("forecast_ready_during_training") is True
        and active_forecast_hash
        and metrics.get("forecast_base_model_sha256") == active_forecast_hash
    )


class AllocationRequest(BaseModel):
    template_date: str | None = None
    planning_date: str | None = None
    attendance_rate: float = Field(default=0.9, ge=0.25, le=1.0)
    demand_multiplier: float = Field(default=1.0, ge=0.5, le=1.75)
    same_division_only: bool = True
    division: str | None = None
    seed: int = Field(default=42, ge=0, le=10_000_000)
    policy: Literal["hybrid", "optimizer", "rl", "greedy"] = "hybrid"
    demand_source: Literal["historical_template", "crop_forecast"] = "historical_template"
    forecast_risk: Literal["lower", "central", "upper"] = "central"
    coverage_goal_pct: float = Field(default=85.0, ge=50.0, le=100.0)


class PracticalAllocationRequest(AllocationRequest):
    additional_workers_available: int = Field(default=0, ge=0, le=650)
    max_cross_division_transfers: int = Field(default=0, ge=0, le=650)


app = FastAPI(
    title="TTE Daily Employee Planner",
    version=APPLICATION_VERSION,
    docs_url="/api/docs",
    redoc_url=None,
)

app.mount("/assets", StaticFiles(directory=settings.web_dir / "assets"), name="assets")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(settings.web_dir / "index.html")


@app.get("/api/health")
def health():
    runtime = optimizer_runtime()
    forecast = data.forecast_status()
    return {
        "status": "ok",
        "mode": "local-prototype",
        "authentication": "disabled",
        "profile_loaded": settings.profile_path.exists(),
        "optimizer_available": runtime["available"],
        "rl_model_present": settings.model_path.exists(),
        "rl_model_compatible": model_is_compatible(),
        "rl_training_required": not model_is_compatible(),
        "productivity_forecast_ready": forecast["ready"],
        "productivity_forecast_test_mae_kg": forecast.get("test_mae_kg"),
        "weather_forecast_ready": forecast.get("weather_ready", False),
        "weather_history_as_of": forecast.get("weather_as_of"),
        "productivity_forecast_error": forecast["error"],
        "crop_forecast": data.crop_forecast_status(),
        "dynamic_rl_model_present": settings.dynamic_model_path.exists(),
        "dynamic_rl_model_compatible": dynamic_model_is_compatible(),
        "dynamic_rl_simulation_approved": dynamic_model_is_compatible(),
        "dynamic_rl_operational_shadow_approved": bool(
            (dynamic_model_metadata() or {}).get("shadow_mode_approved")
        ),
        "dynamic_rl_training_required": not dynamic_model_is_compatible(),
        "selective_hybrid_rl_model_present": settings.selective_hybrid_model_path.exists(),
        "selective_hybrid_rl_model_compatible": selective_hybrid_model_is_compatible(),
        "selective_hybrid_rl_simulation_approved": selective_hybrid_model_is_compatible(),
        "selective_hybrid_rl_operational_shadow_approved": bool(
            (selective_hybrid_model_metadata() or {}).get("shadow_mode_approved")
        ),
        "selective_hybrid_rl_training_required": not selective_hybrid_model_is_compatible(),
        "coverage_goal_planner": runtime["available"],
        "coverage_frontier": runtime["available"],
        "practical_operations_planner": runtime["available"],
    }


@app.get("/api/profile")
def profile():
    return data.public_summary()


@app.get("/api/model")
def model_status():
    metrics = model_metadata()
    runtime = optimizer_runtime()
    return {
        "application_version": APPLICATION_VERSION,
        "algorithm": ALLOCATION_STRATEGY,
        "hybrid_ready": runtime["available"],
        "optimizer": runtime,
        "optimizer_time_limit_seconds": settings.optimizer_time_limit_seconds,
        "goal_time_limit_seconds": settings.goal_time_limit_seconds,
        "frontier_time_limit_seconds": settings.frontier_time_limit_seconds,
        "practical_time_limit_seconds": settings.practical_time_limit_seconds,
        "default_coverage_goal_pct": 85.0,
        "required_model_schema_version": MODEL_SCHEMA_VERSION,
        "trained": model_is_compatible(),
        "rl_training_required": not model_is_compatible(),
        "model_present": settings.model_path.exists(),
        "profile_compatible": model_is_compatible(),
        "model_file": settings.model_path.name,
        "metrics": metrics,
        "productivity_forecast": data.forecast_status(),
        "crop_forecast": data.crop_forecast_status(),
        "dynamic_rl": {
            "model_present": settings.dynamic_model_path.exists(),
            "compatible": dynamic_model_is_compatible(),
            "simulation_approved": dynamic_model_is_compatible(),
            "operational_shadow_approved": bool(
                (dynamic_model_metadata() or {}).get("shadow_mode_approved")
            ),
            "training_required": not dynamic_model_is_compatible(),
            "model_file": settings.dynamic_model_path.name,
            "metrics_file": "dynamic_training_metrics.json",
            "metrics": dynamic_model_metadata(),
            "role": "two-round event-driven intraday reallocation only; not the morning static optimizer",
            "required_design": "morning work + midday replan + afternoon replan; no future-reference leakage",
        },
        "selective_hybrid_rl": {
            "model_present": settings.selective_hybrid_model_path.exists(),
            "compatible": selective_hybrid_model_is_compatible(),
            "simulation_approved": selective_hybrid_model_is_compatible(),
            "operational_shadow_approved": bool(
                (selective_hybrid_model_metadata() or {}).get("shadow_mode_approved")
            ),
            "training_required": not selective_hybrid_model_is_compatible(),
            "model_file": settings.selective_hybrid_model_path.name,
            "metrics_file": "selective_hybrid_training_metrics.json",
            "metrics": selective_hybrid_model_metadata(),
            "role": (
                "budgeted dynamic greedy remains primary; RL may veto only with calibrated high confidence; "
                "midday and afternoon moves"
            ),
            "movement_limits": {
                "maximum_rate": 0.15,
                "maximum_total_moves": 15,
                "maximum_moves_per_round": 10,
            },
            "fallback": "conservative automatic fallback to budgeted dynamic greedy",
        },
        "hard_constraints": [
            "At most one assignment per employee per plan",
            "Only active fields can receive workers",
            "Field worker capacities cannot be exceeded",
            "Division transfers are blocked when same-division mode is enabled",
            "Practical plans cannot exceed the supervisor-entered call-up limit",
            "Practical plans cannot exceed the supervisor-entered transfer limit",
        ],
        "limitation": (
            "Coverage is optimized against forecast productivity, not observed counterfactual outcomes. "
            "The selective hybrid model remains disabled until it passes untouched testing, and live use "
            "still requires supervisor-approved shadow-mode evidence."
        ),
    }


@app.get("/api/crop-forecast")
def crop_forecast(planning_date: str | None = None):
    return data.crop_forecast_status(planning_date)


@app.post("/api/allocate")
def allocate(request: AllocationRequest):
    try:
        scenario = data.create_scenario(
            template_date=request.template_date,
            planning_date=request.planning_date,
            attendance_rate=request.attendance_rate,
            demand_multiplier=request.demand_multiplier,
            same_division_only=request.same_division_only,
            division=request.division,
            seed=request.seed,
            demand_source=request.demand_source,
            forecast_risk=request.forecast_risk,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not scenario.demand_kg:
        raise HTTPException(status_code=400, detail="The selected scenario has no active fields")
    compatible_model = settings.model_path if model_is_compatible() else None
    candidates = build_candidate_plans(
        data,
        scenario,
        model_path=compatible_model,
        include_rl=request.policy in {"hybrid", "rl"},
        include_optimizer=request.policy in {"hybrid", "optimizer"},
        optimizer_time_limit_seconds=settings.optimizer_time_limit_seconds,
    )
    plans = candidates["plans"]
    summaries = candidates["summaries"]
    standard = summaries["standard"]
    rl_summary = summaries["rl"]
    optimizer_summary = summaries["optimizer"]
    comparison = {
        "selected_method": candidates["selected_name"],
        "methods": summaries,
        "errors": candidates["errors"],
        # Retain the v0.4 fields for simple clients already using them.
        "rl_coverage_pct": rl_summary["coverage_pct"] if rl_summary else None,
        "greedy_coverage_pct": standard["coverage_pct"],
        "optimizer_coverage_pct": optimizer_summary["coverage_pct"] if optimizer_summary else None,
        "difference_pct_points": (
            round(rl_summary["coverage_pct"] - standard["coverage_pct"], 1)
            if rl_summary else None
        ),
        "optimizer_minus_greedy_pct_points": (
            round(optimizer_summary["coverage_pct"] - standard["coverage_pct"], 1)
            if optimizer_summary else None
        ),
        "rl_constraint_violations": rl_summary["constraint_violations"] if rl_summary else None,
        "greedy_constraint_violations": standard["constraint_violations"],
        "optimizer_constraint_violations": (
            optimizer_summary["constraint_violations"] if optimizer_summary else None
        ),
    }
    try:
        coverage_goal = analyze_coverage_goal(
            data,
            scenario,
            candidates["selected"],
            goal_coverage_pct=request.coverage_goal_pct,
            time_limit_seconds=settings.goal_time_limit_seconds,
        )
    except Exception as exc:
        coverage_goal = {
            "status": "analysis_unavailable",
            "goal_coverage_pct": request.coverage_goal_pct,
            "current_coverage_pct": candidates["selected"]["metrics"]["coverage_pct"],
            "headline": "The allocation is ready, but the coverage-goal check could not finish.",
            "next_actions": ["Use the valid allocation and retry the goal check."],
            "error": f"{type(exc).__name__}: {exc}",
            "goal_plan": None,
        }
    return {
        "selected": candidates["selected"],
        "optimizer": plans["optimizer"],
        "rl": plans["rl"],
        "greedy": plans["standard"],
        "comparison": comparison,
        "errors": candidates["errors"],
        "rl_error": candidates["errors"]["rl"],
        "forecast": data.forecast_status(scenario.planning_date),
        "crop_forecast": data.crop_forecast_status(scenario.planning_date),
        "coverage_goal": coverage_goal,
    }


@app.post("/api/frontier")
def coverage_frontier(request: AllocationRequest):
    try:
        scenario = data.create_scenario(
            template_date=request.template_date,
            planning_date=request.planning_date,
            attendance_rate=request.attendance_rate,
            demand_multiplier=request.demand_multiplier,
            same_division_only=request.same_division_only,
            division=request.division,
            seed=request.seed,
            demand_source=request.demand_source,
            forecast_risk=request.forecast_risk,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not scenario.demand_kg:
        raise HTTPException(status_code=400, detail="The selected scenario has no active fields")
    compatible_model = settings.model_path if model_is_compatible() else None
    candidates = build_candidate_plans(
        data,
        scenario,
        model_path=compatible_model,
        include_rl=request.policy in {"hybrid", "rl"},
        include_optimizer=True,
        optimizer_time_limit_seconds=settings.optimizer_time_limit_seconds,
    )
    frontier = build_coverage_frontier(
        data,
        scenario,
        candidates["selected"],
        time_limit_seconds=settings.frontier_time_limit_seconds,
    )
    return {
        "frontier": frontier,
        "forecast": data.forecast_status(scenario.planning_date),
        "crop_forecast": data.crop_forecast_status(scenario.planning_date),
    }


@app.post("/api/practical")
def practical_plan(request: PracticalAllocationRequest):
    try:
        scenario = data.create_scenario(
            template_date=request.template_date,
            planning_date=request.planning_date,
            attendance_rate=request.attendance_rate,
            demand_multiplier=request.demand_multiplier,
            same_division_only=request.same_division_only,
            division=request.division,
            seed=request.seed,
            demand_source=request.demand_source,
            forecast_risk=request.forecast_risk,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not scenario.demand_kg:
        raise HTTPException(status_code=400, detail="The selected scenario has no active fields")

    compatible_model = settings.model_path if model_is_compatible() else None
    candidates = build_candidate_plans(
        data,
        scenario,
        model_path=compatible_model,
        include_rl=request.policy in {"hybrid", "rl"},
        include_optimizer=True,
        optimizer_time_limit_seconds=settings.optimizer_time_limit_seconds,
    )
    try:
        practical = build_practical_plan(
            data,
            scenario,
            candidates["selected"],
            max_additional_workers=request.additional_workers_available,
            max_cross_division_assignments=request.max_cross_division_transfers,
            goal_coverage_pct=request.coverage_goal_pct,
            time_limit_seconds=settings.practical_time_limit_seconds,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Practical planning could not finish: {type(exc).__name__}: {exc}",
        )
    return {
        "practical": practical,
        "current": candidates["selected"],
        "forecast": data.forecast_status(scenario.planning_date),
        "crop_forecast": data.crop_forecast_status(scenario.planning_date),
    }
