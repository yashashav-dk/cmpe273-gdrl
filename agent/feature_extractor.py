from __future__ import annotations

from metrics_client import PrometheusClient, REGIONS, TIERS

# {region: {free_rps, premium_rps, internal_rps, rejection_rate}}
Features = dict[str, dict[str, float]]


def extract(client: PrometheusClient, window: str = "5m") -> Features:
    """Reshape last `window` of Prometheus metrics into a flat per-region feature dict.

    Seeds every region+tier with 0.0 so downstream code never sees missing keys,
    even when Prometheus has gaps (e.g. a tier with zero traffic).
    """
    features: Features = {
        r: {f"{t}_rps": 0.0 for t in TIERS} | {"rejection_rate": 0.0}
        for r in REGIONS
    }

    for row in client.request_rate(window=window):
        region = row["metric"].get("region")
        tier = row["metric"].get("tier")
        if region in features and tier in TIERS:
            features[region][f"{tier}_rps"] = _fval(row)

    # Rejection rate: per-region average across tiers (simple mean — good enough for policy decisions)
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
