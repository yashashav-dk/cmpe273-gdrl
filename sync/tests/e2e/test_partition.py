"""
sync/tests/e2e/test_partition.py — Layer 3 e2e: 3-region cluster, asymmetric
partition us→eu, divergent traffic, heal, drift collapse < 5s.
"""
import asyncio
import time
import pytest
import pytest_asyncio
from redis.asyncio import Redis
from testcontainers.redis import RedisContainer
from sync.counter import RegionalCounter
from sync.transport import Transport
from sync.partition_table import PartitionTable
from sync.buffer import FailoverBuffer
from sync.relay import Relay
from sync.reconciler import Reconciler
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
        yield dict(zip(regions, clients))
        for cl in clients:
            await cl.aclose()
    finally:
        for c in containers:
            c.stop()


@pytest.mark.asyncio
async def test_partition_drops_traffic_then_heal_converges(cluster):
    counters: dict[str, RegionalCounter] = {}
    tables: dict[str, PartitionTable] = {}
    tasks: list[asyncio.Task] = []
    for region in ("us", "eu", "asia"):
        counters[region] = RegionalCounter(region, cluster[region])
        tables[region] = PartitionTable()
        peers = {r: cluster[r] for r in ("us", "eu", "asia") if r != region}
        transport = Transport(region, cluster[region], peers, "rl:sync:counter")
        relay = Relay(region, counters[region], transport, tables[region], FailoverBuffer(10_000, region))
        rec = Reconciler(region, counters[region], transport, period_s=2, chunk_size=1000)
        tasks.append(asyncio.create_task(relay.run()))
        tasks.append(asyncio.create_task(rec.run()))

    await asyncio.sleep(0.5)

    tables["eu"].add("us", "eu")

    window = int(time.time() // 60)
    stub_us = GatewayStub("us", cluster["us"])
    for _ in range(20):
        await stub_us.allow_request("free", "u_p", window)
    await asyncio.sleep(0.5)

    eu_view_partitioned = await counters["eu"].get_global("free", "u_p", window)
    asia_view = await counters["asia"].get_global("free", "u_p", window)
    assert "us" not in eu_view_partitioned
    assert asia_view.get("us") == 20

    tables["eu"].remove("us", "eu")

    converged = False
    for _ in range(50):
        await asyncio.sleep(0.1)
        eu_view = await counters["eu"].get_global("free", "u_p", window)
        if eu_view.get("us") == 20:
            converged = True
            break
    assert converged, "drift did not collapse within 5s after heal"

    for t in tasks:
        t.cancel()
