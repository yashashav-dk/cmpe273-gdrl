"""
sync/tests/integration/test_counter_redis.py — Layer 2 integration tests for
RegionalCounter against a real Redis (via testcontainers).

Spec: docs/superpowers/specs/2026-04-25-sync-service-design.md §5.counter.py
"""
import pytest
from sync.counter import RegionalCounter, OwnSlotWriteError


@pytest.mark.asyncio
async def test_apply_remote_slot_writes_when_higher(redis_client):
    counter = RegionalCounter("us", redis_client)
    applied = await counter.apply_remote_slot("free", "u_1", 100, "eu", 5)
    assert applied is True
    slots = await counter.get_global("free", "u_1", 100)
    assert slots == {"eu": 5}


@pytest.mark.asyncio
async def test_apply_remote_slot_skips_when_lower(redis_client):
    counter = RegionalCounter("us", redis_client)
    await counter.apply_remote_slot("free", "u_1", 100, "eu", 10)
    applied = await counter.apply_remote_slot("free", "u_1", 100, "eu", 5)
    assert applied is False
    slots = await counter.get_global("free", "u_1", 100)
    assert slots == {"eu": 10}


@pytest.mark.asyncio
async def test_apply_remote_slot_skips_when_equal(redis_client):
    counter = RegionalCounter("us", redis_client)
    await counter.apply_remote_slot("free", "u_1", 100, "eu", 7)
    applied = await counter.apply_remote_slot("free", "u_1", 100, "eu", 7)
    assert applied is False


@pytest.mark.asyncio
async def test_apply_remote_slot_refuses_own_region(redis_client):
    counter = RegionalCounter("us", redis_client)
    with pytest.raises(OwnSlotWriteError):
        await counter.apply_remote_slot("free", "u_1", 100, "us", 5)


@pytest.mark.asyncio
async def test_apply_remote_slot_refuses_negative_value(redis_client):
    counter = RegionalCounter("us", redis_client)
    with pytest.raises(ValueError):
        await counter.apply_remote_slot("free", "u_1", 100, "eu", -1)


@pytest.mark.asyncio
async def test_apply_remote_slot_sets_ttl(redis_client):
    counter = RegionalCounter("us", redis_client)
    await counter.apply_remote_slot("free", "u_1", 100, "eu", 5)
    ttl = await redis_client.ttl("rl:global:free:u_1:100")
    assert 0 < ttl <= 300


@pytest.mark.asyncio
async def test_apply_remote_slot_refreshes_ttl_on_higher(redis_client):
    counter = RegionalCounter("us", redis_client)
    await counter.apply_remote_slot("free", "u_1", 100, "eu", 5)
    await redis_client.expire("rl:global:free:u_1:100", 10)
    await counter.apply_remote_slot("free", "u_1", 100, "eu", 6)
    ttl = await redis_client.ttl("rl:global:free:u_1:100")
    assert ttl > 10  # refreshed back to 300


@pytest.mark.asyncio
async def test_apply_remote_slot_idempotent_replay(redis_client):
    counter = RegionalCounter("us", redis_client)
    for _ in range(100):
        await counter.apply_remote_slot("free", "u_1", 100, "eu", 7)
    slots = await counter.get_global("free", "u_1", 100)
    assert slots == {"eu": 7}


@pytest.mark.asyncio
async def test_get_own_slot_returns_zero_when_absent(redis_client):
    counter = RegionalCounter("us", redis_client)
    assert await counter.get_own_slot("free", "u_1", 100) == 0


@pytest.mark.asyncio
async def test_get_own_slot_returns_value_after_hincrby(redis_client):
    # Simulate gateway HIncrBy behavior — gateway writes own region's slot directly.
    await redis_client.hincrby("rl:global:free:u_1:100", "us", 42)
    counter = RegionalCounter("us", redis_client)
    assert await counter.get_own_slot("free", "u_1", 100) == 42


@pytest.mark.asyncio
async def test_scan_window_keys_yields_only_matching_window(redis_client):
    await redis_client.hset("rl:global:free:u_1:100", "us", 1)
    await redis_client.hset("rl:global:free:u_2:100", "us", 1)
    await redis_client.hset("rl:global:free:u_3:101", "us", 1)
    counter = RegionalCounter("us", redis_client)
    found: list[tuple[str, str]] = []
    async for entry in counter.scan_window_keys(100):
        found.append(entry)
    assert sorted(found) == [("free", "u_1"), ("free", "u_2")]
