"""
sync/counter.py — RegionalCounter: Lua-atomic max-merge into rl:global hash.

Spec:        docs/superpowers/specs/2026-04-25-sync-service-design.md §5.counter.py
Constitution: docs/sync-constitution.md Art III §6 (single-writer-per-slot)
Reads:       rl:global:{tier}:{user_id}:{window_id} (HGETALL, HGET)
Writes:      rl:global:{tier}:{user_id}:{window_id} (Lua max-merge HSET)
Don't:       write own region's slot (gateway exclusive); accept negative values.

Owns Contract 2 key schema. Atomic max-merge guarantees idempotency under
concurrent writers; HSET only fires if incoming > current.
"""
from __future__ import annotations

from typing import AsyncIterator
from redis.asyncio import Redis

GLOBAL_TTL_SECONDS = 300

_MAX_MERGE_LUA = """
local cur = redis.call('HGET', KEYS[1], ARGV[1])
if (not cur) or (tonumber(cur) < tonumber(ARGV[2])) then
  redis.call('HSET', KEYS[1], ARGV[1], ARGV[2])
  redis.call('EXPIRE', KEYS[1], ARGV[3])
  return 1
end
return 0
"""


class OwnSlotWriteError(Exception):
    """Raised when caller attempts to write the counter's own region slot."""


def _global_key(tier: str, user_id: str, window_id: int) -> str:
    return f"rl:global:{tier}:{user_id}:{window_id}"


class RegionalCounter:
    def __init__(self, region: str, redis: Redis) -> None:
        self._region = region
        self._redis = redis
        self._max_merge = redis.register_script(_MAX_MERGE_LUA)

    @property
    def region(self) -> str:
        return self._region

    async def apply_remote_slot(
        self,
        tier: str,
        user_id: str,
        window_id: int,
        peer_region: str,
        value: int,
    ) -> bool:
        if peer_region == self._region:
            raise OwnSlotWriteError(
                f"sync may not write own region's slot ({peer_region}); gateway is the writer"
            )
        if value < 0:
            raise ValueError(f"slot value must be non-negative; got {value}")
        key = _global_key(tier, user_id, window_id)
        result = await self._max_merge(keys=[key], args=[peer_region, value, GLOBAL_TTL_SECONDS])
        return bool(result)

    async def get_global(
        self, tier: str, user_id: str, window_id: int
    ) -> dict[str, int]:
        key = _global_key(tier, user_id, window_id)
        raw = await self._redis.hgetall(key)
        return {k.decode() if isinstance(k, bytes) else k: int(v) for k, v in raw.items()}

    async def get_own_slot(
        self, tier: str, user_id: str, window_id: int
    ) -> int:
        key = _global_key(tier, user_id, window_id)
        raw = await self._redis.hget(key, self._region)
        return int(raw) if raw is not None else 0

    async def scan_window_keys(self, window_id: int) -> AsyncIterator[tuple[str, str]]:
        pattern = f"rl:global:*:*:{window_id}"
        async for key in self._redis.scan_iter(match=pattern, count=500):
            key_str = key.decode() if isinstance(key, bytes) else key
            parts = key_str.split(":")
            if len(parts) != 5:
                continue
            yield parts[2], parts[3]
