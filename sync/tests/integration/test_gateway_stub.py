"""
sync/tests/integration/test_gateway_stub.py — Layer 2 integration test for the
solo-demo gateway harness. Verifies the stub emits Contract-2 envelopes that
parse successfully and that gateway-side HIncrBy populates rl:global slots.
"""
import asyncio
import pytest
from sync.envelope import parse, CounterEnvelope
from sync.dev.gateway_stub import GatewayStub


@pytest.mark.asyncio
async def test_stub_publishes_contract2_envelope_and_writes_global(redis_client):
    stub = GatewayStub(region="us", redis=redis_client)
    received: list[bytes] = []

    pubsub = redis_client.pubsub()
    await pubsub.subscribe("rl:sync:counter")

    async def consume():
        async for msg in pubsub.listen():
            if msg.get("type") == "message":
                received.append(msg["data"])
                break

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.3)

    await stub.allow_request(tier="free", user_id="u_1", window_id=42)
    await asyncio.wait_for(consumer, timeout=5.0)

    env = parse(received[0])
    assert isinstance(env, CounterEnvelope)
    assert env.tier == "free"
    assert env.user_id == "u_1"
    assert env.window_id == 42
    assert env.region == "us"
    assert env.value == 1
    assert env.ts_ms > 0

    own_slot = await redis_client.hget("rl:global:free:u_1:42", "us")
    assert int(own_slot) == 1

    await pubsub.aclose()
