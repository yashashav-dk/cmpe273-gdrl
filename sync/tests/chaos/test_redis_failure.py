"""
sync/tests/chaos/test_redis_failure.py — Layer 4 chaos: kill local Redis under
load, verify buffer fills.
"""
import asyncio
import pytest
from redis.asyncio import Redis
from testcontainers.redis import RedisContainer
from sync.counter import RegionalCounter
from sync.transport import Transport
from sync.partition_table import PartitionTable
from sync.buffer import FailoverBuffer
from sync.relay import Relay


@pytest.mark.asyncio
async def test_buffer_fills_when_local_redis_fails():
    container_local = RedisContainer("redis:7-alpine").start()
    container_peer = RedisContainer("redis:7-alpine").start()
    try:
        local = Redis(
            host=container_local.get_container_host_ip(),
            port=int(container_local.get_exposed_port(6379)),
            decode_responses=False,
            socket_connect_timeout=1.0,
        )
        peer = Redis(
            host=container_peer.get_container_host_ip(),
            port=int(container_peer.get_exposed_port(6379)),
            decode_responses=False,
        )

        counter = RegionalCounter("us", local)
        transport = Transport("us", local, {"eu": peer}, "rl:sync:counter")
        buffer = FailoverBuffer(1_000, region="us")
        relay = Relay("us", counter, transport, PartitionTable(), buffer)
        task = asyncio.create_task(relay.run())
        await asyncio.sleep(0.3)

        # Kill local Redis to force apply_remote_slot failures.
        container_local.stop()

        # Push 10 envelopes from peer; relay buffers them.
        for i in range(10):
            await peer.publish(
                "rl:sync:counter",
                f'{{"tier":"free","user_id":"u_{i}","window_id":1,"region":"eu","value":1,"ts_ms":1}}'.encode(),
            )
        await asyncio.sleep(3.0)
        assert buffer.size("relay_apply") > 0

        task.cancel()
        await peer.aclose()
        try:
            await local.aclose()
        except Exception:
            pass
    finally:
        try:
            container_local.stop()
        except Exception:
            pass
        container_peer.stop()
