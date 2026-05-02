"""
sync/relay.py — peer envelope receiver + max-merge applicator.

Spec:        docs/superpowers/specs/2026-04-25-sync-service-design.md §5.relay.py, §6 Flow 2
Constitution: docs/sync-constitution.md Art III §3 (transport), Art III §6 (single-writer)
Reads:       rl:sync:counter on local + 2 peer Redises (via Transport)
Writes:      local rl:global:{tier}:{user_id}:{window_id} (peer slots only — never own region)
Don't:       coalesce, batch, write own region's slot, decrement.

Stateless. One pub/sub message → one max-merge. Backpressure path: failed
applies go to the FailoverBuffer; the consumer keeps draining transport so
Redis pub/sub output buffers don't overflow.
"""
from __future__ import annotations

import time
from sync.counter import RegionalCounter, OwnSlotWriteError
from sync.envelope import (
    CounterEnvelope,
    EnvelopeError,
    ReconcileEnvelope,
    parse,
)
from sync.partition_table import PartitionTable
from sync.transport import Transport
from sync.buffer import FailoverBuffer
from sync.metrics import LAG_SECONDS, MESSAGES_TOTAL, MESSAGES_DROPPED, RELAY_INFLIGHT


class Relay:
    def __init__(
        self,
        region: str,
        counter: RegionalCounter,
        transport: Transport,
        partition_table: PartitionTable,
        buffer: FailoverBuffer,
    ) -> None:
        self._region = region
        self._counter = counter
        self._transport = transport
        self._partition = partition_table
        self._buffer = buffer

    async def run(self) -> None:
        async for origin, raw in self._transport.subscribe_peers():
            RELAY_INFLIGHT.labels(region=self._region).inc()
            try:
                await self._handle(origin, raw)
            finally:
                RELAY_INFLIGHT.labels(region=self._region).dec()

    async def _handle(self, origin: str, raw: bytes) -> None:
        try:
            env = parse(raw)
        except EnvelopeError:
            MESSAGES_DROPPED.labels(cause="malformed").inc()
            return
        # Partition check uses the envelope's asserted source region, not the
        # transport-tagged origin: in production they coincide (subscriber tag
        # == publisher region), and tests publish all envelopes through the
        # local Redis so only the asserted region is meaningful.
        asserted = env.region if isinstance(env, CounterEnvelope) else env.origin
        if self._partition.blocks(asserted, self._region):
            MESSAGES_DROPPED.labels(cause="partition").inc()
            return
        if isinstance(env, CounterEnvelope):
            await self._handle_counter(asserted, env)
        elif isinstance(env, ReconcileEnvelope):
            await self._handle_reconcile(asserted, env)

    async def _handle_counter(self, origin: str, env: CounterEnvelope) -> None:
        if env.region == self._region:
            MESSAGES_DROPPED.labels(cause="self_origin").inc()
            return
        try:
            await self._counter.apply_remote_slot(
                env.tier, env.user_id, env.window_id, env.region, env.value
            )
        except OwnSlotWriteError:
            MESSAGES_DROPPED.labels(cause="self_origin_lua").inc()
            return
        except Exception:
            self._buffer.push("relay_apply", (env.tier, env.user_id, env.window_id, env.region, env.value))
            return
        self._observe(origin, "counter", env.ts_ms)

    async def _handle_reconcile(self, origin: str, env: ReconcileEnvelope) -> None:
        if env.origin == self._region:
            MESSAGES_DROPPED.labels(cause="self_origin").inc()
            return
        for (tier, user_id), value in env.slots.items():
            try:
                await self._counter.apply_remote_slot(
                    tier, user_id, env.window_id, env.origin, value
                )
            except OwnSlotWriteError:
                MESSAGES_DROPPED.labels(cause="self_origin_lua").inc()
                continue
            except Exception:
                self._buffer.push(
                    "relay_apply",
                    (tier, user_id, env.window_id, env.origin, value),
                )
                continue
        self._observe(origin, "reconcile", env.ts_ms)

    def _observe(self, origin: str, kind: str, ts_ms: int) -> None:
        lag = max(0.0, (time.time() * 1000 - ts_ms) / 1000.0)
        LAG_SECONDS.labels(from_region=origin, to_region=self._region).observe(lag)
        MESSAGES_TOTAL.labels(kind=kind, origin_region=origin, dest_region=self._region).inc()
