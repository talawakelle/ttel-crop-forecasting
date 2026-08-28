from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    project_root: Path
    profile_path: Path
    model_path: Path
    forecast_model_path: Path
    weather_forecast_model_path: Path
    forecast_metrics_path: Path
    forecast_state_path: Path
    weather_daily_path: Path
    weather_metadata_path: Path
    crop_forecast_path: Path
    dynamic_model_path: Path
    selective_hybrid_model_path: Path
    web_dir: Path
    optimizer_time_limit_seconds: float
    goal_time_limit_seconds: float
    frontier_time_limit_seconds: float
    practical_time_limit_seconds: float


def load_settings() -> Settings:
    root = Path(__file__).resolve().parents[2]
    return Settings(
        project_root=root,
        profile_path=Path(os.getenv("TTE_RL_PROFILE", root / "data" / "workforce_profile.json")).resolve(),
        model_path=Path(os.getenv("TTE_RL_MODEL", root / "models" / "maskable_ppo_allocator.zip")).resolve(),
        forecast_model_path=Path(
            os.getenv("TTE_FORECAST_MODEL", root / "models" / "productivity_catboost.cbm")
        ).resolve(),
        weather_forecast_model_path=Path(
            os.getenv("TTE_WEATHER_FORECAST_MODEL", root / "models" / "productivity_weather_catboost.cbm")
        ).resolve(),
        forecast_metrics_path=Path(
            os.getenv("TTE_FORECAST_METRICS", root / "models" / "productivity_metrics.json")
        ).resolve(),
        forecast_state_path=Path(
            os.getenv("TTE_FORECAST_STATE", root / "data" / "productivity_state.json.gz")
        ).resolve(),
        weather_daily_path=Path(
            os.getenv("TTE_WEATHER_DAILY", root / "data" / "weather_daily.csv.gz")
        ).resolve(),
        weather_metadata_path=Path(
            os.getenv("TTE_WEATHER_METADATA", root / "data" / "weather_metadata.json")
        ).resolve(),
        crop_forecast_path=Path(
            os.getenv("TTE_CROP_FORECAST", root / "data" / "crop_forecast_clarendon.json")
        ).resolve(),
        dynamic_model_path=Path(
            os.getenv("TTE_DYNAMIC_RL_MODEL", root / "models" / "dynamic_maskable_ppo_reallocator.zip")
        ).resolve(),
        selective_hybrid_model_path=Path(
            os.getenv(
                "TTE_SELECTIVE_HYBRID_RL_MODEL",
                root / "models" / "selective_hybrid_maskable_ppo.zip",
            )
        ).resolve(),
        web_dir=root / "web",
        optimizer_time_limit_seconds=max(
            0.25,
            min(30.0, float(os.getenv("TTE_OPTIMIZER_SECONDS", "5"))),
        ),
        goal_time_limit_seconds=max(
            0.25,
            min(15.0, float(os.getenv("TTE_GOAL_SECONDS", "3"))),
        ),
        frontier_time_limit_seconds=max(
            0.25,
            min(15.0, float(os.getenv("TTE_FRONTIER_SECONDS", "3"))),
        ),
        practical_time_limit_seconds=max(
            0.25,
            min(30.0, float(os.getenv("TTE_PRACTICAL_SECONDS", "10"))),
        ),
    )


settings = load_settings()
