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
