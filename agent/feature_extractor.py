from __future__ import annotations

import time

from metrics_client import PrometheusClient, REGIONS, TIERS

Features = dict[str, dict[str, float]]

# Use cached features up to this long after Prometheus becomes unreachable
STALE_WINDOW_SECONDS = 120

# Zero-RPS conservative defaults — avoids over-throttling when we have no data at all
_STATIC_DEFAULTS: Features = {
    r: {f"{t}_rps": 0.0 for t in TIERS} | {"rejection_rate": 0.0}
    for r in REGIONS
}


class FeatureExtractor:
    """Extracts per-region features from Prometheus with graceful staleness handling.

    On each call to extract():
      - If Prometheus was live in the current tick: return fresh features and cache them.
      - If Prometheus is down and cache is < STALE_WINDOW_SECONDS old: return cached features.
      - If Prometheus is down and cache is expired (or empty): return zero-RPS static defaults.

    The "live" check uses client.seconds_since_live() — updated by _query() on every
    successful Prometheus call, so a value < 15 s means the current tick's query succeeded.
    """

    def __init__(self) -> None:
        self._cache: Features | None = None
        self._cache_at: float = 0.0

    def extract(self, client: PrometheusClient, window: str = "5m") -> Features:
        features = _do_extract(client, window)

        if client.seconds_since_live() < 15:
            self._cache = features
            self._cache_at = time.time()
            return features

        stale_secs = time.time() - self._cache_at
        if self._cache is not None and stale_secs <= STALE_WINDOW_SECONDS:
            return self._cache

        return {r: dict(row) for r, row in _STATIC_DEFAULTS.items()}


def _do_extract(client: PrometheusClient, window: str) -> Features:
    features: Features = {
        r: {f"{t}_rps": 0.0 for t in TIERS} | {"rejection_rate": 0.0}
        for r in REGIONS
    }

    for row in client.request_rate(window=window):
        region = row["metric"].get("region")
        tier = row["metric"].get("tier")
        if region in features and tier in TIERS:
            features[region][f"{tier}_rps"] = _fval(row)

    rej_by_region: dict[str, list[float]] = {r: [] for r in REGIONS}
    for row in client.rejection_rate(window=window):
        region = row["metric"].get("region")
        if region in rej_by_region:
            rej_by_region[region].append(_fval(row))

    for region, rates in rej_by_region.items():
        if rates:
            features[region]["rejection_rate"] = round(sum(rates) / len(rates), 4)

    return features


def _fval(row: dict) -> float:
    try:
        return float(row["value"][1])
    except (KeyError, IndexError, ValueError, TypeError):
        return 0.0
