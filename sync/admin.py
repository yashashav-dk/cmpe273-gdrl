"""
sync/admin.py — FastAPI admin surface + Prometheus scrape endpoint.

Spec:        docs/superpowers/specs/2026-04-25-sync-service-design.md §5.admin.py
Constitution: docs/sync-constitution.md Art V §3 (no new metric without panel proposal)
Reads:       counter.get_global, partition_table snapshot, buffer.size, redis ping
Writes:      partition_table (add/remove), reconciler period via callback
Don't:       expose any endpoint that mutates Redis state directly; let counter/
             partition_table own their respective writes.
"""
from __future__ import annotations

from typing import Callable
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from prometheus_client import REGISTRY, generate_latest, CONTENT_TYPE_LATEST
from sync.counter import RegionalCounter
from sync.partition_table import PartitionTable
from sync.buffer import FailoverBuffer
from sync.metrics import LOCAL_REDIS_UP, PARTITION_ACTIVE


def build_app(
    *,
    region: str,
    counter: RegionalCounter,
    partition_table: PartitionTable,
    buffer: FailoverBuffer,
    set_reconcile_period: Callable[[int], None],
) -> FastAPI:
    app = FastAPI(title=f"sync-{region}")

    @app.get("/health")
    async def health() -> dict:
        try:
            await counter._redis.ping()  # type: ignore[attr-defined]
            redis_up = True
        except Exception:
            redis_up = False
        LOCAL_REDIS_UP.labels(region=region).set(1.0 if redis_up else 0.0)
        return {"region": region, "redis_up": redis_up}

    @app.get("/admin/state")
    async def admin_state(
        user_id: str = Query(...),
        tier: str = Query("free"),
        window_id: int = Query(...),
    ) -> dict:
        slots = await counter.get_global(tier, user_id, window_id)
        if not slots:
            return {"region": region, "tier": tier, "user_id": user_id,
                    "window_id": window_id, "slots": {}, "drift": 0, "total": 0}
        drift = max(slots.values()) - min(slots.values())
        total = sum(slots.values())
        return {
            "region": region, "tier": tier, "user_id": user_id,
            "window_id": window_id, "slots": slots, "drift": drift, "total": total,
        }

    @app.post("/admin/partition")
    async def partition(body: dict) -> dict:
        f, t = body.get("from"), body.get("to")
        if not f or not t:
            raise HTTPException(status_code=400, detail="from and to are required")
        partition_table.add(f, t)
        PARTITION_ACTIVE.labels(from_region=f, to_region=t).set(1)
        return {"partitioned": [f, t]}

    @app.post("/admin/heal")
    async def heal(body: dict) -> dict:
        f, t = body.get("from"), body.get("to")
        if f and t:
            partition_table.remove(f, t)
            PARTITION_ACTIVE.labels(from_region=f, to_region=t).set(0)
            return {"healed": [f, t]}
        partition_table.clear()
        return {"healed": "all"}

    @app.post("/admin/config")
    async def config(body: dict) -> dict:
        period = body.get("reconcile_period_s")
        if not isinstance(period, int) or period < 10 or period > 300:
            raise HTTPException(status_code=400, detail="reconcile_period_s must be int in [10, 300]")
        set_reconcile_period(period)
        return {"reconcile_period_s": period}

    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics() -> PlainTextResponse:
        return PlainTextResponse(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    return app
