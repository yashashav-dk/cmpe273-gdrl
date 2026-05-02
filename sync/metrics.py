"""
sync/metrics.py — Prometheus metric definitions, registered once.

Spec: docs/superpowers/specs/2026-04-25-sync-service-design.md §8
"""
from __future__ import annotations

from prometheus_client import REGISTRY, Counter, Gauge, Histogram  # noqa: F401  (REGISTRY re-exported for admin.py in Task 23)

LAG_SECONDS = Histogram(
    "rl_sync_lag_seconds",
    "Sync envelope lag in seconds, measured at receive time.",
    labelnames=("from_region", "to_region"),
    buckets=(0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10),
)
MESSAGES_TOTAL = Counter(
    "rl_sync_messages_total",
    "Sync messages received by kind.",
    labelnames=("kind", "origin_region", "dest_region"),
)
MESSAGES_DROPPED = Counter(
    "rl_messages_dropped_total",
    "Sync messages dropped (partition, malformed, self-origin).",
    labelnames=("cause",),
)
RELAY_INFLIGHT = Gauge(
    "rl_relay_inflight",
    "Relay envelopes currently in flight.",
    labelnames=("region",),
)
RECONCILE_DURATION = Histogram(
    "rl_reconcile_duration_seconds",
    "Reconcile pass duration in seconds.",
    labelnames=("region",),
)
RECONCILE_KEYS = Counter(
    "rl_reconcile_keys_processed",
    "Keys processed in reconcile.",
    labelnames=("region",),
)
RECONCILE_PERIOD = Gauge(
    "rl_reconcile_period_s",
    "Configured reconcile period in seconds.",
    labelnames=("region",),
)
PARTITION_ACTIVE = Gauge(
    "rl_partition_active",
    "1 if partition rule is active for from_region → to_region.",
    labelnames=("from_region", "to_region"),
)
BUFFER_SIZE = Gauge(
    "rl_sync_buffer_size",
    "Failover buffer size by kind.",
    labelnames=("region", "kind"),
)
BUFFER_OVERFLOW = Counter(
    "rl_sync_buffer_overflow_total",
    "Failover buffer overflow drops.",
    labelnames=("region", "kind"),
)
LOCAL_REDIS_UP = Gauge(
    "rl_local_redis_up",
    "1 if local Redis is reachable.",
    labelnames=("region",),
)
