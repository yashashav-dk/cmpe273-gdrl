"""gdrl traffic simulator CLI.

Day 3: real HTTP mode — requests are sent via httpx to the three regional
gateways. Each request's region field is always matched to the gateway it's
routed to (Contract 1 enforces this on the gateway side).

Usage:
    python -m simulator steady --rps 100 --duration 60 --target-region us
    python -m simulator steady --rps 100 --duration 60 --distribution us:0.5,eu:0.3,asia:0.2
    python -m simulator spike  --base 100 --peak 1000 --at 30 --target-region us
    python -m simulator noisy  --culprit free_00001 --share 0.9 --rps 100
"""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass

import click
import httpx

from simulator.populations import User, load
from simulator.runner import Stats, run_at_rate, run_with_diurnal

REGIONS = ["us", "eu", "asia"]

# Host ports for each gateway instance (matches docker-compose port bindings).
GATEWAY_PORTS = {"us": 8081, "eu": 8082, "asia": 8083}

ENDPOINTS = [
    "/api/v1/search",
    "/api/v1/feed",
    "/api/v1/profile",
    "/api/v1/upload",
    "/api/v1/checkout",
]

# Tier sampling weights for mixed-population patterns.
_TIER_WEIGHTS = {"free": 0.7, "premium": 0.2, "internal": 0.1}


# ── Per-run counters (asyncio is single-threaded; no locks needed) ────────────

@dataclass
class _Counters:
    allowed: int = 0
    denied: int = 0
    http_errors: int = 0


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_distribution(s: str) -> dict[str, float]:
    """Parse 'us:0.5,eu:0.3,asia:0.2' into {region: weight}."""
    result: dict[str, float] = {}
    for part in s.split(","):
        region, weight = part.strip().split(":")
        result[region.strip()] = float(weight)
    return result


def _gateway_url(region: str) -> str:
    return f"http://localhost:{GATEWAY_PORTS[region]}/check"


def _pick_target(
    target_region: str,
    distribution: dict[str, float] | None,
) -> tuple[str, str]:
    """Return (region, gateway_url) for one request.

    Distribution takes precedence over target_region when both are provided.
    'all' in target_region picks uniformly across all three regions.
    The returned region is always consistent with the returned URL so the
    gateway's region-validation check passes.
    """
    if distribution:
        region = random.choices(
            list(distribution.keys()), weights=list(distribution.values()), k=1
        )[0]
    elif target_region == "all":
        region = random.choice(REGIONS)
    else:
        region = target_region
    return region, _gateway_url(region)


def _make_request(user: User, region: str) -> dict:
    return {
        "user_id": user.user_id,
        "tier": user.tier,
        "region": region,
        "endpoint": random.choice(ENDPOINTS),
    }


def _pick_user(pops: dict[str, list[User]]) -> User:
    tier = random.choices(
        list(_TIER_WEIGHTS.keys()), weights=list(_TIER_WEIGHTS.values()), k=1
    )[0]
    return random.choice(pops[tier])


async def _send(
    client: httpx.AsyncClient,
    url: str,
    req: dict,
    counters: _Counters,
) -> None:
    """Send one request to the gateway and record the outcome.

    Non-200 HTTP responses and network errors propagate as exceptions so the
    runner's stats.errors counter captures them.
    """
    resp = await client.post(url, json=req, timeout=5.0)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:80]}")
    data = resp.json()
    if data.get("allowed"):
        counters.allowed += 1
    else:
        counters.denied += 1


def _summarize(
    label: str,
    stats: Stats,
    elapsed: float,
    counters: _Counters | None = None,
) -> None:
    actual_rps = stats.sent / elapsed if elapsed > 0 else 0
    msg = (
        f"[{label}] sent={stats.sent} errors={stats.errors} "
        f"actual_rps={actual_rps:.1f}"
    )
    if counters is not None:
        allow_pct = counters.allowed / max(stats.sent, 1) * 100
        msg += (
            f"  |  allowed={counters.allowed} denied={counters.denied} "
            f"http_err={counters.http_errors} ({allow_pct:.0f}% pass)"
        )
    click.echo(msg, err=True)


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.group()
def cli() -> None:
    """gdrl traffic simulator."""


_distribution_option = click.option(
    "--distribution",
    default=None,
    metavar="DIST",
    help="Weighted region distribution, e.g. us:0.5,eu:0.3,asia:0.2. "
         "Overrides --target-region when provided.",
)


@cli.command()
@click.option("--rps", default=100.0, show_default=True, help="Requests per second.")
@click.option("--duration", default=60.0, show_default=True, help="Duration in seconds.")
@click.option(
    "--target-region",
    default="us",
    show_default=True,
    type=click.Choice(["us", "eu", "asia", "all"]),
    help="Region to target. 'all' picks uniformly across all three.",
)
@_distribution_option
@click.option(
    "--diurnal/--no-diurnal",
    default=False,
    show_default=True,
    help="Apply a sine-wave diurnal envelope to RPS (30%–170% of base).",
)
@click.option(
    "--diurnal-period",
    default=86400.0,
    show_default=True,
    metavar="SECONDS",
    help="Diurnal cycle length in seconds. Use 120 for a compressed 2-min demo cycle.",
)
def steady(
    rps: float,
    duration: float,
    target_region: str,
    distribution: str | None,
    diurnal: bool,
    diurnal_period: float,
) -> None:
    """Steady baseline traffic from a realistic mix of all three user tiers.

    Inter-arrival times follow a Poisson process (Exp(rps)) for realistic
    burstiness. Pass --diurnal to add a sinusoidal 24-hour RPS envelope;
    use --diurnal-period 120 for a compressed 2-minute demo cycle.
    """
    pops = load()
    dist = parse_distribution(distribution) if distribution else None
    counters = _Counters()

    async def _run() -> Stats:
        async with httpx.AsyncClient() as client:
            async def _req() -> None:
                user = _pick_user(pops)
                region, url = _pick_target(target_region, dist)
                await _send(client, url, _make_request(user, region), counters)
            if diurnal:
                return await run_with_diurnal(_req, rps, duration, period=diurnal_period)
            return await run_at_rate(_req, rps, duration)

    suffix = f"  diurnal=on period={diurnal_period}s" if diurnal else ""
    click.echo(
        f"steady  rps={rps} duration={duration}s "
        f"target={distribution or target_region}{suffix}",
        err=True,
    )
    t0 = time.monotonic()
    stats = asyncio.run(_run())
    _summarize("steady", stats, time.monotonic() - t0, counters)


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
@click.option("--spike-duration", default=30.0, show_default=True, help="Duration of spike in seconds.")
@click.option("--duration", default=120.0, show_default=True, help="Total run duration in seconds.")
@click.option(
    "--target-region",
    default="us",
    show_default=True,
    type=click.Choice(["us", "eu", "asia"]),
    help="Region to spike.",
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
    counters = _Counters()

    async def _run() -> Stats:
        async with httpx.AsyncClient() as client:
            async def _req() -> None:
                user = _pick_user(pops)
                _, url = _pick_target(target_region, None)
                await _send(client, url, _make_request(user, target_region), counters)

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

    click.echo(
        f"spike  base={base} peak={peak} at={spike_at}s "
        f"spike_duration={spike_duration}s total={duration}s target={target_region}",
        err=True,
    )
    t0 = time.monotonic()
    stats = asyncio.run(_run())
    _summarize("total", stats, time.monotonic() - t0, counters)


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
@_distribution_option
def noisy(
    culprit: str,
    share: float,
    rps: float,
    duration: float,
    target_region: str,
    distribution: str | None,
) -> None:
    """Noisy neighbor: one user_id drives the majority of a tier's traffic."""
    pops = load()
    dist = parse_distribution(distribution) if distribution else None
    all_users = pops["free"] + pops["premium"] + pops["internal"]

    culprit_user = next((u for u in all_users if u.user_id == culprit), None)
    if culprit_user is None:
        click.echo(
            f"Warning: culprit '{culprit}' not found — defaulting to free_00001",
            err=True,
        )
        culprit_user = pops["free"][0]

    counters = _Counters()

    async def _run() -> Stats:
        async with httpx.AsyncClient() as client:
            async def _req() -> None:
                user = culprit_user if random.random() < share else random.choice(all_users)
                region, url = _pick_target(target_region, dist)
                await _send(client, url, _make_request(user, region), counters)
            return await run_at_rate(_req, rps, duration)

    click.echo(
        f"noisy  culprit={culprit_user.user_id} share={share:.0%} "
        f"rps={rps} duration={duration}s target={distribution or target_region}",
        err=True,
    )
    t0 = time.monotonic()
    stats = asyncio.run(_run())
    _summarize("noisy", stats, time.monotonic() - t0, counters)
