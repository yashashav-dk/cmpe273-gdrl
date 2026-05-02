"""
sync/dev/gateway_stub.py — solo-demo harness mimicking Nikhil's gateway at the
sync surface only. Emits Contract-2 envelopes after a fake HIncrBy on local
Redis. Used by docker-compose.sync-only.yml and tests/e2e to exercise sync
without depending on Nikhil's Go gateway.

Not for production. Not part of the sync runtime path.

Spec: docs/superpowers/specs/2026-04-25-sync-service-design.md §5 (gateway-stub harness, dev/)
Constitution: docs/sync-constitution.md Art III §4 (gateway → sync coupling)
"""
from __future__ import annotations

import json
import time
from redis.asyncio import Redis

CHANNEL = "rl:sync:counter"


class GatewayStub:
    def __init__(self, region: str, redis: Redis) -> None:
        self._region = region
        self._redis = redis

    @property
    def region(self) -> str:
        return self._region

    async def allow_request(self, tier: str, user_id: str, window_id: int) -> int:
        global_key = f"rl:global:{tier}:{user_id}:{window_id}"
        new_value = await self._redis.hincrby(global_key, self._region, 1)
        await self._redis.expire(global_key, 120)
        envelope = {
            "tier": tier,
            "user_id": user_id,
            "window_id": window_id,
            "region": self._region,
            "value": int(new_value),
            "ts_ms": int(time.time() * 1000),
        }
        await self._redis.publish(CHANNEL, json.dumps(envelope, separators=(",", ":")))
        return int(new_value)
