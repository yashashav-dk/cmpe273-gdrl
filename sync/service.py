"""
sync/service.py — asyncio orchestrator + entrypoint.

Spec:        docs/superpowers/specs/2026-04-25-sync-service-design.md §5.service.py
Constitution: docs/sync-constitution.md Art II §5 (stateless processes)
Reads:       env vars REGION, LOCAL_REDIS_URL, PEER_REDIS_URLS
Writes:      starts asyncio tasks; stops them cleanly on signal
Don't:       hold persistent state across restart; share connections across regions.

Wires Transport, Counter, Buffer, PartitionTable, Relay, Reconciler, Admin into
one asyncio.gather. Signal-driven shutdown cancels all tasks and closes Redis
clients.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import click
import uvicorn
from redis.asyncio import Redis
from sync.counter import RegionalCounter
from sync.transport import Transport
from sync.partition_table import PartitionTable
from sync.buffer import FailoverBuffer
from sync.relay import Relay
from sync.reconciler import Reconciler
from sync.admin import build_app

CHANNEL = "rl:sync:counter"
ADMIN_PORT = 9100

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("sync")


async def amain(region: str, local_url: str, peer_urls: list[str], reconcile_period_s: int) -> None:
    local = Redis.from_url(local_url, decode_responses=False, health_check_interval=15,
                           socket_keepalive=True)
    peers = {}
    for url in peer_urls:
        peer_region = _infer_region_from_url(url, region)
        peers[peer_region] = Redis.from_url(url, decode_responses=False,
                                            health_check_interval=15, socket_keepalive=True)

    counter = RegionalCounter(region, local)
    partition_table = PartitionTable()
    buffer = FailoverBuffer(max_entries_per_kind=10_000, region=region)
    transport = Transport(region, local, peers, CHANNEL)
    relay = Relay(region, counter, transport, partition_table, buffer)
    reconciler = Reconciler(region, counter, transport, period_s=reconcile_period_s)

    app = build_app(
        region=region, counter=counter, partition_table=partition_table,
        buffer=buffer, set_reconcile_period=reconciler.set_period,
    )
    config = uvicorn.Config(app, host="0.0.0.0", port=ADMIN_PORT, log_level="info")
    server = uvicorn.Server(config)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    log.info("sync-%s booting; peers=%s; reconcile_period=%ds", region, list(peers), reconcile_period_s)
    relay_task = asyncio.create_task(relay.run(), name="relay")
    rec_task = asyncio.create_task(reconciler.run(), name="reconciler")
    server_task = asyncio.create_task(server.serve(), name="admin")

    await stop_event.wait()
    log.info("sync-%s stopping", region)
    server.should_exit = True
    for t in (relay_task, rec_task):
        t.cancel()
    await asyncio.gather(relay_task, rec_task, server_task, return_exceptions=True)
    await local.aclose()
    for c in peers.values():
        await c.aclose()


def _infer_region_from_url(url: str, self_region: str) -> str:
    for r in ("us", "eu", "asia"):
        if r != self_region and r in url:
            return r
    raise RuntimeError(f"cannot infer peer region from URL {url!r}")


@click.command()
@click.option("--region", default=lambda: os.environ.get("REGION"), required=True)
@click.option("--local-redis-url", default=lambda: os.environ.get("LOCAL_REDIS_URL"), required=True)
@click.option("--peer-redis-urls", default=lambda: os.environ.get("PEER_REDIS_URLS", ""))
@click.option("--reconcile-period-s", default=30, type=int)
def main_cli(region: str, local_redis_url: str, peer_redis_urls: str, reconcile_period_s: int) -> None:
    peers = [u.strip() for u in peer_redis_urls.split(",") if u.strip()]
    asyncio.run(amain(region, local_redis_url, peers, reconcile_period_s))
