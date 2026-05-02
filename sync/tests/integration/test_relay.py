"""
sync/tests/integration/test_relay.py — Layer 2 integration tests for the relay
loop. Each test uses one Redis as a stand-in for both local + peer surface.
"""
import asyncio
import json
import pytest
from sync.counter import RegionalCounter
from sync.partition_table import PartitionTable
from sync.transport import Transport
from sync.relay import Relay
from sync.buffer import FailoverBuffer  # forward ref — created in Task 22


def _counter_payload(*, tier, user_id, window_id, region, value, ts_ms=1) -> bytes:
    return json.dumps({
        "tier": tier, "user_id": user_id, "window_id": window_id,
        "region": region, "value": value, "ts_ms": ts_ms,
    }).encode()


@pytest.mark.asyncio
async def test_relay_applies_peer_counter_envelope(redis_client):
    counter = RegionalCounter("us", redis_client)
    transport = Transport(
        region="us",
        local_redis=redis_client,
        peer_redises={},  # only own client; envelope arrives via local publish
        channel="rl:sync:counter",
    )
    table = PartitionTable()
    buffer = FailoverBuffer(max_entries_per_kind=100)
    relay = Relay("us", counter, transport, table, buffer)
    task = asyncio.create_task(relay.run())
    await asyncio.sleep(0.3)

    await redis_client.publish(
        "rl:sync:counter",
        _counter_payload(tier="free", user_id="u_1", window_id=10, region="eu", value=5),
    )
    await asyncio.sleep(0.5)

    slots = await counter.get_global("free", "u_1", 10)
    assert slots == {"eu": 5}
    task.cancel()


@pytest.mark.asyncio
async def test_relay_drops_self_origin_counter(redis_client):
    counter = RegionalCounter("us", redis_client)
    transport = Transport(
        region="us", local_redis=redis_client,
        peer_redises={}, channel="rl:sync:counter",
    )
    relay = Relay("us", counter, transport, PartitionTable(), FailoverBuffer(100))
    task = asyncio.create_task(relay.run())
    await asyncio.sleep(0.3)

    await redis_client.publish(
        "rl:sync:counter",
        _counter_payload(tier="free", user_id="u_1", window_id=10, region="us", value=42),
    )
    await asyncio.sleep(0.5)

    slots = await counter.get_global("free", "u_1", 10)
    assert slots == {}  # self-origin dropped
    task.cancel()


@pytest.mark.asyncio
async def test_relay_drops_when_partition_blocks(redis_client):
    counter = RegionalCounter("us", redis_client)
    transport = Transport(
        region="us", local_redis=redis_client,
        peer_redises={}, channel="rl:sync:counter",
    )
    table = PartitionTable()
    table.add("eu", "us")
    relay = Relay("us", counter, transport, table, FailoverBuffer(100))
    task = asyncio.create_task(relay.run())
    await asyncio.sleep(0.3)

    await redis_client.publish(
        "rl:sync:counter",
        _counter_payload(tier="free", user_id="u_1", window_id=10, region="eu", value=5),
    )
    await asyncio.sleep(0.5)

    slots = await counter.get_global("free", "u_1", 10)
    assert slots == {}  # partition dropped
    task.cancel()


@pytest.mark.asyncio
async def test_relay_applies_reconcile_envelope(redis_client):
    counter = RegionalCounter("us", redis_client)
    transport = Transport(
        region="us", local_redis=redis_client,
        peer_redises={}, channel="rl:sync:counter",
    )
    relay = Relay("us", counter, transport, PartitionTable(), FailoverBuffer(100))
    task = asyncio.create_task(relay.run())
    await asyncio.sleep(0.3)

    payload = json.dumps({
        "kind": "reconcile",
        "v": 1,
        "origin": "eu",
        "window_id": 10,
        "ts_ms": 1,
        "slots": {"free:u_1": 7, "free:u_2": 99},
    }).encode()
    await redis_client.publish("rl:sync:counter", payload)
    await asyncio.sleep(0.5)

    assert await counter.get_global("free", "u_1", 10) == {"eu": 7}
    assert await counter.get_global("free", "u_2", 10) == {"eu": 99}
    task.cancel()
