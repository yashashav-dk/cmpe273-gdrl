"""gdrl traffic simulator CLI.

Day 2: print mode — requests are printed as JSON lines to stdout.
Day 3: replace _print_request with a real httpx send.

Usage:
    python -m simulator steady --rps 100 --duration 60
    python -m simulator spike --base 100 --peak 1000 --at 30
    python -m simulator noisy --culprit free_00001 --share 0.9
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass

import click

from simulator.populations import User, load
from simulator.runner import Stats, run_at_rate

REGIONS = ["us", "eu", "asia"]

ENDPOINTS = [
    "/api/v1/search",
    "/api/v1/feed",
    "/api/v1/profile",
    "/api/v1/upload",
    "/api/v1/checkout",
]

# Tier sampling weights for mixed-population patterns.
# Reflects realistic traffic: free dominates by volume, internal is rare.
_TIER_WEIGHTS = {"free": 0.7, "premium": 0.2, "internal": 0.1}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_request(user: User, region: str) -> dict:
    return {
        "user_id": user.user_id,
        "tier": user.tier,
        "region": region,
        "endpoint": random.choice(ENDPOINTS),
    }


async def _print_request(req: dict) -> None:
    """Day 2 send function — prints JSON to stdout. Swap for httpx on Day 3."""
    print(json.dumps(req), flush=True)


def _pick_user(pops: dict[str, list[User]]) -> User:
    tier = random.choices(
        list(_TIER_WEIGHTS.keys()), weights=list(_TIER_WEIGHTS.values()), k=1
    )[0]
    return random.choice(pops[tier])


def _pick_region(target: str) -> str:
    return random.choice(REGIONS) if target == "all" else target


def _summarize(label: str, stats: Stats, elapsed: float) -> None:
    actual_rps = stats.sent / elapsed if elapsed > 0 else 0
    click.echo(
        f"[{label}] sent={stats.sent} errors={stats.errors} "
        f"actual_rps={actual_rps:.1f}",
        err=True,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.group()
def cli() -> None:
    """gdrl traffic simulator."""


@cli.command()
@click.option("--rps", default=100.0, show_default=True, help="Requests per second.")
@click.option("--duration", default=60.0, show_default=True, help="Duration in seconds.")
@click.option(
    "--target-region",
    default="us",
    show_default=True,
    type=click.Choice(["us", "eu", "asia", "all"]),
    help="Region to target. 'all' picks randomly across all three.",
)
def steady(rps: float, duration: float, target_region: str) -> None:
    """Steady baseline traffic from a realistic mix of all three user tiers."""
    pops = load()

    async def _req() -> None:
        user = _pick_user(pops)
        region = _pick_region(target_region)
        await _print_request(_make_request(user, region))

    click.echo(
        f"steady  rps={rps} duration={duration}s target={target_region}", err=True
    )
    t0 = time.monotonic()
    stats = asyncio.run(run_at_rate(_req, rps, duration))
    _summarize("steady", stats, time.monotonic() - t0)


@cli.command()
@click.option("--base", default=100.0, show_default=True, help="Baseline RPS.")
@click.option("--peak", default=1000.0, show_default=True, help="Peak RPS during spike.")
@click.option(
    "--at",
    "spike_at",
    default=30.0,
    show_default=True,
    help="Seconds of baseline before spike begins.",
)
@click.option(
    "--spike-duration",
    default=30.0,
    show_default=True,
    help="How long the spike lasts in seconds.",
)
@click.option("--duration", default=120.0, show_default=True, help="Total run duration in seconds.")
@click.option(
    "--target-region",
    default="us",
    show_default=True,
    type=click.Choice(["us", "eu", "asia"]),
    help="Region to target.",
)
def spike(
    base: float,
    peak: float,
    spike_at: float,
    spike_duration: float,
    duration: float,
    target_region: str,
) -> None:
    """Spike pattern: steady base → sudden burst → recovery. Simulates a product launch."""
    pops = load()

    async def _req() -> None:
        user = _pick_user(pops)
        await _print_request(_make_request(user, target_region))

    click.echo(
        f"spike  base={base} peak={peak} at={spike_at}s "
        f"spike_duration={spike_duration}s total={duration}s target={target_region}",
        err=True,
    )

    async def _run() -> Stats:
        t0 = time.monotonic()
        s1 = await run_at_rate(_req, base, spike_at)
        _summarize("pre-spike", s1, time.monotonic() - t0)

        burst = min(spike_duration, max(0.0, duration - spike_at))
        t1 = time.monotonic()
        s2 = await run_at_rate(_req, peak, burst, concurrency=200)
        _summarize("spike", s2, time.monotonic() - t1)

        remaining = duration - spike_at - burst
        if remaining > 0:
            t2 = time.monotonic()
            s3 = await run_at_rate(_req, base, remaining)
            _summarize("recovery", s3, time.monotonic() - t2)
            return Stats(
                s1.sent + s2.sent + s3.sent,
                s1.errors + s2.errors + s3.errors,
            )
        return Stats(s1.sent + s2.sent, s1.errors + s2.errors)

    t0 = time.monotonic()
    stats = asyncio.run(_run())
    _summarize("total", stats, time.monotonic() - t0)


@cli.command()
@click.option("--culprit", default="free_00001", show_default=True, help="user_id of the noisy neighbor.")
@click.option(
    "--share",
    default=0.9,
    show_default=True,
    type=click.FloatRange(0.0, 1.0),
    help="Fraction of traffic sent by the culprit.",
)
@click.option("--rps", default=100.0, show_default=True, help="Requests per second.")
@click.option("--duration", default=60.0, show_default=True, help="Duration in seconds.")
@click.option(
    "--target-region",
    default="us",
    show_default=True,
    type=click.Choice(["us", "eu", "asia", "all"]),
)
def noisy(
    culprit: str,
    share: float,
    rps: float,
    duration: float,
    target_region: str,
) -> None:
    """Noisy neighbor: one user_id drives the majority of a tier's traffic."""
    pops = load()
    all_users = pops["free"] + pops["premium"] + pops["internal"]

    culprit_user = next((u for u in all_users if u.user_id == culprit), None)
    if culprit_user is None:
        click.echo(
            f"Warning: culprit '{culprit}' not found — defaulting to free_00001",
            err=True,
        )
        culprit_user = pops["free"][0]

    async def _req() -> None:
        user = culprit_user if random.random() < share else random.choice(all_users)
        region = _pick_region(target_region)
        await _print_request(_make_request(user, region))

    click.echo(
        f"noisy  culprit={culprit_user.user_id} share={share:.0%} "
        f"rps={rps} duration={duration}s target={target_region}",
        err=True,
    )
    t0 = time.monotonic()
    stats = asyncio.run(run_at_rate(_req, rps, duration))
    _summarize("noisy", stats, time.monotonic() - t0)
