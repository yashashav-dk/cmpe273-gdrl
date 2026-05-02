"""
sync/transport.py — pub/sub transport over redis-py async.

Spec:        docs/superpowers/specs/2026-04-25-sync-service-design.md §5.transport.py
Constitution: docs/sync-constitution.md Art III §3 (transport)
Reads:       rl:sync:counter on local + 2 peer Redises (subscribe)
Writes:      rl:sync:counter on local Redis only (publish, reconcile envelopes)
Don't:       publish to peer Redises directly; share PubSub instances across regions.

Each Transport owns one Redis Pub/Sub connection per region (3 total). Peer
subscribers tag yielded messages with origin region so the relay can apply
partition rules. Auto-reconnects with exponential backoff handled by redis-py
when health_check_interval is set; on a hard disconnect the AsyncIterator
closes and the caller restarts subscription.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator
from redis.asyncio import Redis


class Transport:
    def __init__(
        self,
        region: str,
        local_redis: Redis,
        peer_redises: dict[str, Redis],
        channel: str,
    ) -> None:
        self._region = region
        self._local = local_redis
        self._peers = {**peer_redises, region: local_redis}
        self._channel = channel

    async def publish_local(self, payload: bytes) -> int:
        return await self._local.publish(self._channel, payload)

    async def subscribe_peers(self) -> AsyncIterator[tuple[str, bytes]]:
        queue: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue()
        tasks: list[asyncio.Task] = []
        for origin, client in self._peers.items():
            tasks.append(asyncio.create_task(self._pump(origin, client, queue)))
        try:
            while True:
                origin, raw = await queue.get()
                yield origin, raw
        finally:
            for t in tasks:
                t.cancel()
            for t in tasks:
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

    async def _pump(self, origin: str, client: Redis, queue: asyncio.Queue) -> None:
        pubsub = client.pubsub()
        await pubsub.subscribe(self._channel)
        try:
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                data = msg.get("data")
                if isinstance(data, bytes):
                    await queue.put((origin, data))
        finally:
            await pubsub.unsubscribe(self._channel)
            await pubsub.aclose()
