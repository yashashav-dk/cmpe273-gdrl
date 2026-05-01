"""
Tests for EWMAPredictor and HoltWintersPredictor.

Key properties checked:
  - EWMA: cold-start bootstrap, spike detection, warm_up seeding
  - HoltWinters: EWMA fallback when history < min_fit, HW forecast when history >= min_fit,
    IsolationForest anomaly flag fires on a clear outlier, anomaly suppressed below min_fit
"""
from __future__ import annotations

import math

import pytest

from predictor import EWMAPredictor, HoltWintersPredictor


# ── helpers ───────────────────────────────────────────────────────────────────

def _sine_series(n: int, base: float = 50.0, amp: float = 10.0) -> list[float]:
    """Sinusoidal RPS series to give HW something seasonal to fit."""
    return [base + amp * math.sin(2 * math.pi * i / 30) for i in range(n)]


def _features(us_free_rps: float = 10.0) -> dict:
    """Build a feature dict for all regions/tiers; only us/free gets the custom value."""
    from metrics_client import REGIONS, TIERS
    return {
        r: {f"{t}_rps": (us_free_rps if r == "us" and t == "free" else 5.0)
            for t in TIERS} | {"rejection_rate": 0.0}
        for r in REGIONS
    }


def _all_rps(rps: float = 50.0, us_free_override: float | None = None) -> dict:
    """Build a feature dict where every region+tier gets the same RPS, with optional override."""
    tiers = ["free", "premium", "internal"]
    regions = ["us", "eu", "asia"]
    return {
        r: {f"{t}_rps": (us_free_override if us_free_override is not None and r == "us" and t == "free" else rps)
            for t in tiers} | {"rejection_rate": 0.0}
        for r in regions
    }


# ── EWMAPredictor ─────────────────────────────────────────────────────────────

def test_ewma_cold_start_bootstraps_from_first_observation():
    p = EWMAPredictor(alpha=0.3)
    result = p.update(_features(us_free_rps=40.0))
    pred = result["us"]["free"]
    # Cold start: EWMA is seeded directly from the first observation
    assert pred.rps == pytest.approx(40.0, abs=1.0)
    assert not pred.is_spike


def test_ewma_spike_detected_when_current_exceeds_2x_baseline():
    p = EWMAPredictor(alpha=0.3)
    # Warm up to a stable baseline of ~10 rps
    for _ in range(20):
        p.update(_features(us_free_rps=10.0))
    # Feed a value well above 2× the EWMA
    result = p.update(_features(us_free_rps=100.0))
    assert result["us"]["free"].is_spike


def test_ewma_warm_up_seeds_state():
    p = EWMAPredictor(alpha=0.3)
    history = {"us/free": [20.0] * 30}
    p.warm_up(history)
    # EWMA should be near 20 after warm-up; first live update with 20 stays near 20
    result = p.update(_features(us_free_rps=20.0))
    assert result["us"]["free"].rps == pytest.approx(20.0, abs=1.0)


def test_ewma_unknown_key_in_warm_up_ignored():
    p = EWMAPredictor()
    p.warm_up({"bad_key": [1.0, 2.0], "us/unknown_tier": [5.0]})
    # No crash; state for us/free starts at 0 (cold start)
    result = p.update(_features(us_free_rps=0.0))
    assert result["us"]["free"].rps == pytest.approx(0.0, abs=0.1)


# ── HoltWintersPredictor: fallback region ────────────────────────────────────

def test_hw_falls_back_to_ewma_with_short_history():
    """With < min_fit observations the predictor must use EWMA, not HW."""
    p = HoltWintersPredictor(seasonal_periods=30)
    # Feed 10 ticks — well below min_fit=60
    result = None
    for _ in range(10):
        result = p.update(_features(us_free_rps=25.0))
    pred = result["us"]["free"]
    # EWMA of 25.0 repeated converges toward 25; anomaly must stay False (below min_fit)
    assert pred.rps == pytest.approx(25.0, abs=5.0)
    assert not pred.anomaly


def test_hw_warm_up_seeds_history_buffer():
    p = HoltWintersPredictor(seasonal_periods=30, max_history=120)
    series = _sine_series(90)
    p.warm_up({"us/free": series})
    buf = p._history["us"]["free"]
    assert len(buf) == 90


# ── HoltWintersPredictor: HW region (enough history) ─────────────────────────

def test_hw_produces_finite_forecast_with_full_history():
    """After 2 full seasonal cycles the predictor should return a real HW forecast."""
    p = HoltWintersPredictor(seasonal_periods=10, max_history=60, retrain_every=5)
    series = _sine_series(n=60, base=50.0, amp=8.0)
    p.warm_up({"us/free": series})
    # One tick to trigger HW fit (tick=0 % retrain_every=5 == 0)
    result = p.update(_all_rps(rps=50.0))
    pred = result["us"]["free"]
    assert math.isfinite(pred.rps)
    assert pred.rps >= 0.0


# ── HoltWintersPredictor: IsolationForest anomaly ────────────────────────────

def test_anomaly_suppressed_below_min_fit():
    p = HoltWintersPredictor(seasonal_periods=30)
    # Only 1 observation — well below min_fit=60
    result = p.update(_features(us_free_rps=9999.0))
    assert not result["us"]["free"].anomaly


def test_anomaly_fires_on_outlier_after_stable_history():
    """IsolationForest flags a value in the known-outlier range after training on mixed data.

    IsolationForest works by isolating points using random splits bounded by the
    training data range — it doesn't extrapolate well beyond that range. The training
    set therefore includes representative spike samples (~200) alongside the normal
    baseline (~50), so the model learns the boundary between normal and outlier-range
    traffic. A test point of 200 should then be correctly flagged as anomalous.
    """
    sp = 10
    p = HoltWintersPredictor(
        seasonal_periods=sp,
        max_history=200,
        retrain_every=5,
        iso_contamination=0.1,  # 10% → flags ~7 of 70 training points
    )
    # 65 stable baseline + 5 spike-range values in training data (7.7% → above contamination)
    stable = _sine_series(n=65, base=50.0, amp=5.0)
    spikes = [200.0, 210.0, 195.0, 205.0, 198.0]
    p.warm_up({"us/free": stable + spikes})  # 70 points, ~7% spikes

    # Trigger ISO retrain at tick=0 (0 % retrain_every == 0)
    p.update(_all_rps(rps=50.0))  # tick=0 — ISO trains on all 71 points

    # tick=1: inject a value in the spike range — ISO model trained at tick=0 flags it
    result = p.update(_all_rps(rps=50.0, us_free_override=202.0))
    assert result["us"]["free"].anomaly, (
        "IsolationForest should flag a spike-range value (202) after training on data "
        "that includes representative spike samples (~200)"
    )
