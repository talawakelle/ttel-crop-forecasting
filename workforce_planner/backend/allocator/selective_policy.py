from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import torch

from .selective_actions import ACCEPT_GREEDY, KEEP_CURRENT


DEFAULT_VETO_CONFIDENCE_THRESHOLD = 0.90
VETO_CONFIDENCE_THRESHOLD_GRID = (0.80, 0.85, 0.90, 0.95, 0.98)


@dataclass(frozen=True)
class SelectiveDecision:
    applied_action: int
    raw_action: int
    raw_action_confidence: float
    veto_confidence: float
    low_confidence_veto_overridden: bool


def _masked_action_probabilities(
    model: Any,
    observation: np.ndarray,
    action_masks: np.ndarray,
) -> np.ndarray:
    """Return deterministic masked action probabilities for one observation."""
    observation_tensor, _vectorized = model.policy.obs_to_tensor(observation)
    masks = np.asarray(action_masks, dtype=bool).reshape(1, -1)
    with torch.no_grad():
        distribution = model.policy.get_distribution(
            observation_tensor,
            action_masks=masks,
        )
        probabilities = distribution.distribution.probs
    values = probabilities.detach().cpu().numpy().reshape(-1)
    if values.size != masks.shape[1]:
        raise RuntimeError(
            f"Unexpected selective-policy probability shape: {values.shape}"
        )
    return values.astype(float)


def conservative_selective_action(
    model: Any,
    observation: np.ndarray,
    action_masks: np.ndarray,
    *,
    veto_confidence_threshold: float = DEFAULT_VETO_CONFIDENCE_THRESHOLD,
) -> SelectiveDecision:
    """Apply RL only for a very-high-confidence veto.

    Budgeted dynamic greedy is always the default. A low-confidence RL veto is
    converted back to ACCEPT_GREEDY. An RL accept already agrees with the
    default planner and therefore does not require an override.
    """
    threshold = max(0.50, min(0.999, float(veto_confidence_threshold)))
    probabilities = _masked_action_probabilities(model, observation, action_masks)
    raw_action = int(np.argmax(probabilities))
    raw_confidence = float(probabilities[raw_action])
    veto_confidence = float(probabilities[KEEP_CURRENT])
    override = raw_action == KEEP_CURRENT and veto_confidence < threshold
    applied = ACCEPT_GREEDY if override else raw_action
    return SelectiveDecision(
        applied_action=applied,
        raw_action=raw_action,
        raw_action_confidence=raw_confidence,
        veto_confidence=veto_confidence,
        low_confidence_veto_overridden=override,
    )
