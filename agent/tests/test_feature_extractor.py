"""
Tests for FeatureExtractor staleness logic.

Key properties:
  - live tick: returns fresh features and updates the cache
  - Prometheus down, cache < 120 s old: returns cached features unchanged
  - Prometheus down, cache > 120 s old: returns zero-RPS static defaults
  - Prometheus never connected (first tick): returns zero-RPS static defaults
"""
from __future__ import annotations

import math
import time
from unittest.mock import MagicMock

from feature_extractor import FeatureExtractor, STALE_WINDOW_SECONDS
from metrics_client import REGIONS, TIERS


# ── helpers ───────────────────────────────────────────────────────────────────

def _mock_client(seconds_since: float) -> MagicMock:
    client = MagicMock()
    client.seconds_since_live.return_value = seconds_since
    client.request_rate.return_value = []
    client.rejection_rate.return_value = []
    return client


def _live_client() -> MagicMock:
    return _mock_client(seconds_since=0.5)


def _dead_client() -> MagicMock:
    return _mock_client(seconds_since=math.inf)


def _all_zero(features: dict) -> bool:
    return all(
        features[r][f"{t}_rps"] == 0.0
        for r in REGIONS
        for t in TIERS
    )


# ── live query ────────────────────────────────────────────────────────────────

def test_live_query_returns_features_and_populates_cache():
    extractor = FeatureExtractor()
    client = _live_client()
    features = extractor.extract(client)
    assert features is extractor._cache
    assert extractor._cache_at > 0


def test_live_query_twice_updates_cache():
    extractor = FeatureExtractor()
    extractor.extract(_live_client())
    first_at = extractor._cache_at

    extractor.extract(_live_client())
    assert extractor._cache_at >= first_at


# ── stale within window ───────────────────────────────────────────────────────

def test_stale_within_window_returns_cached_features():
    extractor = FeatureExtractor()
    # Seed cache from a live tick
    live = _live_client()
    first = extractor.extract(live)

    # Prometheus drops — cache is still fresh
    extractor._cache_at = time.time()
    second = extractor.extract(_dead_client())

    assert second is first


def test_stale_within_window_does_not_update_cache_at():
    extractor = FeatureExtractor()
    extractor.extract(_live_client())
    cached_at = extractor._cache_at

    extractor.extract(_dead_client())
    assert extractor._cache_at == cached_at  # unchanged — no live query happened


# ── stale beyond window ───────────────────────────────────────────────────────

def test_stale_beyond_window_returns_static_defaults():
    extractor = FeatureExtractor()
    # Seed with non-zero traffic so we can tell the difference
    extractor._cache = {
        r: {f"{t}_rps": 99.0 for t in TIERS} | {"rejection_rate": 0.5}
        for r in REGIONS
    }
    extractor._cache_at = time.time() - STALE_WINDOW_SECONDS - 10

    features = extractor.extract(_dead_client())

    assert _all_zero(features)


def test_stale_beyond_window_does_not_serve_stale_cache():
    extractor = FeatureExtractor()
    extractor._cache = {r: {f"{t}_rps": 50.0 for t in TIERS} | {"rejection_rate": 0.1} for r in REGIONS}
    extractor._cache_at = time.time() - STALE_WINDOW_SECONDS - 1

    features = extractor.extract(_dead_client())

    for r in REGIONS:
        for t in TIERS:
            assert features[r][f"{t}_rps"] == 0.0, f"expected 0 for {r}/{t}, got {features[r][f'{t}_rps']}"


# ── never connected ───────────────────────────────────────────────────────────

def test_never_connected_returns_static_defaults():
    extractor = FeatureExtractor()  # empty cache, _cache_at=0
    features = extractor.extract(_dead_client())
    assert _all_zero(features)


def test_static_defaults_are_independent_copies():
    """Each call must return a fresh dict so callers can't mutate the defaults."""
    extractor = FeatureExtractor()
    a = extractor.extract(_dead_client())
    b = extractor.extract(_dead_client())
    a["us"]["free_rps"] = 999.0
    assert b["us"]["free_rps"] == 0.0
