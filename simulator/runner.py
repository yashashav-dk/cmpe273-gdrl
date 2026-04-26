"""Async rate-controlled request loop.

Drives a caller-supplied coroutine at a fixed RPS using a semaphore to cap
concurrency. The send function is injected by the CLI so Day 3 can swap
print_request for a real httpx call without touching this module.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

RequestFn = Callable[[], Awaitable[None]]


@dataclass
class Stats:
    sent: int = 0
    errors: int = 0


async def run_at_rate(
    request_fn: RequestFn,
    rps: float,
    duration: float,
    concurrency: int = 50,
) -> Stats:
    """Drive request_fn at `rps` req/s for `duration` seconds.

    Uses a token-interval loop: one task is created every 1/rps seconds.
    The semaphore caps how many run concurrently so slow responses don't
    pile up unboundedly.
    """
    stats = Stats()
    sem = asyncio.Semaphore(concurrency)
    interval = 1.0 / rps
    end_time = time.monotonic() + duration
    tasks: list[asyncio.Task] = []

    async def _bounded() -> None:
        async with sem:
            try:
                await request_fn()
                stats.sent += 1
            except Exception:
                stats.errors += 1

    next_tick = time.monotonic()
    while time.monotonic() < end_time:
        tasks.append(asyncio.create_task(_bounded()))
        next_tick += interval
        sleep_for = next_tick - time.monotonic()
        if sleep_for > 0:
            await asyncio.sleep(sleep_for)

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    return stats
