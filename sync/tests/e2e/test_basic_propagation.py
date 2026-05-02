"""
sync/tests/e2e/test_basic_propagation.py — Layer 3 end-to-end: gateway-stub on
3 region Redises + 3 Relay instances. Verifies that a stub-emitted counter
envelope on one region propagates and merges into the other two within 2s.
"""
import asyncio
import pytest
import pytest_asyncio
from redis.asyncio import Redis
from testcontainers.redis import RedisContainer
from sync.counter import RegionalCounter
from sync.transport import Transport
from sync.partition_table import PartitionTable
from sync.buffer import FailoverBuffer
from sync.relay import Relay
from sync.dev.gateway_stub import GatewayStub


@pytest_asyncio.fixture
async def cluster():
    containers = [RedisContainer("redis:7-alpine") for _ in range(3)]
    for c in containers:
        c.start()
    clients: list[Redis] = []
    try:
        for c in containers:
            clients.append(Redis(
                host=c.get_container_host_ip(),
                port=int(c.get_exposed_port(6379)),
                decode_responses=False,
            ))
        regions = ["us", "eu", "asia"]
        by_region = dict(zip(regions, clients))
        yield by_region
        for cl in clients:
            await cl.aclose()
    finally:
        for c in containers:
            c.stop()


@pytest.mark.asyncio
async def test_gateway_publish_propagates_to_all_regions(cluster):
    counters: dict[str, RegionalCounter] = {}
    relays_tasks: list[asyncio.Task] = []
    for region in ("us", "eu", "asia"):
        counters[region] = RegionalCounter(region, cluster[region])
        peers = {r: cluster[r] for r in ("us", "eu", "asia") if r != region}
        transport = Transport(region, cluster[region], peers, "rl:sync:counter")
        relay = Relay(region, counters[region], transport, PartitionTable(), FailoverBuffer(1000))
        relays_tasks.append(asyncio.create_task(relay.run()))

    await asyncio.sleep(0.5)  # let subscribers settle

    stub = GatewayStub("us", cluster["us"])
    await stub.allow_request(tier="free", user_id="u_1", window_id=42)
    await stub.allow_request(tier="free", user_id="u_1", window_id=42)

    await asyncio.sleep(2.0)

    # us slot is gateway-side; eu + asia must have learned it via relay max-merge.
    eu_view = await counters["eu"].get_global("free", "u_1", 42)
    asia_view = await counters["asia"].get_global("free", "u_1", 42)
    assert eu_view == {"us": 2}
    assert asia_view == {"us": 2}

    for t in relays_tasks:
        t.cancel()
