from __future__ import annotations

import math
import random
import time
from datetime import datetime, timedelta
from typing import Any

PROMETHEUS_URL = "http://localhost:9090"
REGIONS: tuple[str, ...] = ("us", "eu", "asia")
TIERS: tuple[str, ...] = ("free", "premium", "internal")

# Steady-state RPS per tier — keeps mock data realistic while stack is offline
_MOCK_BASE_RPS: dict[str, float] = {"free": 45.0, "premium": 12.0, "internal": 3.0}


class PrometheusClient:
    def __init__(self, url: str = PROMETHEUS_URL) -> None:
        self._url = url
        self._prom: Any = None
        try:
            from prometheus_api_client import PrometheusConnect
            self._prom = PrometheusConnect(url=url, disable_ssl=True)
        except Exception:
            pass

    def _query(self, promql: str) -> list[dict[str, Any]] | None:
        if self._prom is None:
            return None
        try:
            return self._prom.custom_query(query=promql)
        except Exception:
            print(f"[metrics_client] Prometheus unreachable at {self._url} — using synthetic data")
            return None

    def request_rate(self, window: str = "1m") -> list[dict[str, Any]]:
        """RPS per region+tier averaged over `window` (Contract 3: rl_requests_total)."""
        result = self._query(f"sum(rate(rl_requests_total[{window}])) by (region, tier)")
        return result if result is not None else _synthetic_request_rate()

    def rejection_rate(self, window: str = "1m") -> list[dict[str, Any]]:
        """Fraction of denied requests per region+tier over `window`."""
        result = self._query(
            f'sum(rate(rl_requests_total{{decision="denied"}}[{window}])) by (region, tier)'
            f" / sum(rate(rl_requests_total[{window}])) by (region, tier)"
        )
        return result if result is not None else _synthetic_rejection_rate()

    def request_rate_range(
        self, window_minutes: int = 30, step: str = "1m"
    ) -> dict[str, list[float]]:
        """RPS time series per 'region/tier' over the last window_minutes.

        Returns {"us/free": [rps_t0, ..., rps_tn], ...} — used to warm-start EWMA.
        """
        if self._prom is not None:
            try:
                end_time = datetime.now()
                start_time = end_time - timedelta(minutes=window_minutes)
                rows = self._prom.custom_query_range(
                    query="sum(rate(rl_requests_total[1m])) by (region, tier)",
                    start_time=start_time,
                    end_time=end_time,
                    step=step,
                )
                series: dict[str, list[float]] = {}
                for row in rows:
                    region = row["metric"].get("region", "")
                    tier = row["metric"].get("tier", "")
                    if region and tier:
                        series[f"{region}/{tier}"] = [float(v[1]) for v in row["values"]]
                if series:
                    return series
            except Exception:
                print(f"[metrics_client] range query failed — using synthetic history")
        return _synthetic_request_rate_range(window_minutes)


def _synthetic_request_rate() -> list[dict[str, Any]]:
    ts = time.time()
    return [
        {
            "metric": {"region": r, "tier": t},
            "value": [ts, str(round(_MOCK_BASE_RPS[t] * random.uniform(0.8, 1.2), 2))],
        }
        for r in REGIONS
        for t in TIERS
    ]


def _synthetic_request_rate_range(window_minutes: int) -> dict[str, list[float]]:
    # Mirrors Prathamesh's diurnal model: amplitude=0.7 sinusoid over a 60-min compressed period
    result: dict[str, list[float]] = {}
    for r in REGIONS:
        for t in TIERS:
            base = _MOCK_BASE_RPS[t]
            series = []
            for i in range(window_minutes):
                multiplier = max(0.1, 1.0 + 0.7 * math.sin(2 * math.pi * i / 60 - math.pi / 2))
                series.append(round(base * multiplier * random.uniform(0.9, 1.1), 2))
            result[f"{r}/{t}"] = series
    return result


def _synthetic_rejection_rate() -> list[dict[str, Any]]:
    ts = time.time()
    return [
        {
            "metric": {"region": r, "tier": t},
            "value": [ts, str(round(random.uniform(0.0, 0.05), 4))],
        }
        for r in REGIONS
        for t in TIERS
    ]
