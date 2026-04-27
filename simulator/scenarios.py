"""Named demo scenarios for gdrl.

Each scenario is a single function that runs end-to-end using the existing
CLI commands programmatically. Run via:

    python -m simulator.scenarios <scenario_name>

or import and call directly in tests.

Scenarios
---------
global_steady     Balanced load across all three regions — baseline metrics.
product_launch    10x spike on US for 2 min, then back to baseline.
noisy_neighbor    One free user sends 50% of a tier's traffic.
region_failover   Kill US gateway mid-run; traffic redistributes to EU/Asia.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from dataclasses import dataclass

import click
import httpx

from simulator.cli import (
    GATEWAY_PORTS,
    REGIONS,
    _Counters,
    _make_request,
    _pick_user,
    _send,
    _summarize,
    parse_distribution,
)
from simulator.populations import load
from simulator.runner import Stats, run_at_rate


# ── Scenario helpers ──────────────────────────────────────────────────────────

def _url(region: str) -> str:
    return f"http://localhost:{GATEWAY_PORTS[region]}/check"


def _gateway_container(region: str) -> str:
    return f"gateway-{region}"


async def _run_region(
    pops: dict,
    region: str,
    rps: float,
    duration: float,
    counters: _Counters,
    concurrency: int = 50,
) -> Stats:
    async with httpx.AsyncClient() as client:
        async def _req() -> None:
            user = _pick_user(pops)
            await _send(client, _url(region), _make_request(user, region), counters)
        return await run_at_rate(_req, rps, duration, concurrency)


async def _run_weighted(
    pops: dict,
    distribution: dict[str, float],
    rps: float,
    duration: float,
    counters: _Counters,
) -> Stats:
    """Send traffic weighted across multiple regions in one coroutine pool."""
    import random
    regions = list(distribution.keys())
    weights = list(distribution.values())

    async with httpx.AsyncClient() as client:
        async def _req() -> None:
            region = random.choices(regions, weights=weights, k=1)[0]
            user = _pick_user(pops)
            await _send(client, _url(region), _make_request(user, region), counters)
        return await run_at_rate(_req, rps, duration)


# ── Scenarios ─────────────────────────────────────────────────────────────────

def global_steady(rps: float = 300.0, duration: float = 300.0) -> None:
    """Balanced load across all three regions.

    Sends `rps` total req/s split evenly across US / EU / Asia (1:1:1).
    Intended as baseline — run this first to establish steady-state metrics
    before any spike or failover demo.

    Default: 300 req/s for 5 minutes (100 per region).
    """
    pops = load()
    dist = {"us": 1/3, "eu": 1/3, "asia": 1/3}
    counters = _Counters()

    click.echo(
        f"[global_steady] rps={rps} duration={duration}s  "
        f"distribution=us:eu:asia 1:1:1",
        err=True,
    )
    t0 = time.monotonic()
    stats = asyncio.run(_run_weighted(pops, dist, rps, duration, counters))
    _summarize("global_steady", stats, time.monotonic() - t0, counters)


def product_launch(
    base_rps: float = 100.0,
    peak_rps: float = 1000.0,
    warmup: float = 30.0,
    spike_duration: float = 120.0,
    cooldown: float = 60.0,
    region: str = "us",
) -> None:
    """10x traffic spike on one region simulating a product launch.

    Phases:
      1. Warmup  — base_rps for `warmup` seconds (establish baseline)
      2. Spike   — peak_rps for `spike_duration` seconds (launch burst)
      3. Cooldown — base_rps for `cooldown` seconds (watch recovery)

    Default: US region, 100 → 1000 → 100 RPS over ~3.5 minutes total.
    """
    pops = load()
    counters = _Counters()
    total = warmup + spike_duration + cooldown

    click.echo(
        f"[product_launch] region={region} base={base_rps} peak={peak_rps}  "
        f"warmup={warmup}s spike={spike_duration}s cooldown={cooldown}s  "
        f"total={total}s",
        err=True,
    )

    async def _run() -> Stats:
        async with httpx.AsyncClient() as client:
            async def _req() -> None:
                user = _pick_user(pops)
                await _send(client, _url(region), _make_request(user, region), counters)

            t0 = time.monotonic()
            s1 = await run_at_rate(_req, base_rps, warmup)
            _summarize("warmup", s1, time.monotonic() - t0)

            t1 = time.monotonic()
            s2 = await run_at_rate(_req, peak_rps, spike_duration, concurrency=200)
            _summarize("spike", s2, time.monotonic() - t1)

            t2 = time.monotonic()
            s3 = await run_at_rate(_req, base_rps, cooldown)
            _summarize("cooldown", s3, time.monotonic() - t2)

            return Stats(
                s1.sent + s2.sent + s3.sent,
                s1.errors + s2.errors + s3.errors,
            )

    t0 = time.monotonic()
    stats = asyncio.run(_run())
    _summarize("product_launch total", stats, time.monotonic() - t0, counters)


def noisy_neighbor(
    culprit_id: str = "free_00001",
    share: float = 0.5,
    rps: float = 200.0,
    duration: float = 120.0,
    region: str = "us",
) -> None:
    """One free user sends 50% of a tier's traffic.

    With share=0.5 and rps=200, the culprit sends ~100 req/s while the free
    tier limit is 10/min — they will be throttled almost immediately.
    Atharv's agent should detect the anomaly and write an override within
    30 seconds of this scenario starting.

    Default: culprit=free_00001, 50% share, 200 RPS for 2 minutes on US.
    """
    import random as _random

    pops = load()
    all_users = pops["free"] + pops["premium"] + pops["internal"]
    culprit = next((u for u in all_users if u.user_id == culprit_id), pops["free"][0])
    counters = _Counters()

    click.echo(
        f"[noisy_neighbor] culprit={culprit.user_id} share={share:.0%}  "
        f"rps={rps} duration={duration}s region={region}",
        err=True,
    )

    async def _run() -> Stats:
        async with httpx.AsyncClient() as client:
            async def _req() -> None:
                user = culprit if _random.random() < share else _random.choice(all_users)
                await _send(client, _url(region), _make_request(user, region), counters)
            return await run_at_rate(_req, rps, duration)

    t0 = time.monotonic()
    stats = asyncio.run(_run())
    _summarize("noisy_neighbor", stats, time.monotonic() - t0, counters)


def region_failover(
    rps: float = 300.0,
    failover_at: float = 30.0,
    duration: float = 120.0,
    kill_region: str = "us",
) -> None:
    """Kill one gateway mid-run and watch traffic redistribute.

    Phase 1: balanced traffic across all 3 regions for `failover_at` seconds.
    Phase 2: stop the gateway container for `kill_region`, then send traffic
             weighted to the surviving two regions for the remaining time.
    Phase 3: restart the killed gateway (clean recovery).

    Requires Docker — uses `docker stop` / `docker start` on the gateway container.

    Default: kill US after 30s, run for 2 minutes total.
    """
    pops = load()
    surviving = [r for r in REGIONS if r != kill_region]
    even_dist = {r: 1 / len(REGIONS) for r in REGIONS}
    failover_dist = {r: 1 / len(surviving) for r in surviving}

    click.echo(
        f"[region_failover] kill={kill_region} at={failover_at}s  "
        f"duration={duration}s  surviving={surviving}",
        err=True,
    )

    async def _run() -> Stats:
        counters_pre = _Counters()
        counters_post = _Counters()

        # Phase 1 — balanced across all regions
        click.echo(f"  phase 1: balanced traffic for {failover_at}s …", err=True)
        s1 = await _run_weighted(pops, even_dist, rps, failover_at, counters_pre)
        _summarize("pre-failover", s1, failover_at, counters_pre)

        # Kill the gateway
        click.echo(f"  stopping {_gateway_container(kill_region)} …", err=True)
        result = subprocess.run(
            ["docker", "stop", _gateway_container(kill_region)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            click.echo(
                f"  [warn] docker stop failed: {result.stderr.strip()}", err=True
            )
        else:
            click.echo(f"  {_gateway_container(kill_region)} stopped.", err=True)

        # Phase 2 — traffic to surviving regions
        remaining = duration - failover_at
        click.echo(
            f"  phase 2: routing to {surviving} for {remaining}s …", err=True
        )
        s2 = await _run_weighted(pops, failover_dist, rps, remaining, counters_post)
        _summarize("post-failover", s2, remaining, counters_post)

        # Restart the gateway
        click.echo(f"  restarting {_gateway_container(kill_region)} …", err=True)
        subprocess.run(
            ["docker", "start", _gateway_container(kill_region)],
            capture_output=True,
        )
        click.echo(f"  {_gateway_container(kill_region)} restarted.", err=True)

        total_counters = _Counters(
            counters_pre.allowed + counters_post.allowed,
            counters_pre.denied + counters_post.denied,
            counters_pre.http_errors + counters_post.http_errors,
        )
        return Stats(s1.sent + s2.sent, s1.errors + s2.errors), total_counters

    t0 = time.monotonic()
    stats, counters = asyncio.run(_run())
    _summarize("region_failover total", stats, time.monotonic() - t0, counters)


# ── CLI entry point ───────────────────────────────────────────────────────────

_SCENARIOS = {
    "global_steady": global_steady,
    "product_launch": product_launch,
    "noisy_neighbor": noisy_neighbor,
    "region_failover": region_failover,
}


@click.command()
@click.argument("scenario", type=click.Choice(list(_SCENARIOS.keys())))
def main(scenario: str) -> None:
    """Run a named demo scenario end-to-end."""
    _SCENARIOS[scenario]()


if __name__ == "__main__":
    main()
