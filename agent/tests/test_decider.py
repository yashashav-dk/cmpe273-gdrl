"""
Tests for Decider hysteresis and no-flapping behaviour.

The key property: once a policy decision is made, neither the same decision
nor its reversal can fire again until HYSTERESIS_SECONDS have elapsed.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from decider import (
    DEFAULT_LIMITS,
    HYSTERESIS_SECONDS,
    NOISY_NEIGHBOR_SHARE,
    SPIKE_THRESHOLD,
    TIER_CAPACITY_RPS,
    Decider,
    _TierState,
)
from predictor import Prediction


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_decider() -> tuple[Decider, MagicMock]:
    writer = MagicMock()
    return Decider(writer=writer), writer


def _predictions(free_rps: float = 0.0) -> dict:
    from metrics_client import REGIONS, TIERS
    return {
        r: {
            t: Prediction(rps=free_rps if t == "free" else 5.0, is_spike=False)
            for t in TIERS
        }
        for r in REGIONS
    }


def _past_hysteresis() -> float:
    return time.time() - HYSTERESIS_SECONDS - 1


def _within_hysteresis() -> float:
    return time.time() - (HYSTERESIS_SECONDS // 2)


# ── spike throttle ────────────────────────────────────────────────────────────

def test_throttle_fires_above_threshold():
    decider, writer = _make_decider()
    # Age the initial state past the hysteresis window so the rule can fire
    for region in decider._state:
        decider._state[region]["free"].written_at = _past_hysteresis()

    spike_rps = TIER_CAPACITY_RPS["free"] * (SPIKE_THRESHOLD + 0.05)
    decider.decide({}, _predictions(spike_rps), {})

    assert writer.write_policy.called
    call = writer.write_policy.call_args.kwargs
    assert call["tier"] == "free"
    assert call["limit_per_minute"] < DEFAULT_LIMITS["free"]
    assert "spike" in call["reason"]


def test_throttle_does_not_fire_below_threshold():
    decider, writer = _make_decider()
    for region in decider._state:
        decider._state[region]["free"].written_at = _past_hysteresis()

    safe_rps = TIER_CAPACITY_RPS["free"] * (SPIKE_THRESHOLD - 0.10)
    decider.decide({}, _predictions(safe_rps), {})

    writer.write_policy.assert_not_called()


# ── hysteresis: no double-throttle, no premature recovery ────────────────────

def test_hysteresis_blocks_second_throttle():
    """After throttling, another spike within HYSTERESIS_SECONDS must not re-fire."""
    decider, writer = _make_decider()
    decider._state["us"]["free"] = _TierState(
        limit_per_minute=70, written_at=_within_hysteresis(), throttled=True
    )

    spike_rps = TIER_CAPACITY_RPS["free"] * 0.95
    decider.decide({}, _predictions(spike_rps), {})

    writer.write_policy.assert_not_called()


def test_hysteresis_blocks_premature_recovery():
    """A throttled tier must not recover while still inside HYSTERESIS_SECONDS."""
    decider, writer = _make_decider()
    decider._state["us"]["free"] = _TierState(
        limit_per_minute=70, written_at=_within_hysteresis(), throttled=True
    )

    low_rps = TIER_CAPACITY_RPS["free"] * 0.10  # well below recovery threshold
    decider.decide({}, _predictions(low_rps), {})

    writer.write_policy.assert_not_called()


def test_recovery_fires_after_hysteresis_window():
    """Recovery must fire once HYSTERESIS_SECONDS have elapsed and traffic is low."""
    decider, writer = _make_decider()
    decider._state["us"]["free"] = _TierState(
        limit_per_minute=70, written_at=_past_hysteresis(), throttled=True
    )

    low_rps = TIER_CAPACITY_RPS["free"] * 0.10
    decider.decide({}, _predictions(low_rps), {})

    assert writer.write_policy.called
    call = writer.write_policy.call_args.kwargs
    assert call["limit_per_minute"] == DEFAULT_LIMITS["free"]
    assert "recovery" in call["reason"]


# ── noisy neighbor ────────────────────────────────────────────────────────────

def test_noisy_neighbor_override_fires():
    decider, writer = _make_decider()
    top_users = {"us": {"free": ("u_spammer", NOISY_NEIGHBOR_SHARE + 0.10)}}

    decider.decide({}, _predictions(0.0), top_users)

    assert writer.write_override.called
    call = writer.write_override.call_args.kwargs
    assert call["user_id"] == "u_spammer"
    assert call["limit_per_minute"] == 5
    assert "noisy_neighbor" in call["reason"]


def test_noisy_neighbor_below_threshold_ignored():
    decider, writer = _make_decider()
    top_users = {"us": {"free": ("u_normal", NOISY_NEIGHBOR_SHARE - 0.05)}}

    decider.decide({}, _predictions(0.0), top_users)

    writer.write_override.assert_not_called()


def test_noisy_neighbor_hysteresis_blocks_repeat_override():
    """Same user must not be overridden again within HYSTERESIS_SECONDS."""
    decider, writer = _make_decider()
    decider._overrides["u_spammer"] = _within_hysteresis()

    top_users = {"us": {"free": ("u_spammer", NOISY_NEIGHBOR_SHARE + 0.10)}}
    decider.decide({}, _predictions(0.0), top_users)

    writer.write_override.assert_not_called()


def test_noisy_neighbor_fires_after_hysteresis_expires():
    decider, writer = _make_decider()
    decider._overrides["u_spammer"] = _past_hysteresis()

    top_users = {"us": {"free": ("u_spammer", NOISY_NEIGHBOR_SHARE + 0.10)}}
    decider.decide({}, _predictions(0.0), top_users)

    assert writer.write_override.called
