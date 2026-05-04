"""
sync/reconciler.py — periodic full-window scan + broadcast.

Spec:        docs/superpowers/specs/2026-04-25-sync-service-design.md §5.reconciler.py, §6 Flow 3
Constitution: docs/sync-constitution.md Art III §3 (reconcile is the correctness mechanism)
Reads:       local rl:global:*:*:{window_id} (HGETALL via scan + HGET own slot)
Writes:      rl:sync:counter (kind=reconcile envelopes only)
Don't:       broadcast slots from other regions (only own region's slots travel
             across the wire — peers re-broadcast their own).

Runs immediately on startup (cold-start catch-up) then every period_s. Two
windows scanned per pass (current + previous) to absorb minute-boundary skew.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from sync.counter import RegionalCounter
from sync.envelope import ReconcileEnvelope, serialize_reconcile
from sync.transport import Transport
from sync.metrics import RECONCILE_DURATION, RECONCILE_KEYS, RECONCILE_PERIOD


@dataclass
class ReconcileStats:
    keys_processed: int
    chunks_published: int


class Reconciler:
    def __init__(
        self,
        region: str,
        counter: RegionalCounter,
        transport: Transport,
        period_s: int = 30,
        chunk_size: int = 1000,
    ) -> None:
        self._region = region
        self._counter = counter
        self._transport = transport
        self._period_s = period_s
        self._chunk_size = chunk_size
        RECONCILE_PERIOD.labels(region=region).set(period_s)

    def set_period(self, period_s: int) -> None:
        self._period_s = period_s
        RECONCILE_PERIOD.labels(region=self._region).set(period_s)

    async def run(self) -> None:
        # Cold-start catch-up
        await self._tick()
        while True:
            await asyncio.sleep(self._period_s)
            await self._tick()

    async def _tick(self) -> None:
        now_window = int(time.time() // 60)
        for window_id in (now_window, now_window - 1):
            try:
                await self.reconcile_once(window_id)
            except Exception:
                continue

    async def reconcile_once(self, window_id: int) -> ReconcileStats:
        start = time.time()
        chunk: dict[tuple[str, str], int] = {}
        keys = 0
        chunks = 0
        async for tier, user_id in self._counter.scan_window_keys(window_id):
            global_slots = await self._counter.get_global(tier, user_id, window_id)
            if self._region not in global_slots:
                continue
            value = global_slots[self._region]
            if value < 0:
                continue
            chunk[(tier, user_id)] = value
            keys += 1
            if len(chunk) >= self._chunk_size:
                await self._publish_chunk(window_id, chunk)
                chunk = {}
                chunks += 1
        if chunk:
            await self._publish_chunk(window_id, chunk)
            chunks += 1
        RECONCILE_DURATION.labels(region=self._region).observe(time.time() - start)
        RECONCILE_KEYS.labels(region=self._region).inc(keys)
        return ReconcileStats(keys_processed=keys, chunks_published=chunks)

    async def _publish_chunk(self, window_id: int, slots: dict[tuple[str, str], int]) -> None:
        env = ReconcileEnvelope(
            origin=self._region,
            window_id=window_id,
            ts_ms=int(time.time() * 1000),
            slots=slots,
        )
        payload = serialize_reconcile(env)
        await self._transport.publish_local(payload)
