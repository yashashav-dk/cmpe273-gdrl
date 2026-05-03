"""
sync/tests/integration/test_admin.py — Layer 2 integration tests for the admin
HTTP surface. Uses httpx.AsyncClient with ASGITransport against a real Redis
so the test, the redis client, and the FastAPI app all share the same event
loop (FastAPI's TestClient spins up its own portal loop, which collides with
the redis_client fixture's pytest-asyncio loop binding).
"""
import pytest
import httpx
from sync.counter import RegionalCounter
from sync.partition_table import PartitionTable
from sync.buffer import FailoverBuffer
from sync.admin import build_app


def _make_app(redis_client):
    counter = RegionalCounter("us", redis_client)
    table = PartitionTable()
    buffer = FailoverBuffer(1000, region="us")
    return build_app(region="us", counter=counter, partition_table=table,
                     buffer=buffer, set_reconcile_period=lambda s: None), table


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.mark.asyncio
async def test_health_returns_200_when_redis_up(redis_client):
    app, _ = _make_app(redis_client)
    async with _client(app) as client:
        r = await client.get("/health")
        assert r.status_code == 200
        assert r.json()["redis_up"] is True


@pytest.mark.asyncio
async def test_admin_state_returns_drift_and_counts(redis_client):
    await redis_client.hset("rl:global:free:u_1:42", mapping={"us": 5, "eu": 3, "asia": 1})
    app, _ = _make_app(redis_client)
    async with _client(app) as client:
        r = await client.get("/admin/state", params={"user_id": "u_1", "tier": "free", "window_id": 42})
        assert r.status_code == 200
        body = r.json()
        assert body["slots"] == {"us": 5, "eu": 3, "asia": 1}
        assert body["drift"] == 4  # max - min


@pytest.mark.asyncio
async def test_admin_partition_and_heal_flip_table(redis_client):
    app, table = _make_app(redis_client)
    async with _client(app) as client:
        r = await client.post("/admin/partition", json={"from": "us", "to": "eu"})
        assert r.status_code == 200
        assert table.blocks("us", "eu") is True

        r = await client.post("/admin/heal", json={"from": "us", "to": "eu"})
        assert r.status_code == 200
        assert table.blocks("us", "eu") is False


@pytest.mark.asyncio
async def test_admin_config_calls_setter(redis_client):
    captured: list[int] = []
    counter = RegionalCounter("us", redis_client)
    app = build_app(
        region="us",
        counter=counter,
        partition_table=PartitionTable(),
        buffer=FailoverBuffer(1000, region="us"),
        set_reconcile_period=lambda s: captured.append(s),
    )
    async with _client(app) as client:
        r = await client.post("/admin/config", json={"reconcile_period_s": 60})
        assert r.status_code == 200
        assert captured == [60]


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_prometheus_text(redis_client):
    app, _ = _make_app(redis_client)
    async with _client(app) as client:
        r = await client.get("/metrics")
        assert r.status_code == 200
        body = r.text
        assert "rl_sync_lag_seconds" in body
        assert "rl_reconcile_period_s" in body
