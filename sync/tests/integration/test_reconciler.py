"""
sync/tests/integration/test_reconciler.py — Layer 2 integration tests for the
reconciler. Verifies window scan, chunked broadcast, and idempotent self-skip.
"""
import asyncio
import json
import pytest
from sync.counter import RegionalCounter
from sync.transport import Transport
from sync.reconciler import Reconciler


@pytest.mark.asyncio
async def test_reconcile_once_broadcasts_own_slots(redis_client):
    # Simulate gateway HIncrBy on three users in one window.
    await redis_client.hset("rl:global:free:u_1:100", mapping={"us": 5, "eu": 3})
    await redis_client.hset("rl:global:free:u_2:100", mapping={"us": 7})
    await redis_client.hset("rl:global:premium:u_3:100", mapping={"us": 99, "asia": 1})

    counter = RegionalCounter("us", redis_client)
    transport = Transport("us", redis_client, {}, "rl:sync:counter")

    pubsub = redis_client.pubsub()
    await pubsub.subscribe("rl:sync:counter")
    received: list[dict] = []

    async def consume():
        async for msg in pubsub.listen():
            if msg.get("type") == "message":
                received.append(json.loads(msg["data"]))
                if len(received) >= 1:
                    break

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.3)

    reconciler = Reconciler("us", counter, transport, period_s=30, chunk_size=1000)
    stats = await reconciler.reconcile_once(window_id=100)
    await asyncio.wait_for(consumer, timeout=5.0)

    assert stats.keys_processed == 3
    env = received[0]
    assert env["kind"] == "reconcile"
    assert env["v"] == 1
    assert env["origin"] == "us"
    assert env["window_id"] == 100
    assert env["slots"] == {"free:u_1": 5, "free:u_2": 7, "premium:u_3": 99}
    await pubsub.aclose()


@pytest.mark.asyncio
async def test_reconcile_once_chunks_at_chunk_size(redis_client):
    for i in range(5):
        await redis_client.hset(f"rl:global:free:u_{i}:200", "us", i)

    counter = RegionalCounter("us", redis_client)
    transport = Transport("us", redis_client, {}, "rl:sync:counter")

    pubsub = redis_client.pubsub()
    await pubsub.subscribe("rl:sync:counter")
    received: list[dict] = []

    async def consume():
        async for msg in pubsub.listen():
            if msg.get("type") == "message":
                received.append(json.loads(msg["data"]))
                if len(received) >= 3:
                    break

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.3)

    reconciler = Reconciler("us", counter, transport, period_s=30, chunk_size=2)
    stats = await reconciler.reconcile_once(window_id=200)
    await asyncio.wait_for(consumer, timeout=5.0)

    assert stats.keys_processed == 5
    assert len(received) == 3  # 5 keys / chunk_size=2 = ceil(5/2) = 3 messages
    total_slots = sum(len(env["slots"]) for env in received)
    assert total_slots == 5
    await pubsub.aclose()


@pytest.mark.asyncio
async def test_reconcile_once_skips_users_with_no_own_slot(redis_client):
    # Only eu wrote this slot; us has nothing to broadcast.
    await redis_client.hset("rl:global:free:u_1:300", "eu", 5)

    counter = RegionalCounter("us", redis_client)
    transport = Transport("us", redis_client, {}, "rl:sync:counter")
    reconciler = Reconciler("us", counter, transport, period_s=30, chunk_size=1000)
    stats = await reconciler.reconcile_once(window_id=300)
    assert stats.keys_processed == 0
