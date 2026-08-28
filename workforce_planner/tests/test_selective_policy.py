from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
import sys

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from allocator.selective_actions import ACCEPT_GREEDY, KEEP_CURRENT
from allocator.selective_policy import conservative_selective_action


class _FakeDistribution:
    def __init__(self, probabilities: list[float]):
        self.distribution = SimpleNamespace(
            probs=torch.tensor([probabilities], dtype=torch.float32)
        )


class _FakePolicy:
    def __init__(self, probabilities: list[float]):
        self.probabilities = probabilities

    def obs_to_tensor(self, observation):
        return torch.tensor(observation, dtype=torch.float32).reshape(1, -1), False

    def get_distribution(self, observation, action_masks=None):
        assert action_masks.shape == (1, 2)
        return _FakeDistribution(self.probabilities)


class _FakeModel:
    def __init__(self, probabilities: list[float]):
        self.policy = _FakePolicy(probabilities)


def test_low_confidence_veto_keeps_greedy_default():
    decision = conservative_selective_action(
        _FakeModel([0.15, 0.85]),
        np.asarray([0.0], dtype=np.float32),
        np.asarray([True, True]),
        veto_confidence_threshold=0.90,
    )
    assert decision.raw_action == KEEP_CURRENT
    assert decision.applied_action == ACCEPT_GREEDY
    assert decision.low_confidence_veto_overridden


def test_high_confidence_veto_is_applied():
    decision = conservative_selective_action(
        _FakeModel([0.03, 0.97]),
        np.asarray([0.0], dtype=np.float32),
        np.asarray([True, True]),
        veto_confidence_threshold=0.90,
    )
    assert decision.applied_action == KEEP_CURRENT
    assert not decision.low_confidence_veto_overridden


def test_rl_accept_preserves_greedy_default():
    decision = conservative_selective_action(
        _FakeModel([0.92, 0.08]),
        np.asarray([0.0], dtype=np.float32),
        np.asarray([True, True]),
        veto_confidence_threshold=0.90,
    )
    assert decision.applied_action == ACCEPT_GREEDY
