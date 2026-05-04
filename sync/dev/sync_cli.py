"""
sync/dev/sync_cli.py — operator CLI for solo demo.

Subcommands:
  inspect <user_id> [--tier free] — calls /admin/state on all 3 syncs
  partition <from> <to>           — POST /admin/partition
  heal <from> <to>                — POST /admin/heal
  config <region> --reconcile-period <s>  — POST /admin/config
"""
from __future__ import annotations

import json
import click
import httpx

DEFAULT_HOSTS = {
    "us": "http://localhost:9101",
    "eu": "http://localhost:9102",
    "asia": "http://localhost:9103",
}


@click.group()
def cli() -> None:
    pass


@cli.command()
@click.argument("user_id")
@click.option("--tier", default="free")
def inspect(user_id: str, tier: str) -> None:
    rows: list[dict] = []
    for region, base in DEFAULT_HOSTS.items():
        try:
            r = httpx.get(f"{base}/admin/state", params={"user_id": user_id, "tier": tier}, timeout=2.0)
            rows.append({"region": region, **r.json()})
        except Exception as e:
            rows.append({"region": region, "error": str(e)})
    click.echo(json.dumps(rows, indent=2))


@cli.command()
@click.argument("from_region")
@click.argument("to_region")
def partition(from_region: str, to_region: str) -> None:
    base = DEFAULT_HOSTS[to_region]
    r = httpx.post(f"{base}/admin/partition", json={"from": from_region, "to": to_region}, timeout=2.0)
    r.raise_for_status()
    click.echo(r.json())


@cli.command()
@click.argument("from_region")
@click.argument("to_region")
def heal(from_region: str, to_region: str) -> None:
    base = DEFAULT_HOSTS[to_region]
    r = httpx.post(f"{base}/admin/heal", json={"from": from_region, "to": to_region}, timeout=2.0)
    r.raise_for_status()
    click.echo(r.json())


@cli.command()
@click.argument("region")
@click.option("--reconcile-period", type=int, required=True)
def config(region: str, reconcile_period: int) -> None:
    base = DEFAULT_HOSTS[region]
    r = httpx.post(f"{base}/admin/config", json={"reconcile_period_s": reconcile_period}, timeout=2.0)
    r.raise_for_status()
    click.echo(r.json())


if __name__ == "__main__":
    cli()
