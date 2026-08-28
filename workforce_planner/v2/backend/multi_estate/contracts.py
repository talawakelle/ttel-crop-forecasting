from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class OperationalCategory(StrEnum):
    TEA_ESTATE_LABOUR = "tea_estate_labour"
    BLACK_LEAF_FACTORY = "black_leaf_factory"
    COMBINED_UNIT = "combined_unit"
    REPROCESSING = "reprocessing"
    RUBBER = "rubber"
    CINNAMON = "cinnamon"


class EstatePlannerStatus(StrEnum):
    DATA_AUDIT = "DATA_AUDIT"
    DETERMINISTIC_SIMULATION = "DETERMINISTIC_SIMULATION"
    RL_EVALUATION = "RL_EVALUATION"
    SHADOW_MODE = "SHADOW_MODE"
    CONTROLLED_LIVE = "CONTROLLED_LIVE"
    REJECTED = "REJECTED"


@dataclass(frozen=True, order=True)
class EstateKey:
    plantation_id: int
    estate_id: int

    def __post_init__(self) -> None:
        if self.plantation_id <= 0 or self.estate_id <= 0:
            raise ValueError("plantation_id and estate_id must be positive")

    @property
    def value(self) -> str:
        return f"{self.plantation_id}:{self.estate_id}"


@dataclass(frozen=True)
class PlannerSafetyPolicy:
    maximum_move_rate: float = 0.15
    maximum_total_moves: int = 15
    maximum_moves_per_round: int = 10
    maximum_voluntary_moves_per_employee: int = 1
    deterministic_default: str = "budgeted_dynamic_greedy"
    rl_role: str = "high_confidence_accept_veto_gate"
    fallback: str = "budgeted_dynamic_greedy"

    def __post_init__(self) -> None:
        if not 0 < self.maximum_move_rate <= 0.15:
            raise ValueError("maximum_move_rate cannot exceed 15%")
        if self.maximum_total_moves > 15 or self.maximum_moves_per_round > 10:
            raise ValueError("movement limits exceed the approved v1.5 safety ceiling")
        if self.maximum_voluntary_moves_per_employee != 1:
            raise ValueError("only one voluntary move per employee is allowed")


@dataclass
class EstateProfileContract:
    key: EstateKey
    estate: str
    category: OperationalCategory
    employees: int
    divisions: int
    fields: int
    date_min: str | None
    date_max: str | None
    workforce_readiness: str
    crop_forecast_origin: str | None = None
    crop_forecast_status: str | None = None
    planner_status: EstatePlannerStatus = EstatePlannerStatus.DATA_AUDIT
    safety: PlannerSafetyPolicy = field(default_factory=PlannerSafetyPolicy)

    def can_run_deterministic_simulation(self) -> bool:
        return (
            self.category is OperationalCategory.TEA_ESTATE_LABOUR
            and self.workforce_readiness == "READY_FOR_MODEL_COMPARISON"
            and bool(self.crop_forecast_origin)
        )

    def can_enable_rl(self) -> bool:
        return self.planner_status in {
            EstatePlannerStatus.RL_EVALUATION,
            EstatePlannerStatus.SHADOW_MODE,
            EstatePlannerStatus.CONTROLLED_LIVE,
        }
