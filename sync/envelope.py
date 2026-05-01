"""
sync/envelope.py — wire-format envelopes for rl:sync:counter.

Spec:        docs/superpowers/specs/2026-04-25-sync-service-design.md §4
Constitution: docs/sync-constitution.md Art III §3 (transport)
Reads:       nothing (pure parse/serialize)
Writes:      nothing
Don't:       silently coerce malformed input; accept envelopes from unknown regions.

Two envelope kinds share the same channel. Counter (Contract 2 verbatim) has no
"kind" field. Reconcile envelopes have "kind":"reconcile" and a slots map.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Union

VALID_REGIONS = frozenset({"us", "eu", "asia"})
RECONCILE_VERSION = 1


class EnvelopeError(ValueError):
    pass


@dataclass(frozen=True)
class CounterEnvelope:
    tier: str
    user_id: str
    window_id: int
    region: str
    value: int
    ts_ms: int


@dataclass(frozen=True)
class ReconcileEnvelope:
    origin: str
    window_id: int
    ts_ms: int
    slots: dict[tuple[str, str], int]
    version: int = RECONCILE_VERSION


Envelope = Union[CounterEnvelope, ReconcileEnvelope]


def parse(raw: bytes) -> Envelope:
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        raise EnvelopeError(f"invalid JSON: {e}") from e
    if not isinstance(obj, dict):
        raise EnvelopeError(f"envelope is not a JSON object: {type(obj).__name__}")
    if obj.get("kind") == "reconcile":
        return _parse_reconcile(obj)
    return _parse_counter(obj)


def _parse_counter(obj: dict) -> CounterEnvelope:
    required = ("tier", "user_id", "window_id", "region", "value", "ts_ms")
    missing = [k for k in required if k not in obj]
    if missing:
        raise EnvelopeError(f"counter envelope missing fields: {missing}")
    region = obj["region"]
    if region not in VALID_REGIONS:
        raise EnvelopeError(f"counter envelope has invalid region: {region!r}")
    value = obj["value"]
    if not isinstance(value, int) or value < 0:
        raise EnvelopeError(f"counter envelope has non-monotonic value: {value!r}")
    return CounterEnvelope(
        tier=str(obj["tier"]),
        user_id=str(obj["user_id"]),
        window_id=int(obj["window_id"]),
        region=region,
        value=value,
        ts_ms=int(obj["ts_ms"]),
    )


def _parse_reconcile(obj: dict) -> ReconcileEnvelope:
    version = obj.get("v")
    if version != RECONCILE_VERSION:
        raise EnvelopeError(f"reconcile envelope has unknown version: {version!r}")
    required = ("origin", "window_id", "ts_ms", "slots")
    missing = [k for k in required if k not in obj]
    if missing:
        raise EnvelopeError(f"reconcile envelope missing fields: {missing}")
    origin = obj["origin"]
    if origin not in VALID_REGIONS:
        raise EnvelopeError(f"reconcile envelope has invalid origin: {origin!r}")
    slots_raw = obj["slots"]
    if not isinstance(slots_raw, dict):
        raise EnvelopeError("reconcile envelope slots must be an object")
    slots: dict[tuple[str, str], int] = {}
    for key, value in slots_raw.items():
        if not isinstance(key, str) or ":" not in key:
            raise EnvelopeError(f"reconcile slot key must be 'tier:user_id': {key!r}")
        tier, user_id = key.split(":", 1)
        if not isinstance(value, int) or value < 0:
            raise EnvelopeError(f"reconcile slot value must be non-negative int: {value!r}")
        slots[(tier, user_id)] = value
    return ReconcileEnvelope(
        origin=origin,
        window_id=int(obj["window_id"]),
        ts_ms=int(obj["ts_ms"]),
        slots=slots,
        version=version,
    )


def serialize_reconcile(env: ReconcileEnvelope) -> bytes:
    obj = {
        "kind": "reconcile",
        "v": env.version,
        "origin": env.origin,
        "window_id": env.window_id,
        "ts_ms": env.ts_ms,
        "slots": {f"{tier}:{user_id}": value for (tier, user_id), value in env.slots.items()},
    }
    return json.dumps(obj, separators=(",", ":")).encode("utf-8")
