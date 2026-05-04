"""
sync/tests/chaos/test_convergence.py — Layer 4 chaos: THE PROOF.

PDF Day 8 requirement. Cluster + brief baseline + ~6s partition with divergent
load + heal → assert convergence < 5s. Writes timestamped result file for the
writeup and Constitution Art V §2. The CI/local run uses a 6s partition for
speed; the pre-demo run uses 60s by setting CONVERGENCE_PARTITION_S=60.
"""
import asyncio
import datetime
import os
import pathlib
import pytest
import pytest_asyncio
import time
from redis.asyncio import Redis
from testcontainers.redis import RedisContainer
from sync.counter import RegionalCounter
from sync.transport import Transport
from sync.partition_table import PartitionTable
from sync.buffer import FailoverBuffer
from sync.relay import Relay
from sync.reconciler import Reconciler
from sync.dev.gateway_stub import GatewayStub

RESULTS_DIR = pathlib.Path(__file__).parent / "results"
CONVERGENCE_TARGET_S = 5.0
PARTITION_S = float(os.environ.get("CONVERGENCE_PARTITION_S", "6"))


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
async def test_convergence_after_partition_under_5s(cluster):
    counters: dict[str, RegionalCounter] = {}
    tables: dict[str, PartitionTable] = {}
    tasks: list[asyncio.Task] = []
    for region in ("us", "eu", "asia"):
        counters[region] = RegionalCounter(region, cluster[region])
        tables[region] = PartitionTable()
        peers = {r: cluster[r] for r in ("us", "eu", "asia") if r != region}
        transport = Transport(region, cluster[region], peers, "rl:sync:counter")
        relay = Relay(region, counters[region], transport, tables[region], FailoverBuffer(50_000, region))
        rec = Reconciler(region, counters[region], transport, period_s=2, chunk_size=1000)
        tasks.append(asyncio.create_task(relay.run()))
        tasks.append(asyncio.create_task(rec.run()))

    await asyncio.sleep(0.5)

    stub_us = GatewayStub("us", cluster["us"])

    # Use current epoch-minute window so reconciler actually scans it.
    window = int(time.time() // 60)

    # Baseline traffic.
    for _ in range(10):
        await stub_us.allow_request("free", "u_X", window)
        await asyncio.sleep(0.05)

    # Partition us↛eu, divergent load.
    tables["eu"].add("us", "eu")
    partition_started = time.time()
    events_during_partition = 0
    while time.time() - partition_started < PARTITION_S:
        await stub_us.allow_request("free", "u_X", window)
        events_during_partition += 1
        await asyncio.sleep(0.01)

    eu_view_partitioned = await counters["eu"].get_global("free", "u_X", window)
    us_value_raw = await cluster["us"].hget(f"rl:global:free:u_X:{window}", "us")
    us_value = int(us_value_raw or 0)
    assert eu_view_partitioned.get("us", 0) < us_value, (
        f"partition not effective: eu={eu_view_partitioned} us={us_value}"
    )

    # Heal + measure.
    tables["eu"].remove("us", "eu")
    heal_started = time.time()
    converged_at = None
    deadline = heal_started + CONVERGENCE_TARGET_S * 2
    while time.time() < deadline:
        eu_view = await counters["eu"].get_global("free", "u_X", window)
        if eu_view.get("us") == us_value:
            converged_at = time.time()
            break
        await asyncio.sleep(0.05)

    convergence_s = (converged_at - heal_started) if converged_at else float("inf")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    artifact = RESULTS_DIR / f"convergence_{stamp}.txt"
    artifact.write_text(
        f"convergence_test\n"
        f"partition_window_s={PARTITION_S}\n"
        f"events_during_partition={events_during_partition}\n"
        f"us_final_value={us_value}\n"
        f"converged_in_s={convergence_s:.3f}\n"
        f"target_s={CONVERGENCE_TARGET_S}\n"
        f"passed={convergence_s < CONVERGENCE_TARGET_S}\n"
    )

    for t in tasks:
        t.cancel()

    assert convergence_s < CONVERGENCE_TARGET_S, (
        f"convergence took {convergence_s:.3f}s > {CONVERGENCE_TARGET_S}s target; see {artifact}"
    )
