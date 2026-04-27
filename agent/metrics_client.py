from __future__ import annotations

from typing import Any

from prometheus_api_client import PrometheusConnect

PROMETHEUS_URL = "http://localhost:9090"


class PrometheusClient:
    def __init__(self, url: str = PROMETHEUS_URL) -> None:
        self._prom = PrometheusConnect(url=url, disable_ssl=True)

    def request_rate(self, window: str = "1m") -> list[dict[str, Any]]:
        """RPS per region+tier averaged over `window` (Contract 3: rl_requests_total)."""
        return self._prom.custom_query(
            query=f"sum(rate(rl_requests_total[{window}])) by (region, tier)"
        )

    def rejection_rate(self, window: str = "1m") -> list[dict[str, Any]]:
        """Fraction of denied requests per region+tier over `window`."""
        return self._prom.custom_query(
            query=(
                f'sum(rate(rl_requests_total{{decision="deny"}}[{window}])) by (region, tier)'
                f" / sum(rate(rl_requests_total[{window}])) by (region, tier)"
            )
        )
