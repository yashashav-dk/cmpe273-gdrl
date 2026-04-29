"""Async rate-controlled request loop.

Drives a caller-supplied coroutine at a target RPS using a semaphore to cap
concurrency. Supports two scheduling modes:

  Poisson (default) — inter-arrival times drawn from Exp(rps), producing a
    realistic Poisson arrival process with natural burstiness.
  Fixed             — deterministic 1/rps interval with drift correction
    (original behaviour; useful for reproducible benchmarks).

run_with_diurnal wraps run_at_rate with a sinusoidal RPS envelope so a
single steady run can simulate 24-hour traffic patterns at any time scale.
"""
from __future__ import annotations

import asyncio
import math
import random
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
    poisson: bool = True,
) -> Stats:
    """Drive request_fn at `rps` req/s for `duration` seconds.

    With poisson=True (default) inter-arrival times are drawn from
    Exp(rps), matching real-world Poisson arrival processes.
    With poisson=False a fixed 1/rps interval with drift correction is
    used — deterministic and good for reproducible load tests.
    """
    stats = Stats()
    sem = asyncio.Semaphore(concurrency)
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
        # Poisson process: inter-arrivals ~ Exp(λ=rps), mean = 1/rps
        next_tick += random.expovariate(rps) if poisson else (1.0 / rps)
        sleep_for = next_tick - time.monotonic()
        if sleep_for > 0:
            await asyncio.sleep(sleep_for)

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    return stats


async def run_with_diurnal(
    request_fn: RequestFn,
    base_rps: float,
    duration: float,
    period: float = 86400.0,
    amplitude: float = 0.7,
    concurrency: int = 50,
) -> Stats:
    """Drive request_fn with a sinusoidally-varying RPS for `duration` seconds.

    RPS(t) = base_rps * max(0.1, 1 + amplitude * sin(2π·t/period − π/2))

    The phase offset −π/2 starts the wave at its trough (simulating 3 AM)
    and peaks at period/4 (simulating noon). With amplitude=0.7 the rate
    swings from 30% to 170% of base_rps.

    For a compressed demo set period=120 to complete a full cycle in 2 min.
    """
    segment = 5.0  # seconds between RPS recalculations
    start = time.monotonic()
    end = start + duration
    total = Stats()

    while True:
        now = time.monotonic()
        if now >= end:
            break
        elapsed = now - start
        multiplier = max(0.1, 1.0 + amplitude * math.sin(2 * math.pi * elapsed / period - math.pi / 2))
        effective_rps = base_rps * multiplier
        seg_dur = min(segment, end - now)
        s = await run_at_rate(request_fn, effective_rps, seg_dur, concurrency)
        total.sent += s.sent
        total.errors += s.errors

    return total
