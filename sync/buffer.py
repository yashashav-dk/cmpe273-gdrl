"""
sync/buffer.py — bounded FIFO failover buffer for degraded-mode replay.

Spec:        docs/superpowers/specs/2026-04-25-sync-service-design.md §5.buffer.py, §6 Flow 5
Constitution: docs/sync-constitution.md Art VII (defaults: 10 000 entries/kind)
Reads:       (in-memory only)
Writes:      (in-memory only — emits Prometheus gauge updates)
Don't:       persist to disk; share across regions; hold references to live
             Redis clients (state must be loseable on restart).

Used when relay's `apply_remote_slot` raises (local Redis dead) or when
reconciler's publish fails. A watchdog drains the buffer when the local
Redis becomes reachable again. Bounded so a long outage cannot OOM the
process; reconcile fills any actually-lost data on recovery.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Iterator
from sync.metrics import BUFFER_SIZE, BUFFER_OVERFLOW


class FailoverBuffer:
    def __init__(self, max_entries_per_kind: int = 10_000, region: str = "unknown") -> None:
        self._cap = max_entries_per_kind
        self._region = region
        self._queues: dict[str, deque] = {}

    def push(self, kind: str, payload: Any) -> bool:
        q = self._queues.setdefault(kind, deque())
        if len(q) >= self._cap:
            q.popleft()
            BUFFER_OVERFLOW.labels(region=self._region, kind=kind).inc()
            q.append(payload)
            BUFFER_SIZE.labels(region=self._region, kind=kind).set(len(q))
            return False
        q.append(payload)
        BUFFER_SIZE.labels(region=self._region, kind=kind).set(len(q))
        return True

    def drain(self, kind: str) -> Iterator[Any]:
        q = self._queues.get(kind)
        if not q:
            return
        while q:
            yield q.popleft()
            BUFFER_SIZE.labels(region=self._region, kind=kind).set(len(q))

    def size(self, kind: str) -> int:
        return len(self._queues.get(kind, ()))
