"""Shared pytest fixtures for sync tests."""
import asyncio
import pytest
import pytest_asyncio
from testcontainers.redis import RedisContainer
from redis.asyncio import Redis


@pytest_asyncio.fixture
async def redis_container():
    with RedisContainer("redis:7-alpine") as ctr:
        yield ctr


@pytest_asyncio.fixture
async def redis_client(redis_container):
    host = redis_container.get_container_host_ip()
    port = int(redis_container.get_exposed_port(6379))
    client = Redis(host=host, port=port, decode_responses=False)
    try:
        yield client
    finally:
        await client.flushall()
        await client.aclose()
