"""
sync/tests/integration/test_transport_pubsub.py — Layer 2 integration tests
for the pub/sub transport.

Spec: docs/superpowers/specs/2026-04-25-sync-service-design.md §5.transport.py
"""
import asyncio
import pytest
import pytest_asyncio
from redis.asyncio import Redis
from testcontainers.redis import RedisContainer
from sync.transport import Transport


@pytest_asyncio.fixture
async def three_redis_clients():
    containers = [RedisContainer("redis:7-alpine") for _ in range(3)]
    for c in containers:
        c.start()
    try:
        clients = [
            Redis(
                host=c.get_container_host_ip(),
                port=int(c.get_exposed_port(6379)),
                decode_responses=False,
            )
            for c in containers
        ]
        yield clients
        for c in clients:
            await c.aclose()
    finally:
        for c in containers:
            c.stop()


@pytest.mark.asyncio
async def test_subscribe_peers_yields_origin_and_raw(three_redis_clients):
    local, peer1, peer2 = three_redis_clients
    transport = Transport(
        region="us",
        local_redis=local,
        peer_redises={"eu": peer1, "asia": peer2},
        channel="rl:sync:counter",
    )
    received: list[tuple[str, bytes]] = []

    async def consume():
        async for origin, raw in transport.subscribe_peers():
            received.append((origin, raw))
            if len(received) == 2:
                break

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.3)
    await peer1.publish("rl:sync:counter", b"hello-eu")
    await peer2.publish("rl:sync:counter", b"hello-asia")
    await asyncio.wait_for(consumer, timeout=5.0)

    received.sort()
    assert received == [("asia", b"hello-asia"), ("eu", b"hello-eu")]


@pytest.mark.asyncio
async def test_publish_local_round_trips_through_subscribe(three_redis_clients):
    local, peer1, peer2 = three_redis_clients
    transport = Transport(
        region="us",
        local_redis=local,
        peer_redises={"eu": peer1, "asia": peer2},
        channel="rl:sync:counter",
    )
    received: list[tuple[str, bytes]] = []

    async def consume():
        async for origin, raw in transport.subscribe_peers():
            received.append((origin, raw))
            if received:
                break

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.3)
    await transport.publish_local(b"reconcile-payload")
    await asyncio.wait_for(consumer, timeout=5.0)

    assert received == [("us", b"reconcile-payload")]


@pytest.mark.asyncio
async def test_subscribe_peers_recovers_after_disconnect(three_redis_clients):
    local, peer1, peer2 = three_redis_clients
    transport = Transport(
        region="us",
        local_redis=local,
        peer_redises={"eu": peer1, "asia": peer2},
        channel="rl:sync:counter",
    )
    received: list[tuple[str, bytes]] = []

    async def consume():
        async for origin, raw in transport.subscribe_peers():
            received.append((origin, raw))
            if len(received) == 2:
                break

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.3)
    await peer1.publish("rl:sync:counter", b"first")
    await asyncio.sleep(0.3)

    # Simulate transient peer reconnect by closing peer1's existing connections.
    await peer1.execute_command("CLIENT", "KILL", "TYPE", "pubsub")
    await asyncio.sleep(0.5)

    await peer1.publish("rl:sync:counter", b"second")
    await asyncio.wait_for(consumer, timeout=10.0)

    payloads = sorted(raw for _, raw in received)
    assert payloads == [b"first", b"second"]
