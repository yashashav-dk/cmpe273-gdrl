# Sync Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the cross-region sync service for the geo-distributed rate limiter — a stateless Python relay that subscribes to `rl:sync:counter` on three Redis instances and max-merges peer slots into the local `rl:global:{tier}:{user_id}:{window_id}` hash, plus periodic reconcile, partition simulation, failover buffer, and admin endpoints. Feature-complete by 2026-05-03 (PDF Day 8) with all four test layers green.

**Architecture:** One Python asyncio process per region, three identical containers. Subscribes peer-Redis pub/sub, applies atomic Lua max-merge into local Redis, emits Prometheus metrics for lag/drift/buffer state. CRDT G-Counter semantics; AP from CAP. Single-writer-per-slot invariant: gateway writes its own region's slot via `HIncrBy`; sync writes only peer slots received over the wire. No coalescing — gateway emits one envelope per allowed request.

**Tech Stack:** Python 3.11, redis-py async (`redis>=5.0`), FastAPI, uvicorn, click, prometheus-client, pytest + pytest-asyncio, testcontainers, toxiproxy. Redis 7 vanilla, three containers (us/eu/asia on 6379/6380/6381).

**Spec:** `docs/superpowers/specs/2026-04-25-sync-service-design.md` (canonical).
**Constitution:** `docs/sync-constitution.md` (non-negotiable rules).
**Contracts:** `docs/contracts.md` (locked — Contract 2 governs the wire format).

**Branch:** `yashashav/sync-d5-foundation` (already pushed). Each PDF day = one or more PRs off this branch onto `main`.

---

## File map

### Code (~740 LOC application)

| File | Purpose | LOC |
|---|---|---|
| `sync/__init__.py` | Package marker | 0 |
| `sync/__main__.py` | `python -m sync` entrypoint | ~10 |
| `sync/crdt.py` | G-Counter primitive (lifted from `python3-crdt` MIT) | ~120 |
| `sync/envelope.py` | Counter + reconcile envelope parse/serialize | ~80 |
| `sync/counter.py` | `RegionalCounter` (Lua atomic max-merge) | ~100 |
| `sync/transport.py` | redis-py async PubSub wrapper | ~100 |
| `sync/partition_table.py` | `set[(from, to)]` directional rules | ~30 |
| `sync/relay.py` | Receive → parse → max-merge | ~80 |
| `sync/reconciler.py` | 30s window scan + broadcast | ~100 |
| `sync/buffer.py` | Bounded FIFO failover buffer | ~60 |
| `sync/admin.py` | FastAPI admin + Prometheus | ~100 |
| `sync/service.py` | asyncio orchestrator | ~100 |
| `sync/dev/gateway_stub.py` | Solo-demo harness (Contract-2 emitter) | ~60 |
| `sync/dev/sync_cli.py` | CLI inspector | ~50 |

### Tests (~250 LOC)

| File | Layer |
|---|---|
| `sync/tests/__init__.py` | (empty) |
| `sync/tests/conftest.py` | Shared fixtures (testcontainers Redis) |
| `sync/tests/unit/test_crdt.py` | L1 |
| `sync/tests/unit/test_envelope.py` | L1 |
| `sync/tests/unit/test_partition_table.py` | L1 |
| `sync/tests/unit/test_buffer.py` | L1 |
| `sync/tests/integration/test_counter_redis.py` | L2 |
| `sync/tests/integration/test_transport_pubsub.py` | L2 |
| `sync/tests/integration/test_relay.py` | L2 |
| `sync/tests/e2e/test_basic_propagation.py` | L3 |
| `sync/tests/e2e/test_partition.py` | L3 |
| `sync/tests/chaos/test_convergence.py` | L4 |
| `sync/tests/chaos/test_redis_failure.py` | L4 |
| `sync/tests/chaos/test_load.py` | L4 (D9) |

### Infra + scaffolding

| File | Purpose |
|---|---|
| `sync/pyproject.toml` | Package metadata + tool config (ruff, pytest) |
| `sync/requirements.txt` | Runtime + test deps |
| `sync/Dockerfile` | Container image |
| `infra/docker-compose.sync-only.yml` | 3 Redis + 3 sync + gateway-stub |
| `Makefile` | `test`, `test-chaos`, `demo-sync`, `convergence-proof` |
| `scripts/solo-demo.sh` | 4-min narrated demo runner |

### Docs (handover layer, §15 of spec)

| File | Purpose |
|---|---|
| `AGENTS.md` (repo root) | Cross-team navigation + four "do not break" rules |
| `sync/CONTEXT.md` | Sync-internal primer for cold readers |
| `docs/sync-design.md` | Writeup (≥1500 words by D10) |
| `docs/failure-modes.md` | F1–F7 drill record (D9) |

---

## Day 5 (2026-04-30) — Foundation + handover docs

**Gate:** Layer 1 unit tests for crdt + envelope green; Layer 2 counter integration test green; AGENTS.md + sync/CONTEXT.md committed; module docstrings on `crdt.py`, `counter.py`, `envelope.py`.

---

### Task 1: Scaffold sync package

**Files:**
- Create: `sync/__init__.py`
- Create: `sync/__main__.py`
- Create: `sync/pyproject.toml`
- Create: `sync/requirements.txt`
- Create: `sync/tests/__init__.py`
- Create: `sync/tests/unit/__init__.py`
- Create: `sync/tests/integration/__init__.py`
- Create: `sync/tests/e2e/__init__.py`
- Create: `sync/tests/chaos/__init__.py`

- [ ] **Step 1: Replace placeholder `.gitkeep`**

```bash
rm sync/.gitkeep
```

- [ ] **Step 2: Create empty package markers**

`sync/__init__.py`:
```python
```

`sync/tests/__init__.py`, `sync/tests/unit/__init__.py`, `sync/tests/integration/__init__.py`, `sync/tests/e2e/__init__.py`, `sync/tests/chaos/__init__.py`:
```python
```

- [ ] **Step 3: Create `sync/__main__.py`**

```python
from sync.service import main_cli

if __name__ == "__main__":
    main_cli()
```

- [ ] **Step 4: Create `sync/pyproject.toml`**

```toml
[project]
name = "sync"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "redis>=5.0",
    "fastapi>=0.110",
    "uvicorn>=0.27",
    "click>=8.1",
    "prometheus-client>=0.20",
    "pydantic>=2.6",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "testcontainers[redis]>=4.0",
    "httpx>=0.27",
    "ruff>=0.4",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["sync/tests"]

[tool.ruff]
line-length = 100
target-version = "py311"
```

- [ ] **Step 5: Create `sync/requirements.txt`**

```
redis>=5.0
fastapi>=0.110
uvicorn>=0.27
click>=8.1
prometheus-client>=0.20
pydantic>=2.6
pytest>=8.0
pytest-asyncio>=0.23
testcontainers[redis]>=4.0
httpx>=0.27
```

- [ ] **Step 6: Verify package imports**

Run: `python -c "import sync; import sync.tests"`
Expected: no output, exit 0.

- [ ] **Step 7: Commit**

```bash
git add sync/__init__.py sync/__main__.py sync/pyproject.toml sync/requirements.txt sync/tests/
git rm sync/.gitkeep
git commit -m "day5(sync): scaffold package — pyproject, __main__, test dirs"
```

---

### Task 2: Add infra and Makefile

**Files:**
- Create: `infra/docker-compose.sync-only.yml`
- Create: `sync/Dockerfile`
- Create: `Makefile`

- [ ] **Step 1: Create `sync/Dockerfile`**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY sync/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY sync/ /app/sync/
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-m", "sync"]
```

- [ ] **Step 2: Create `infra/docker-compose.sync-only.yml`**

```yaml
version: "3.9"
services:
  redis-us:
    image: redis:7-alpine
    ports: ["6379:6379"]
  redis-eu:
    image: redis:7-alpine
    ports: ["6380:6379"]
  redis-asia:
    image: redis:7-alpine
    ports: ["6381:6379"]

  sync-us:
    build:
      context: ..
      dockerfile: sync/Dockerfile
    depends_on: [redis-us, redis-eu, redis-asia]
    environment:
      REGION: us
      LOCAL_REDIS_URL: redis://redis-us:6379
      PEER_REDIS_URLS: redis://redis-eu:6379,redis://redis-asia:6379
    ports: ["9101:9100"]

  sync-eu:
    build:
      context: ..
      dockerfile: sync/Dockerfile
    depends_on: [redis-us, redis-eu, redis-asia]
    environment:
      REGION: eu
      LOCAL_REDIS_URL: redis://redis-eu:6379
      PEER_REDIS_URLS: redis://redis-us:6379,redis://redis-asia:6379
    ports: ["9102:9100"]

  sync-asia:
    build:
      context: ..
      dockerfile: sync/Dockerfile
    depends_on: [redis-us, redis-eu, redis-asia]
    environment:
      REGION: asia
      LOCAL_REDIS_URL: redis://redis-asia:6379
      PEER_REDIS_URLS: redis://redis-us:6379,redis://redis-eu:6379
    ports: ["9103:9100"]
```

- [ ] **Step 3: Create `Makefile`**

```makefile
.PHONY: test test-unit test-integration test-e2e test-chaos demo-sync convergence-proof clean

PYTHON ?= python3
PYTEST ?= $(PYTHON) -m pytest

test: test-unit test-integration

test-unit:
	$(PYTEST) sync/tests/unit -v

test-integration:
	$(PYTEST) sync/tests/integration -v

test-e2e:
	$(PYTEST) sync/tests/e2e -v

test-chaos:
	$(PYTEST) sync/tests/chaos -v

demo-sync:
	docker compose -f infra/docker-compose.sync-only.yml up --build

convergence-proof:
	$(PYTEST) sync/tests/chaos/test_convergence.py -v

clean:
	docker compose -f infra/docker-compose.sync-only.yml down -v
```

- [ ] **Step 4: Verify compose config parses**

Run: `docker compose -f infra/docker-compose.sync-only.yml config | head -5`
Expected: prints rendered YAML, exit 0.

- [ ] **Step 5: Commit**

```bash
git add sync/Dockerfile infra/docker-compose.sync-only.yml Makefile
git commit -m "day5(sync): infra — sync-only compose, Dockerfile, Makefile"
```

---

### Task 3: Write `AGENTS.md` (repo root)

**Files:**
- Create: `AGENTS.md`

- [ ] **Step 1: Create `AGENTS.md`**

```markdown
# Agent / LLM guide

This repo is a 4-component team project (CMPE 273). Each top-level dir has one owner; touching another's dir without coordination breaks contracts.

## Layout

| Dir | Owner | Purpose |
|---|---|---|
| `agent/` | Atharva | Observability-driven policy/override writer. Reads Prometheus metrics; writes `policy:*` and `override:*` to all 3 region Redises. |
| `gateway/` | Nikhil | Go HTTP rate limiter on `/check`. Owns `rl:local:*` (full) and own-region slot of `rl:global:*:{w}`. Token bucket + sliding window via Lua. |
| `simulator/` | Prathamesh | Python traffic generator + scenario library. Talks gateway HTTP only. |
| `sync/` | Yashashav | Cross-region max-merge relay for `rl:global:*:{w}`. Subscribes pub/sub; writes peer slots into local Redis. |
| `infra/` | shared | Docker-compose, Grafana, Prometheus. |
| `docs/` | shared | Project brief, contracts (SACRED), constitution, naming. |

## Before touching `<component>/`, read:

- `docs/contracts.md` — always. The four locked cross-team contracts.
- `docs/<component>-constitution.md` — if exists (currently `sync-constitution.md`).
- `docs/superpowers/specs/<latest-design>.md` — the design spec for the component.

If you are working in `sync/`, also read `sync/CONTEXT.md` next.

## Cross-team rules (do not break)

1. **Gateway is the only writer of `rl:local:*`** and the only writer of its own region's slot in `rl:global:{tier}:{user_id}:{window_id}`.
2. **Sync is the only writer of peer-region slots** in `rl:global:{tier}:{user_id}:{window_id}` (via atomic Lua max-merge). Sync never writes its own region's slot.
3. **Agent is the only writer of `policy:*` and `override:*`.** Gateway and sync read these read-only.
4. **No cross-region network call on a request hot path.** Ever. Hot-path I/O is local-Redis only.

## Contract-change protocol

The four contracts in `docs/contracts.md` are immutable from day 1 unless renegotiated in chat with all four owners present. If you discover you need a change:

1. Stop coding.
2. Post in team chat: "Proposing contract change: [X] → [Y]. Reason: [Z]."
3. Wait for explicit acks from affected owners.
4. Update `docs/contracts.md` and any affected constitution/spec in the same PR.
5. Then code.

## PR conventions

Branches: `<owner>/<topic>` — e.g. `yashashav/sync-d5-foundation`, `atharva/day5-decider`.
Commits: prefix with `dayN(component):` for daily-scope work, or `feat|fix|chore|docs(scope):` for non-day work.
```

- [ ] **Step 2: Verify markdown lints clean**

Run: `python -c "import pathlib; t=pathlib.Path('AGENTS.md').read_text(); assert len(t) > 1500, len(t)"`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md
git commit -m "day5(docs): AGENTS.md — cross-team navigation + four 'do not break' rules"
```

---

### Task 4: Write `sync/CONTEXT.md`

**Files:**
- Create: `sync/CONTEXT.md`

- [ ] **Step 1: Create `sync/CONTEXT.md`**

```markdown
# sync/ — context for cold readers

You are about to work in `sync/`. Read this file end-to-end before writing or modifying code. It will save you from violating an invariant that took a constitutional amendment to settle.

## §1 Mission

Make the AI traffic-shaping agent possible by giving it a globally-coherent view of per-user request volume across three regions, with bounded staleness, no matter what fails. Sync observes and replicates. It does not enforce, it does not decide.

## §2 Load-bearing invariants (quoted verbatim from `docs/sync-constitution.md`)

> **Single-writer-per-slot.** The region's gateway is the only writer of that region's slot value, full stop. Sync max-merges peer slots received via pub/sub into the local hash; sync never writes its own region's slot. (Art III §6)

> **Monotonic within a window.** Within a `window_id`, every replicated slot is monotonically non-decreasing. Window rollover (next `window_id` → new key) is the only way a slot's value resets. (Art II §3)

> **No cross-region network call on the request hot path.** Ever. Local-Redis I/O is permitted because the local hash is populated by sync's relay loop. (Art II §1, Art III §8)

> **Stateless processes.** All durable state in Redis. Restart at any moment must be safe. (Art II §5)

## §3 Module map

See `docs/superpowers/specs/2026-04-25-sync-service-design.md` §5 for full descriptions.

| Module | Purpose | Spec ref |
|---|---|---|
| `crdt.py` | G-Counter primitive | §5.crdt.py |
| `envelope.py` | Wire-format parse/serialize | §4 |
| `counter.py` | `RegionalCounter` — Lua atomic max-merge, scan helpers, own-slot-write refusal | §5.counter.py |
| `transport.py` | redis-py async PubSub wrapper | §5.transport.py |
| `partition_table.py` | Directional partition rules | §5 |
| `relay.py` | Receive → parse → max-merge | §5.relay.py, §6 Flow 2 |
| `reconciler.py` | 30s window broadcast | §5.reconciler.py, §6 Flow 3 |
| `buffer.py` | Failover FIFO buffer | §5.buffer.py |
| `admin.py` | FastAPI admin + Prometheus | §5.admin.py |
| `service.py` | asyncio orchestrator | §5.service.py |

Dependency graph: `service → {relay, reconciler, admin}; relay → {counter, transport, buffer, partition_table}; reconciler → {counter, transport}`. No cycles.

## §4 Common pitfalls (a fresh LLM in this dir tends to do these wrong)

- **Decrementing slots.** NEVER. See Constitution Art II §3. Window rollover is the only path back to zero, and it goes through Redis TTL on the old key — not via mutation.
- **Sync writing own region's slot.** NEVER. The gateway already did via Contract 2 (`HIncrBy` on `rl:global:*:{w}`). `RegionalCounter.apply_remote_slot` rejects this; do not bypass.
- **Coalescing or batching incoming envelopes.** NEVER. The gateway emits one envelope per allowed request; sync relays one-for-one. There is no dirty set, no coalescer.
- **Subscribing only to peer Redises.** Subscribe to **all 3** (including local), then drop self-origin counter envelopes in `relay.py`. Keeps partition simulation symmetric across all three subscribers.
- **Reading peer Redis from anywhere outside `sync/`.** NEVER. Sync's relay is the only path that crosses region boundaries on Redis.
- **Skipping the failing-test-first step.** Constitution Art VIII §3: a failing test before a fix. Always.

## §5 Pointers

| File | One-line summary |
|---|---|
| `docs/sync-constitution.md` | Non-negotiable principles, invariants, scope boundaries. Re-read every Monday. |
| `docs/superpowers/specs/2026-04-25-sync-service-design.md` | Canonical design spec — architecture, components, data flow, tests, timeline. |
| `docs/contracts.md` | The four locked cross-team contracts. Contract 2 = our wire format. |
| `AGENTS.md` (repo root) | Repo-wide LLM router. |

## §6 Test-layer routing

For the change you are about to make, ask which layer the first failing test belongs to:

- Pure logic (CRDT math, envelope parse, partition table, buffer FIFO) → **Layer 1** unit (`sync/tests/unit/`).
- Anything touching Redis (counter Lua, transport pubsub, reconciler scan) → **Layer 2** integration (`sync/tests/integration/`) — uses testcontainers.
- Cross-region behavior (propagation, partition, drift) → **Layer 3** e2e (`sync/tests/e2e/`) — full 3-region cluster.
- Convergence guarantees, redis-down recovery, sustained load → **Layer 4** chaos (`sync/tests/chaos/`).

If you are unsure, the higher layer is usually wrong — start as low as the change permits.
```

- [ ] **Step 2: Commit**

```bash
git add sync/CONTEXT.md
git commit -m "day5(docs): sync/CONTEXT.md — primer for cold readers (mission, invariants, pitfalls)"
```

---

### Task 5: G-Counter primitive — increment + value

**Files:**
- Create: `sync/crdt.py`
- Create: `sync/tests/unit/test_crdt.py`

- [ ] **Step 1: Write the failing tests**

`sync/tests/unit/test_crdt.py`:
```python
"""
sync/tests/unit/test_crdt.py — Layer 1 unit tests for the G-Counter primitive.

Spec: docs/superpowers/specs/2026-04-25-sync-service-design.md §3 CRDT model
"""
from sync.crdt import GCounter


def test_empty_counter_value_is_zero():
    c = GCounter("us")
    assert c.value() == 0
    assert c.slots() == {}


def test_increment_writes_only_own_slot():
    c = GCounter("us")
    c.increment(3)
    assert c.value() == 3
    assert c.slots() == {"us": 3}


def test_increment_default_is_one():
    c = GCounter("us")
    c.increment()
    assert c.slots()["us"] == 1


def test_value_sums_all_slots():
    c = GCounter.from_slots("us", {"us": 5, "eu": 7, "asia": 2})
    assert c.value() == 14
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest sync/tests/unit/test_crdt.py -v`
Expected: `ModuleNotFoundError: No module named 'sync.crdt'`.

- [ ] **Step 3: Implement minimal `crdt.py`**

`sync/crdt.py`:
```python
"""
sync/crdt.py — G-Counter primitive.

Spec:        docs/superpowers/specs/2026-04-25-sync-service-design.md §3, §5.crdt.py
Constitution: docs/sync-constitution.md Art II §3 (monotonic within window)
Reads:       nothing (pure data structure, no I/O)
Writes:      nothing (pure data structure, no I/O)
Don't:       expose set() or decrement(); add I/O.

Lifted with attribution from python3-crdt (anshulahuja98, MIT). The primitive is
deliberately I/O-free — RegionalCounter handles persistence and atomic merge.
"""
from __future__ import annotations


class GCounter:
    def __init__(self, region: str) -> None:
        self._region = region
        self._slots: dict[str, int] = {}

    @classmethod
    def from_slots(cls, region: str, slots: dict[str, int]) -> "GCounter":
        c = cls(region)
        c._slots = dict(slots)
        return c

    def increment(self, n: int = 1) -> None:
        if n < 0:
            raise ValueError("GCounter.increment requires n >= 0; decrement is forbidden")
        self._slots[self._region] = self._slots.get(self._region, 0) + n

    def merge(self, other: dict[str, int]) -> None:
        for region, value in other.items():
            cur = self._slots.get(region, 0)
            if value > cur:
                self._slots[region] = value

    def value(self) -> int:
        return sum(self._slots.values())

    def slots(self) -> dict[str, int]:
        return dict(self._slots)

    @property
    def region(self) -> str:
        return self._region
```

- [ ] **Step 4: Run tests to verify passing**

Run: `pytest sync/tests/unit/test_crdt.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add sync/crdt.py sync/tests/unit/test_crdt.py
git commit -m "day5(sync): crdt.py — G-Counter increment + value (unit tests green)"
```

---

### Task 6: G-Counter — merge max-per-slot, idempotency, commutativity

**Files:**
- Modify: `sync/tests/unit/test_crdt.py`

- [ ] **Step 1: Add the failing tests**

Append to `sync/tests/unit/test_crdt.py`:
```python
def test_merge_takes_max_per_slot():
    c = GCounter.from_slots("us", {"us": 5, "eu": 3})
    c.merge({"us": 4, "eu": 7, "asia": 2})  # us 4 < 5 keeps 5; eu 7 > 3; asia new
    assert c.slots() == {"us": 5, "eu": 7, "asia": 2}


def test_merge_is_idempotent_on_replay():
    c = GCounter.from_slots("us", {"us": 5})
    incoming = {"eu": 7, "asia": 2}
    for _ in range(100):
        c.merge(incoming)
    assert c.slots() == {"us": 5, "eu": 7, "asia": 2}


def test_merge_is_commutative():
    a = GCounter("us")
    b = GCounter("us")
    a.merge({"eu": 3})
    a.merge({"asia": 2})
    b.merge({"asia": 2})
    b.merge({"eu": 3})
    assert a.slots() == b.slots()


def test_increment_negative_raises():
    c = GCounter("us")
    import pytest
    with pytest.raises(ValueError):
        c.increment(-1)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest sync/tests/unit/test_crdt.py -v`
Expected: 8 passed (the 4 new tests should pass without code changes — `merge` is already correct).

- [ ] **Step 3: Commit**

```bash
git add sync/tests/unit/test_crdt.py
git commit -m "day5(sync): crdt — merge idempotency, commutativity, no-decrement tests"
```

---

### Task 7: Wire envelope — counter shape (Contract 2)

**Files:**
- Create: `sync/envelope.py`
- Create: `sync/tests/unit/test_envelope.py`

- [ ] **Step 1: Write the failing tests**

`sync/tests/unit/test_envelope.py`:
```python
"""
sync/tests/unit/test_envelope.py — Layer 1 unit tests for wire envelopes.

Spec: docs/superpowers/specs/2026-04-25-sync-service-design.md §4
"""
import pytest
from sync.envelope import (
    CounterEnvelope,
    ReconcileEnvelope,
    parse,
    serialize_reconcile,
    EnvelopeError,
)


def test_parse_counter_envelope_roundtrip():
    raw = (
        b'{"tier":"free","user_id":"u_123","window_id":29620586,'
        b'"region":"us","value":47,"ts_ms":1714060800123}'
    )
    env = parse(raw)
    assert isinstance(env, CounterEnvelope)
    assert env.tier == "free"
    assert env.user_id == "u_123"
    assert env.window_id == 29620586
    assert env.region == "us"
    assert env.value == 47
    assert env.ts_ms == 1714060800123


def test_parse_counter_rejects_missing_field():
    raw = b'{"tier":"free","user_id":"u_123","window_id":1,"region":"us","value":1}'
    with pytest.raises(EnvelopeError):
        parse(raw)


def test_parse_counter_rejects_bad_region():
    raw = (
        b'{"tier":"free","user_id":"u_123","window_id":1,'
        b'"region":"mars","value":1,"ts_ms":1}'
    )
    with pytest.raises(EnvelopeError):
        parse(raw)


def test_parse_counter_rejects_negative_value():
    raw = (
        b'{"tier":"free","user_id":"u_123","window_id":1,'
        b'"region":"us","value":-1,"ts_ms":1}'
    )
    with pytest.raises(EnvelopeError):
        parse(raw)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest sync/tests/unit/test_envelope.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement minimal `envelope.py`**

`sync/envelope.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify passing**

Run: `pytest sync/tests/unit/test_envelope.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add sync/envelope.py sync/tests/unit/test_envelope.py
git commit -m "day5(sync): envelope.py — counter shape parse + validation (Contract 2)"
```

---

### Task 8: Wire envelope — reconcile shape + serialize roundtrip

**Files:**
- Modify: `sync/tests/unit/test_envelope.py`

- [ ] **Step 1: Append the failing tests**

```python
def test_parse_reconcile_envelope():
    raw = (
        b'{"kind":"reconcile","v":1,"origin":"us","window_id":29620586,'
        b'"ts_ms":1714060800123,"slots":{"free:u_123":47,"premium:u_456":1203}}'
    )
    env = parse(raw)
    assert isinstance(env, ReconcileEnvelope)
    assert env.origin == "us"
    assert env.window_id == 29620586
    assert env.slots == {("free", "u_123"): 47, ("premium", "u_456"): 1203}


def test_serialize_reconcile_roundtrip():
    original = ReconcileEnvelope(
        origin="eu",
        window_id=99,
        ts_ms=42,
        slots={("free", "u_1"): 10, ("free", "u_2"): 20},
    )
    raw = serialize_reconcile(original)
    parsed = parse(raw)
    assert parsed == original


def test_parse_reconcile_rejects_unknown_version():
    raw = b'{"kind":"reconcile","v":99,"origin":"us","window_id":1,"ts_ms":1,"slots":{}}'
    with pytest.raises(EnvelopeError, match="unknown version"):
        parse(raw)


def test_parse_reconcile_rejects_bad_slot_key():
    raw = b'{"kind":"reconcile","v":1,"origin":"us","window_id":1,"ts_ms":1,"slots":{"badkey":1}}'
    with pytest.raises(EnvelopeError, match="tier:user_id"):
        parse(raw)


def test_parse_rejects_non_object():
    with pytest.raises(EnvelopeError):
        parse(b'[1,2,3]')


def test_parse_rejects_invalid_json():
    with pytest.raises(EnvelopeError):
        parse(b'not json')
```

- [ ] **Step 2: Run tests to verify passing**

Run: `pytest sync/tests/unit/test_envelope.py -v`
Expected: 10 passed.

- [ ] **Step 3: Commit**

```bash
git add sync/tests/unit/test_envelope.py
git commit -m "day5(sync): envelope — reconcile parse, serialize roundtrip, version + key validation"
```

---

### Task 9: `RegionalCounter` — atomic Lua max-merge

**Files:**
- Create: `sync/counter.py`
- Create: `sync/tests/conftest.py`
- Create: `sync/tests/integration/test_counter_redis.py`

- [ ] **Step 1: Create the testcontainers fixture**

`sync/tests/conftest.py`:
```python
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
```

- [ ] **Step 2: Write the failing test for max-merge applies higher**

`sync/tests/integration/test_counter_redis.py`:
```python
"""
sync/tests/integration/test_counter_redis.py — Layer 2 integration tests for
RegionalCounter against a real Redis (via testcontainers).

Spec: docs/superpowers/specs/2026-04-25-sync-service-design.md §5.counter.py
"""
import pytest
from sync.counter import RegionalCounter, OwnSlotWriteError


@pytest.mark.asyncio
async def test_apply_remote_slot_writes_when_higher(redis_client):
    counter = RegionalCounter("us", redis_client)
    applied = await counter.apply_remote_slot("free", "u_1", 100, "eu", 5)
    assert applied is True
    slots = await counter.get_global("free", "u_1", 100)
    assert slots == {"eu": 5}


@pytest.mark.asyncio
async def test_apply_remote_slot_skips_when_lower(redis_client):
    counter = RegionalCounter("us", redis_client)
    await counter.apply_remote_slot("free", "u_1", 100, "eu", 10)
    applied = await counter.apply_remote_slot("free", "u_1", 100, "eu", 5)
    assert applied is False
    slots = await counter.get_global("free", "u_1", 100)
    assert slots == {"eu": 10}


@pytest.mark.asyncio
async def test_apply_remote_slot_skips_when_equal(redis_client):
    counter = RegionalCounter("us", redis_client)
    await counter.apply_remote_slot("free", "u_1", 100, "eu", 7)
    applied = await counter.apply_remote_slot("free", "u_1", 100, "eu", 7)
    assert applied is False
```

- [ ] **Step 3: Run tests to verify failure**

Run: `pytest sync/tests/integration/test_counter_redis.py -v`
Expected: `ModuleNotFoundError: No module named 'sync.counter'`.

- [ ] **Step 4: Implement minimal `counter.py`**

`sync/counter.py`:
```python
"""
sync/counter.py — RegionalCounter: Lua-atomic max-merge into rl:global hash.

Spec:        docs/superpowers/specs/2026-04-25-sync-service-design.md §5.counter.py
Constitution: docs/sync-constitution.md Art III §6 (single-writer-per-slot)
Reads:       rl:global:{tier}:{user_id}:{window_id} (HGETALL, HGET)
Writes:      rl:global:{tier}:{user_id}:{window_id} (Lua max-merge HSET)
Don't:       write own region's slot (gateway exclusive); accept negative values.

Owns Contract 2 key schema. Atomic max-merge guarantees idempotency under
concurrent writers; HSET only fires if incoming > current.
"""
from __future__ import annotations

from typing import AsyncIterator
from redis.asyncio import Redis

GLOBAL_TTL_SECONDS = 300

_MAX_MERGE_LUA = """
local cur = redis.call('HGET', KEYS[1], ARGV[1])
if (not cur) or (tonumber(cur) < tonumber(ARGV[2])) then
  redis.call('HSET', KEYS[1], ARGV[1], ARGV[2])
  redis.call('EXPIRE', KEYS[1], ARGV[3])
  return 1
end
return 0
"""


class OwnSlotWriteError(Exception):
    """Raised when caller attempts to write the counter's own region slot."""


def _global_key(tier: str, user_id: str, window_id: int) -> str:
    return f"rl:global:{tier}:{user_id}:{window_id}"


class RegionalCounter:
    def __init__(self, region: str, redis: Redis) -> None:
        self._region = region
        self._redis = redis
        self._max_merge = redis.register_script(_MAX_MERGE_LUA)

    @property
    def region(self) -> str:
        return self._region

    async def apply_remote_slot(
        self,
        tier: str,
        user_id: str,
        window_id: int,
        peer_region: str,
        value: int,
    ) -> bool:
        if peer_region == self._region:
            raise OwnSlotWriteError(
                f"sync may not write own region's slot ({peer_region}); gateway is the writer"
            )
        if value < 0:
            raise ValueError(f"slot value must be non-negative; got {value}")
        key = _global_key(tier, user_id, window_id)
        result = await self._max_merge(keys=[key], args=[peer_region, value, GLOBAL_TTL_SECONDS])
        return bool(result)

    async def get_global(
        self, tier: str, user_id: str, window_id: int
    ) -> dict[str, int]:
        key = _global_key(tier, user_id, window_id)
        raw = await self._redis.hgetall(key)
        return {k.decode() if isinstance(k, bytes) else k: int(v) for k, v in raw.items()}

    async def get_own_slot(
        self, tier: str, user_id: str, window_id: int
    ) -> int:
        key = _global_key(tier, user_id, window_id)
        raw = await self._redis.hget(key, self._region)
        return int(raw) if raw is not None else 0

    async def scan_window_keys(self, window_id: int) -> AsyncIterator[tuple[str, str]]:
        pattern = f"rl:global:*:*:{window_id}"
        async for key in self._redis.scan_iter(match=pattern, count=500):
            key_str = key.decode() if isinstance(key, bytes) else key
            parts = key_str.split(":")
            if len(parts) != 5:
                continue
            yield parts[2], parts[3]
```

- [ ] **Step 5: Run tests to verify passing**

Run: `pytest sync/tests/integration/test_counter_redis.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add sync/counter.py sync/tests/conftest.py sync/tests/integration/test_counter_redis.py
git commit -m "day5(sync): counter.py — Lua atomic max-merge with TTL refresh"
```

---

### Task 10: `RegionalCounter` — own-slot refusal, TTL, idempotency, scan

**Files:**
- Modify: `sync/tests/integration/test_counter_redis.py`

- [ ] **Step 1: Append the failing tests**

```python
@pytest.mark.asyncio
async def test_apply_remote_slot_refuses_own_region(redis_client):
    counter = RegionalCounter("us", redis_client)
    with pytest.raises(OwnSlotWriteError):
        await counter.apply_remote_slot("free", "u_1", 100, "us", 5)


@pytest.mark.asyncio
async def test_apply_remote_slot_refuses_negative_value(redis_client):
    counter = RegionalCounter("us", redis_client)
    with pytest.raises(ValueError):
        await counter.apply_remote_slot("free", "u_1", 100, "eu", -1)


@pytest.mark.asyncio
async def test_apply_remote_slot_sets_ttl(redis_client):
    counter = RegionalCounter("us", redis_client)
    await counter.apply_remote_slot("free", "u_1", 100, "eu", 5)
    ttl = await redis_client.ttl("rl:global:free:u_1:100")
    assert 0 < ttl <= 300


@pytest.mark.asyncio
async def test_apply_remote_slot_refreshes_ttl_on_higher(redis_client):
    counter = RegionalCounter("us", redis_client)
    await counter.apply_remote_slot("free", "u_1", 100, "eu", 5)
    await redis_client.expire("rl:global:free:u_1:100", 10)
    await counter.apply_remote_slot("free", "u_1", 100, "eu", 6)
    ttl = await redis_client.ttl("rl:global:free:u_1:100")
    assert ttl > 10  # refreshed back to 300


@pytest.mark.asyncio
async def test_apply_remote_slot_idempotent_replay(redis_client):
    counter = RegionalCounter("us", redis_client)
    for _ in range(100):
        await counter.apply_remote_slot("free", "u_1", 100, "eu", 7)
    slots = await counter.get_global("free", "u_1", 100)
    assert slots == {"eu": 7}


@pytest.mark.asyncio
async def test_get_own_slot_returns_zero_when_absent(redis_client):
    counter = RegionalCounter("us", redis_client)
    assert await counter.get_own_slot("free", "u_1", 100) == 0


@pytest.mark.asyncio
async def test_get_own_slot_returns_value_after_hincrby(redis_client):
    # Simulate gateway HIncrBy behavior — gateway writes own region's slot directly.
    await redis_client.hincrby("rl:global:free:u_1:100", "us", 42)
    counter = RegionalCounter("us", redis_client)
    assert await counter.get_own_slot("free", "u_1", 100) == 42


@pytest.mark.asyncio
async def test_scan_window_keys_yields_only_matching_window(redis_client):
    await redis_client.hset("rl:global:free:u_1:100", "us", 1)
    await redis_client.hset("rl:global:free:u_2:100", "us", 1)
    await redis_client.hset("rl:global:free:u_3:101", "us", 1)
    counter = RegionalCounter("us", redis_client)
    found: list[tuple[str, str]] = []
    async for entry in counter.scan_window_keys(100):
        found.append(entry)
    assert sorted(found) == [("free", "u_1"), ("free", "u_2")]
```

- [ ] **Step 2: Run tests to verify passing**

Run: `pytest sync/tests/integration/test_counter_redis.py -v`
Expected: 11 passed (3 from Task 9 + 8 new).

- [ ] **Step 3: Commit**

```bash
git add sync/tests/integration/test_counter_redis.py
git commit -m "day5(sync): counter — own-slot refusal, TTL refresh, idempotency, window scan tests"
```

---

### Task 11: D5 wrap — verify gates, push branch

- [ ] **Step 1: Run all green Layer 1 + Layer 2 (counter)**

Run: `pytest sync/tests/unit sync/tests/integration/test_counter_redis.py -v`
Expected: all green (4 crdt + 10 envelope + 11 counter = 25 tests).

- [ ] **Step 2: Lint gate**

Run: `ruff check sync/`
Expected: no errors. If any, fix and re-run before pushing.

- [ ] **Step 3: Confirm handover docs exist**

Run: `test -f AGENTS.md && test -f sync/CONTEXT.md && echo OK`
Expected: `OK`.

- [ ] **Step 4: Confirm module docstrings present**

Run: `grep -l "^Spec:" sync/crdt.py sync/envelope.py sync/counter.py`
Expected: all three filenames printed.

- [ ] **Step 5: Push branch**

Run: `git push origin yashashav/sync-d5-foundation`
Expected: branch updated on origin.

---

## Day 6 (2026-05-01) — Transport + harness

**Gate:** Layer 2 transport integration test green; `gateway-stub` publishes Contract-2 envelopes against all 3 Redises in compose.

---

### Task 12: Transport — peer subscribe yields (origin, raw)

**Files:**
- Create: `sync/transport.py`
- Create: `sync/tests/integration/test_transport_pubsub.py`

- [ ] **Step 1: Write the failing test**

`sync/tests/integration/test_transport_pubsub.py`:
```python
"""
sync/tests/integration/test_transport_pubsub.py — Layer 2 integration tests
for the pub/sub transport.

Spec: docs/superpowers/specs/2026-04-25-sync-service-design.md §5.transport.py
"""
import asyncio
import pytest
import pytest_asyncio
from redis.asyncio import Redis
from testcontainers.redis import RedisContainer
from sync.transport import Transport


@pytest_asyncio.fixture
async def three_redis_clients():
    containers = [RedisContainer("redis:7-alpine") for _ in range(3)]
    for c in containers:
        c.start()
    try:
        clients = [
            Redis(
                host=c.get_container_host_ip(),
                port=int(c.get_exposed_port(6379)),
                decode_responses=False,
            )
            for c in containers
        ]
        yield clients
        for c in clients:
            await c.aclose()
    finally:
        for c in containers:
            c.stop()


@pytest.mark.asyncio
async def test_subscribe_peers_yields_origin_and_raw(three_redis_clients):
    local, peer1, peer2 = three_redis_clients
    transport = Transport(
        region="us",
        local_redis=local,
        peer_redises={"eu": peer1, "asia": peer2},
        channel="rl:sync:counter",
    )
    received: list[tuple[str, bytes]] = []

    async def consume():
        async for origin, raw in transport.subscribe_peers():
            received.append((origin, raw))
            if len(received) == 2:
                break

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.3)
    await peer1.publish("rl:sync:counter", b"hello-eu")
    await peer2.publish("rl:sync:counter", b"hello-asia")
    await asyncio.wait_for(consumer, timeout=5.0)

    received.sort()
    assert received == [("asia", b"hello-asia"), ("eu", b"hello-eu")]


@pytest.mark.asyncio
async def test_publish_local_round_trips_through_subscribe(three_redis_clients):
    local, peer1, peer2 = three_redis_clients
    transport = Transport(
        region="us",
        local_redis=local,
        peer_redises={"eu": peer1, "asia": peer2},
        channel="rl:sync:counter",
    )
    received: list[tuple[str, bytes]] = []

    async def consume():
        async for origin, raw in transport.subscribe_peers():
            received.append((origin, raw))
            if received:
                break

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.3)
    await transport.publish_local(b"reconcile-payload")
    await asyncio.wait_for(consumer, timeout=5.0)

    assert received == [("us", b"reconcile-payload")]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest sync/tests/integration/test_transport_pubsub.py -v`
Expected: `ModuleNotFoundError: No module named 'sync.transport'`.

- [ ] **Step 3: Implement minimal `transport.py`**

`sync/transport.py`:
```python
"""
sync/transport.py — pub/sub transport over redis-py async.

Spec:        docs/superpowers/specs/2026-04-25-sync-service-design.md §5.transport.py
Constitution: docs/sync-constitution.md Art III §3 (transport)
Reads:       rl:sync:counter on local + 2 peer Redises (subscribe)
Writes:      rl:sync:counter on local Redis only (publish, reconcile envelopes)
Don't:       publish to peer Redises directly; share PubSub instances across regions.

Each Transport owns one Redis Pub/Sub connection per region (3 total). Peer
subscribers tag yielded messages with origin region so the relay can apply
partition rules. Auto-reconnects with exponential backoff handled by redis-py
when health_check_interval is set; on a hard disconnect the AsyncIterator
closes and the caller restarts subscription.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator
from redis.asyncio import Redis


class Transport:
    def __init__(
        self,
        region: str,
        local_redis: Redis,
        peer_redises: dict[str, Redis],
        channel: str,
    ) -> None:
        self._region = region
        self._local = local_redis
        self._peers = {**peer_redises, region: local_redis}
        self._channel = channel

    async def publish_local(self, payload: bytes) -> int:
        return await self._local.publish(self._channel, payload)

    async def subscribe_peers(self) -> AsyncIterator[tuple[str, bytes]]:
        queue: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue()
        tasks: list[asyncio.Task] = []
        for origin, client in self._peers.items():
            tasks.append(asyncio.create_task(self._pump(origin, client, queue)))
        try:
            while True:
                origin, raw = await queue.get()
                yield origin, raw
        finally:
            for t in tasks:
                t.cancel()
            for t in tasks:
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

    async def _pump(self, origin: str, client: Redis, queue: asyncio.Queue) -> None:
        pubsub = client.pubsub()
        await pubsub.subscribe(self._channel)
        try:
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                data = msg.get("data")
                if isinstance(data, bytes):
                    await queue.put((origin, data))
        finally:
            await pubsub.unsubscribe(self._channel)
            await pubsub.aclose()
```

- [ ] **Step 4: Run tests to verify passing**

Run: `pytest sync/tests/integration/test_transport_pubsub.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add sync/transport.py sync/tests/integration/test_transport_pubsub.py
git commit -m "day6(sync): transport.py — peer pub/sub with origin-tagged subscriber"
```

---

### Task 13: Transport — reconnect resilience

**Files:**
- Modify: `sync/tests/integration/test_transport_pubsub.py`
- Modify: `sync/transport.py`

- [ ] **Step 1: Append the failing test**

```python
@pytest.mark.asyncio
async def test_subscribe_peers_recovers_after_disconnect(three_redis_clients):
    local, peer1, peer2 = three_redis_clients
    transport = Transport(
        region="us",
        local_redis=local,
        peer_redises={"eu": peer1, "asia": peer2},
        channel="rl:sync:counter",
    )
    received: list[tuple[str, bytes]] = []

    async def consume():
        async for origin, raw in transport.subscribe_peers():
            received.append((origin, raw))
            if len(received) == 2:
                break

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.3)
    await peer1.publish("rl:sync:counter", b"first")
    await asyncio.sleep(0.3)

    # Simulate transient peer reconnect by closing peer1's existing connections.
    await peer1.execute_command("CLIENT", "KILL", "TYPE", "pubsub")
    await asyncio.sleep(0.5)

    await peer1.publish("rl:sync:counter", b"second")
    await asyncio.wait_for(consumer, timeout=10.0)

    payloads = sorted(raw for _, raw in received)
    assert payloads == [b"first", b"second"]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest sync/tests/integration/test_transport_pubsub.py::test_subscribe_peers_recovers_after_disconnect -v`
Expected: hangs or fails (current `_pump` exits on disconnect).

- [ ] **Step 3: Add reconnect loop in `transport.py`**

Replace `_pump` in `sync/transport.py`:
```python
    async def _pump(self, origin: str, client: Redis, queue: asyncio.Queue) -> None:
        backoff = 1.0
        while True:
            pubsub = client.pubsub()
            try:
                await pubsub.subscribe(self._channel)
                backoff = 1.0
                async for msg in pubsub.listen():
                    if msg.get("type") != "message":
                        continue
                    data = msg.get("data")
                    if isinstance(data, bytes):
                        await queue.put((origin, data))
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(min(backoff, 30.0))
                backoff = min(backoff * 2, 30.0)
            finally:
                try:
                    await pubsub.aclose()
                except Exception:
                    pass
```

- [ ] **Step 4: Run tests to verify passing**

Run: `pytest sync/tests/integration/test_transport_pubsub.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add sync/transport.py sync/tests/integration/test_transport_pubsub.py
git commit -m "day6(sync): transport — reconnect loop with exponential backoff (1s → 30s)"
```

---

### Task 14: Gateway-stub harness

**Files:**
- Create: `sync/dev/__init__.py`
- Create: `sync/dev/gateway_stub.py`
- Create: `sync/tests/integration/test_gateway_stub.py`

- [ ] **Step 1: Write the failing integration test**

`sync/tests/integration/test_gateway_stub.py`:
```python
"""
sync/tests/integration/test_gateway_stub.py — Layer 2 integration test for the
solo-demo gateway harness. Verifies the stub emits Contract-2 envelopes that
parse successfully and that gateway-side HIncrBy populates rl:global slots.
"""
import asyncio
import pytest
from sync.envelope import parse, CounterEnvelope
from sync.dev.gateway_stub import GatewayStub


@pytest.mark.asyncio
async def test_stub_publishes_contract2_envelope_and_writes_global(redis_client):
    stub = GatewayStub(region="us", redis=redis_client)
    received: list[bytes] = []

    pubsub = redis_client.pubsub()
    await pubsub.subscribe("rl:sync:counter")

    async def consume():
        async for msg in pubsub.listen():
            if msg.get("type") == "message":
                received.append(msg["data"])
                break

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.3)

    await stub.allow_request(tier="free", user_id="u_1", window_id=42)
    await asyncio.wait_for(consumer, timeout=5.0)

    env = parse(received[0])
    assert isinstance(env, CounterEnvelope)
    assert env.tier == "free"
    assert env.user_id == "u_1"
    assert env.window_id == 42
    assert env.region == "us"
    assert env.value == 1
    assert env.ts_ms > 0

    own_slot = await redis_client.hget("rl:global:free:u_1:42", "us")
    assert int(own_slot) == 1

    await pubsub.aclose()
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest sync/tests/integration/test_gateway_stub.py -v`
Expected: `ModuleNotFoundError: No module named 'sync.dev.gateway_stub'`.

- [ ] **Step 3: Implement `gateway_stub.py`**

`sync/dev/__init__.py`:
```python
```

`sync/dev/gateway_stub.py`:
```python
"""
sync/dev/gateway_stub.py — solo-demo harness mimicking Nikhil's gateway at the
sync surface only. Emits Contract-2 envelopes after a fake HIncrBy on local
Redis. Used by docker-compose.sync-only.yml and tests/e2e to exercise sync
without depending on Nikhil's Go gateway.

Not for production. Not part of the sync runtime path.
"""
from __future__ import annotations

import json
import time
from redis.asyncio import Redis

CHANNEL = "rl:sync:counter"


class GatewayStub:
    def __init__(self, region: str, redis: Redis) -> None:
        self._region = region
        self._redis = redis

    @property
    def region(self) -> str:
        return self._region

    async def allow_request(self, tier: str, user_id: str, window_id: int) -> int:
        global_key = f"rl:global:{tier}:{user_id}:{window_id}"
        new_value = await self._redis.hincrby(global_key, self._region, 1)
        await self._redis.expire(global_key, 120)
        envelope = {
            "tier": tier,
            "user_id": user_id,
            "window_id": window_id,
            "region": self._region,
            "value": int(new_value),
            "ts_ms": int(time.time() * 1000),
        }
        await self._redis.publish(CHANNEL, json.dumps(envelope, separators=(",", ":")))
        return int(new_value)
```

- [ ] **Step 4: Run tests to verify passing**

Run: `pytest sync/tests/integration/test_gateway_stub.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add sync/dev/ sync/tests/integration/test_gateway_stub.py
git commit -m "day6(sync): gateway_stub.py — Contract-2 emitter for solo-demo"
```

---

### Task 15: `sync-cli` inspector skeleton

**Files:**
- Create: `sync/dev/sync_cli.py`

- [ ] **Step 1: Implement `sync_cli.py`**

```python
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
```

- [ ] **Step 2: Verify it imports**

Run: `python -c "from sync.dev.sync_cli import cli; print(cli.commands.keys())"`
Expected: `dict_keys(['inspect', 'partition', 'heal', 'config'])`.

- [ ] **Step 3: Commit**

```bash
git add sync/dev/sync_cli.py
git commit -m "day6(sync): sync_cli.py — operator CLI skeleton (inspect, partition, heal, config)"
```

---

### Task 16: D6 wrap — verify gates, push

- [ ] **Step 1: Run all green Layer 2**

Run: `pytest sync/tests/unit sync/tests/integration -v`
Expected: all green (25 from D5 + 3 transport + 1 stub = 29).

- [ ] **Step 2: Lint gate**

Run: `ruff check sync/`
Expected: no errors.

- [ ] **Step 3: Confirm module docstrings present**

Run: `grep -l "^Spec:" sync/transport.py sync/dev/gateway_stub.py`
Expected: both filenames printed.

- [ ] **Step 4: Push branch**

Run: `git push origin yashashav/sync-d5-foundation`

---

## Day 7 (2026-05-02) — Relay + reconciler + first e2e

**Gate:** Layer 3 e2e propagation test green; cross-region max-merge proven end-to-end with gateway-stub on a 3-region cluster.

---

### Task 17: PartitionTable — directional add/remove/blocks

**Files:**
- Create: `sync/partition_table.py`
- Create: `sync/tests/unit/test_partition_table.py`

- [ ] **Step 1: Write the failing tests**

`sync/tests/unit/test_partition_table.py`:
```python
"""
sync/tests/unit/test_partition_table.py — Layer 1 unit tests for the directional
partition rules used by relay.py to drop messages.
"""
import pytest
from sync.partition_table import PartitionTable


def test_empty_table_blocks_nothing():
    t = PartitionTable()
    assert t.blocks("us", "eu") is False


def test_add_blocks_directional():
    t = PartitionTable()
    t.add("us", "eu")
    assert t.blocks("us", "eu") is True
    assert t.blocks("eu", "us") is False  # asymmetric


def test_remove_clears_specific_pair():
    t = PartitionTable()
    t.add("us", "eu")
    t.add("us", "asia")
    t.remove("us", "eu")
    assert t.blocks("us", "eu") is False
    assert t.blocks("us", "asia") is True


def test_clear_removes_all():
    t = PartitionTable()
    t.add("us", "eu")
    t.add("eu", "asia")
    t.clear()
    assert t.snapshot() == set()


def test_snapshot_returns_copy():
    t = PartitionTable()
    t.add("us", "eu")
    snap = t.snapshot()
    snap.add(("xx", "yy"))  # mutate the copy
    assert ("xx", "yy") not in t.snapshot()
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest sync/tests/unit/test_partition_table.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `partition_table.py`**

`sync/partition_table.py`:
```python
"""
sync/partition_table.py — directional partition rules for sync's relay loop.

Spec:        docs/superpowers/specs/2026-04-25-sync-service-design.md §5, §6 Flow 4
Constitution: docs/sync-constitution.md Art VII (operational defaults)
Reads:       (in-memory only)
Writes:      (in-memory only)
Don't:       persist to Redis (state is intentionally ephemeral — restart heals).

Used to simulate cross-region partitions in tests and the demo. Asymmetric:
adding (us, eu) blocks us→eu only; eu→us still flows. Snapshots are copies
to prevent external mutation.
"""
from __future__ import annotations


class PartitionTable:
    def __init__(self) -> None:
        self._rules: set[tuple[str, str]] = set()

    def add(self, from_region: str, to_region: str) -> None:
        self._rules.add((from_region, to_region))

    def remove(self, from_region: str, to_region: str) -> None:
        self._rules.discard((from_region, to_region))

    def clear(self) -> None:
        self._rules.clear()

    def blocks(self, from_region: str, to_region: str) -> bool:
        return (from_region, to_region) in self._rules

    def snapshot(self) -> set[tuple[str, str]]:
        return set(self._rules)
```

- [ ] **Step 4: Run tests to verify passing**

Run: `pytest sync/tests/unit/test_partition_table.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add sync/partition_table.py sync/tests/unit/test_partition_table.py
git commit -m "day7(sync): partition_table.py — directional asymmetric partition rules"
```

---

### Task 18: Relay — counter envelope max-merge

**Files:**
- Create: `sync/metrics.py` (lightweight registry holder)
- Create: `sync/relay.py`
- Create: `sync/tests/integration/test_relay.py`

- [ ] **Step 1: Create `sync/metrics.py`**

```python
"""
sync/metrics.py — Prometheus metric definitions, registered once.

Spec: docs/superpowers/specs/2026-04-25-sync-service-design.md §8
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, REGISTRY

LAG_SECONDS = Histogram(
    "rl_sync_lag_seconds",
    "Sync envelope lag in seconds, measured at receive time.",
    labelnames=("from_region", "to_region"),
    buckets=(0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10),
)
MESSAGES_TOTAL = Counter(
    "rl_sync_messages_total",
    "Sync messages received by kind.",
    labelnames=("kind", "origin_region", "dest_region"),
)
MESSAGES_DROPPED = Counter(
    "rl_messages_dropped_total",
    "Sync messages dropped (partition, malformed, self-origin).",
    labelnames=("cause",),
)
RELAY_INFLIGHT = Gauge(
    "rl_relay_inflight",
    "Relay envelopes currently in flight.",
    labelnames=("region",),
)
RECONCILE_DURATION = Histogram(
    "rl_reconcile_duration_seconds",
    "Reconcile pass duration in seconds.",
    labelnames=("region",),
)
RECONCILE_KEYS = Counter(
    "rl_reconcile_keys_processed",
    "Keys processed in reconcile.",
    labelnames=("region",),
)
RECONCILE_PERIOD = Gauge(
    "rl_reconcile_period_s",
    "Configured reconcile period in seconds.",
    labelnames=("region",),
)
PARTITION_ACTIVE = Gauge(
    "rl_partition_active",
    "1 if partition rule is active for from_region → to_region.",
    labelnames=("from_region", "to_region"),
)
BUFFER_SIZE = Gauge(
    "rl_sync_buffer_size",
    "Failover buffer size by kind.",
    labelnames=("region", "kind"),
)
BUFFER_OVERFLOW = Counter(
    "rl_sync_buffer_overflow_total",
    "Failover buffer overflow drops.",
    labelnames=("region", "kind"),
)
LOCAL_REDIS_UP = Gauge(
    "rl_local_redis_up",
    "1 if local Redis is reachable.",
    labelnames=("region",),
)
```

- [ ] **Step 2: Write the failing test**

`sync/tests/integration/test_relay.py`:
```python
"""
sync/tests/integration/test_relay.py — Layer 2 integration tests for the relay
loop. Each test uses one Redis as a stand-in for both local + peer surface.
"""
import asyncio
import json
import pytest
from sync.counter import RegionalCounter
from sync.partition_table import PartitionTable
from sync.transport import Transport
from sync.relay import Relay
from sync.buffer import FailoverBuffer  # forward ref — created in Task 22


def _counter_payload(*, tier, user_id, window_id, region, value, ts_ms=1) -> bytes:
    return json.dumps({
        "tier": tier, "user_id": user_id, "window_id": window_id,
        "region": region, "value": value, "ts_ms": ts_ms,
    }).encode()


@pytest.mark.asyncio
async def test_relay_applies_peer_counter_envelope(redis_client):
    counter = RegionalCounter("us", redis_client)
    transport = Transport(
        region="us",
        local_redis=redis_client,
        peer_redises={},  # only own client; envelope arrives via local publish
        channel="rl:sync:counter",
    )
    table = PartitionTable()
    buffer = FailoverBuffer(max_entries_per_kind=100)
    relay = Relay("us", counter, transport, table, buffer)
    task = asyncio.create_task(relay.run())
    await asyncio.sleep(0.3)

    await redis_client.publish(
        "rl:sync:counter",
        _counter_payload(tier="free", user_id="u_1", window_id=10, region="eu", value=5),
    )
    await asyncio.sleep(0.5)

    slots = await counter.get_global("free", "u_1", 10)
    assert slots == {"eu": 5}
    task.cancel()


@pytest.mark.asyncio
async def test_relay_drops_self_origin_counter(redis_client):
    counter = RegionalCounter("us", redis_client)
    transport = Transport(
        region="us", local_redis=redis_client,
        peer_redises={}, channel="rl:sync:counter",
    )
    relay = Relay("us", counter, transport, PartitionTable(), FailoverBuffer(100))
    task = asyncio.create_task(relay.run())
    await asyncio.sleep(0.3)

    await redis_client.publish(
        "rl:sync:counter",
        _counter_payload(tier="free", user_id="u_1", window_id=10, region="us", value=42),
    )
    await asyncio.sleep(0.5)

    slots = await counter.get_global("free", "u_1", 10)
    assert slots == {}  # self-origin dropped
    task.cancel()


@pytest.mark.asyncio
async def test_relay_drops_when_partition_blocks(redis_client):
    counter = RegionalCounter("us", redis_client)
    transport = Transport(
        region="us", local_redis=redis_client,
        peer_redises={}, channel="rl:sync:counter",
    )
    table = PartitionTable()
    table.add("eu", "us")
    relay = Relay("us", counter, transport, table, FailoverBuffer(100))
    task = asyncio.create_task(relay.run())
    await asyncio.sleep(0.3)

    await redis_client.publish(
        "rl:sync:counter",
        _counter_payload(tier="free", user_id="u_1", window_id=10, region="eu", value=5),
    )
    await asyncio.sleep(0.5)

    slots = await counter.get_global("free", "u_1", 10)
    assert slots == {}  # partition dropped
    task.cancel()


@pytest.mark.asyncio
async def test_relay_applies_reconcile_envelope(redis_client):
    counter = RegionalCounter("us", redis_client)
    transport = Transport(
        region="us", local_redis=redis_client,
        peer_redises={}, channel="rl:sync:counter",
    )
    relay = Relay("us", counter, transport, PartitionTable(), FailoverBuffer(100))
    task = asyncio.create_task(relay.run())
    await asyncio.sleep(0.3)

    payload = json.dumps({
        "kind": "reconcile",
        "v": 1,
        "origin": "eu",
        "window_id": 10,
        "ts_ms": 1,
        "slots": {"free:u_1": 7, "free:u_2": 99},
    }).encode()
    await redis_client.publish("rl:sync:counter", payload)
    await asyncio.sleep(0.5)

    assert await counter.get_global("free", "u_1", 10) == {"eu": 7}
    assert await counter.get_global("free", "u_2", 10) == {"eu": 99}
    task.cancel()
```

- [ ] **Step 3: Run tests to verify failure**

Run: `pytest sync/tests/integration/test_relay.py -v`
Expected: `ModuleNotFoundError: No module named 'sync.relay'` (or `sync.buffer`).

- [ ] **Step 4: Implement minimal `relay.py`**

`sync/relay.py`:
```python
"""
sync/relay.py — peer envelope receiver + max-merge applicator.

Spec:        docs/superpowers/specs/2026-04-25-sync-service-design.md §5.relay.py, §6 Flow 2
Constitution: docs/sync-constitution.md Art III §3 (transport), Art III §6 (single-writer)
Reads:       rl:sync:counter on local + 2 peer Redises (via Transport)
Writes:      local rl:global:{tier}:{user_id}:{window_id} (peer slots only — never own region)
Don't:       coalesce, batch, write own region's slot, decrement.

Stateless. One pub/sub message → one max-merge. Backpressure path: failed
applies go to the FailoverBuffer; the consumer keeps draining transport so
Redis pub/sub output buffers don't overflow.
"""
from __future__ import annotations

import time
from sync.counter import RegionalCounter, OwnSlotWriteError
from sync.envelope import (
    CounterEnvelope,
    EnvelopeError,
    ReconcileEnvelope,
    parse,
)
from sync.partition_table import PartitionTable
from sync.transport import Transport
from sync.buffer import FailoverBuffer
from sync.metrics import LAG_SECONDS, MESSAGES_TOTAL, MESSAGES_DROPPED, RELAY_INFLIGHT


class Relay:
    def __init__(
        self,
        region: str,
        counter: RegionalCounter,
        transport: Transport,
        partition_table: PartitionTable,
        buffer: FailoverBuffer,
    ) -> None:
        self._region = region
        self._counter = counter
        self._transport = transport
        self._partition = partition_table
        self._buffer = buffer

    async def run(self) -> None:
        async for origin, raw in self._transport.subscribe_peers():
            RELAY_INFLIGHT.labels(region=self._region).inc()
            try:
                await self._handle(origin, raw)
            finally:
                RELAY_INFLIGHT.labels(region=self._region).dec()

    async def _handle(self, origin: str, raw: bytes) -> None:
        try:
            env = parse(raw)
        except EnvelopeError:
            MESSAGES_DROPPED.labels(cause="malformed").inc()
            return
        if self._partition.blocks(origin, self._region):
            MESSAGES_DROPPED.labels(cause="partition").inc()
            return
        if isinstance(env, CounterEnvelope):
            await self._handle_counter(origin, env)
        elif isinstance(env, ReconcileEnvelope):
            await self._handle_reconcile(origin, env)

    async def _handle_counter(self, origin: str, env: CounterEnvelope) -> None:
        if env.region == self._region:
            MESSAGES_DROPPED.labels(cause="self_origin").inc()
            return
        try:
            await self._counter.apply_remote_slot(
                env.tier, env.user_id, env.window_id, env.region, env.value
            )
        except OwnSlotWriteError:
            MESSAGES_DROPPED.labels(cause="self_origin_lua").inc()
            return
        except Exception:
            self._buffer.push("relay_apply", (env.tier, env.user_id, env.window_id, env.region, env.value))
            return
        self._observe(origin, "counter", env.ts_ms)

    async def _handle_reconcile(self, origin: str, env: ReconcileEnvelope) -> None:
        if env.origin == self._region:
            MESSAGES_DROPPED.labels(cause="self_origin").inc()
            return
        for (tier, user_id), value in env.slots.items():
            try:
                await self._counter.apply_remote_slot(
                    tier, user_id, env.window_id, env.origin, value
                )
            except OwnSlotWriteError:
                MESSAGES_DROPPED.labels(cause="self_origin_lua").inc()
                continue
            except Exception:
                self._buffer.push(
                    "relay_apply",
                    (tier, user_id, env.window_id, env.origin, value),
                )
                continue
        self._observe(origin, "reconcile", env.ts_ms)

    def _observe(self, origin: str, kind: str, ts_ms: int) -> None:
        lag = max(0.0, (time.time() * 1000 - ts_ms) / 1000.0)
        LAG_SECONDS.labels(from_region=origin, to_region=self._region).observe(lag)
        MESSAGES_TOTAL.labels(kind=kind, origin_region=origin, dest_region=self._region).inc()
```

- [ ] **Step 5: Stub `sync/buffer.py` so tests can import (Task 22 finishes it)**

`sync/buffer.py`:
```python
"""
sync/buffer.py — bounded FIFO failover buffer (placeholder; full impl in Task 22).
"""
from __future__ import annotations

from collections import deque
from typing import Any


class FailoverBuffer:
    def __init__(self, max_entries_per_kind: int = 10_000) -> None:
        self._cap = max_entries_per_kind
        self._queues: dict[str, deque] = {}

    def push(self, kind: str, payload: Any) -> bool:
        q = self._queues.setdefault(kind, deque())
        if len(q) >= self._cap:
            q.popleft()
            return False
        q.append(payload)
        return True

    def drain(self, kind: str):
        q = self._queues.get(kind)
        if not q:
            return
        while q:
            yield q.popleft()

    def size(self, kind: str) -> int:
        return len(self._queues.get(kind, ()))
```

- [ ] **Step 6: Run tests to verify passing**

Run: `pytest sync/tests/integration/test_relay.py -v`
Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add sync/metrics.py sync/relay.py sync/buffer.py sync/tests/integration/test_relay.py
git commit -m "day7(sync): relay.py + metrics.py — counter/reconcile max-merge with partition + self-origin filters"
```

---

### Task 19: Reconciler — 30s window scan + broadcast

**Files:**
- Create: `sync/reconciler.py`
- Create: `sync/tests/integration/test_reconciler.py`

- [ ] **Step 1: Write the failing test**

`sync/tests/integration/test_reconciler.py`:
```python
"""
sync/tests/integration/test_reconciler.py — Layer 2 integration tests for the
reconciler. Verifies window scan, chunked broadcast, and idempotent self-skip.
"""
import asyncio
import json
import pytest
from sync.counter import RegionalCounter
from sync.transport import Transport
from sync.reconciler import Reconciler


@pytest.mark.asyncio
async def test_reconcile_once_broadcasts_own_slots(redis_client):
    # Simulate gateway HIncrBy on three users in one window.
    await redis_client.hset("rl:global:free:u_1:100", mapping={"us": 5, "eu": 3})
    await redis_client.hset("rl:global:free:u_2:100", mapping={"us": 7})
    await redis_client.hset("rl:global:premium:u_3:100", mapping={"us": 99, "asia": 1})

    counter = RegionalCounter("us", redis_client)
    transport = Transport("us", redis_client, {}, "rl:sync:counter")

    pubsub = redis_client.pubsub()
    await pubsub.subscribe("rl:sync:counter")
    received: list[dict] = []

    async def consume():
        async for msg in pubsub.listen():
            if msg.get("type") == "message":
                received.append(json.loads(msg["data"]))
                if len(received) >= 1:
                    break

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.3)

    reconciler = Reconciler("us", counter, transport, period_s=30, chunk_size=1000)
    stats = await reconciler.reconcile_once(window_id=100)
    await asyncio.wait_for(consumer, timeout=5.0)

    assert stats.keys_processed == 3
    env = received[0]
    assert env["kind"] == "reconcile"
    assert env["v"] == 1
    assert env["origin"] == "us"
    assert env["window_id"] == 100
    assert env["slots"] == {"free:u_1": 5, "free:u_2": 7, "premium:u_3": 99}
    await pubsub.aclose()


@pytest.mark.asyncio
async def test_reconcile_once_chunks_at_chunk_size(redis_client):
    for i in range(5):
        await redis_client.hset(f"rl:global:free:u_{i}:200", "us", i)

    counter = RegionalCounter("us", redis_client)
    transport = Transport("us", redis_client, {}, "rl:sync:counter")

    pubsub = redis_client.pubsub()
    await pubsub.subscribe("rl:sync:counter")
    received: list[dict] = []

    async def consume():
        async for msg in pubsub.listen():
            if msg.get("type") == "message":
                received.append(json.loads(msg["data"]))
                if len(received) >= 3:
                    break

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.3)

    reconciler = Reconciler("us", counter, transport, period_s=30, chunk_size=2)
    stats = await reconciler.reconcile_once(window_id=200)
    await asyncio.wait_for(consumer, timeout=5.0)

    assert stats.keys_processed == 5
    assert len(received) == 3  # 5 keys / chunk_size=2 = ceil(5/2) = 3 messages
    total_slots = sum(len(env["slots"]) for env in received)
    assert total_slots == 5
    await pubsub.aclose()


@pytest.mark.asyncio
async def test_reconcile_once_skips_users_with_no_own_slot(redis_client):
    # Only eu wrote this slot; us has nothing to broadcast.
    await redis_client.hset("rl:global:free:u_1:300", "eu", 5)

    counter = RegionalCounter("us", redis_client)
    transport = Transport("us", redis_client, {}, "rl:sync:counter")
    reconciler = Reconciler("us", counter, transport, period_s=30, chunk_size=1000)
    stats = await reconciler.reconcile_once(window_id=300)
    assert stats.keys_processed == 0
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest sync/tests/integration/test_reconciler.py -v`
Expected: `ModuleNotFoundError: No module named 'sync.reconciler'`.

- [ ] **Step 3: Implement `reconciler.py`**

`sync/reconciler.py`:
```python
"""
sync/reconciler.py — periodic full-window scan + broadcast.

Spec:        docs/superpowers/specs/2026-04-25-sync-service-design.md §5.reconciler.py, §6 Flow 3
Constitution: docs/sync-constitution.md Art III §3 (reconcile is the correctness mechanism)
Reads:       local rl:global:*:*:{window_id} (HGETALL via scan + HGET own slot)
Writes:      rl:sync:counter (kind=reconcile envelopes only)
Don't:       broadcast slots from other regions (only own region's slots travel
             across the wire — peers re-broadcast their own).

Runs immediately on startup (cold-start catch-up) then every period_s. Two
windows scanned per pass (current + previous) to absorb minute-boundary skew.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from sync.counter import RegionalCounter
from sync.envelope import ReconcileEnvelope, serialize_reconcile
from sync.transport import Transport
from sync.metrics import RECONCILE_DURATION, RECONCILE_KEYS, RECONCILE_PERIOD


@dataclass
class ReconcileStats:
    keys_processed: int
    chunks_published: int


class Reconciler:
    def __init__(
        self,
        region: str,
        counter: RegionalCounter,
        transport: Transport,
        period_s: int = 30,
        chunk_size: int = 1000,
    ) -> None:
        self._region = region
        self._counter = counter
        self._transport = transport
        self._period_s = period_s
        self._chunk_size = chunk_size
        RECONCILE_PERIOD.labels(region=region).set(period_s)

    def set_period(self, period_s: int) -> None:
        self._period_s = period_s
        RECONCILE_PERIOD.labels(region=self._region).set(period_s)

    async def run(self) -> None:
        # Cold-start catch-up
        await self._tick()
        while True:
            await asyncio.sleep(self._period_s)
            await self._tick()

    async def _tick(self) -> None:
        now_window = int(time.time() // 60)
        for window_id in (now_window, now_window - 1):
            try:
                await self.reconcile_once(window_id)
            except Exception:
                continue

    async def reconcile_once(self, window_id: int) -> ReconcileStats:
        start = time.time()
        chunk: dict[tuple[str, str], int] = {}
        keys = 0
        chunks = 0
        async for tier, user_id in self._counter.scan_window_keys(window_id):
            value = await self._counter.get_own_slot(tier, user_id, window_id)
            if value <= 0:
                continue
            chunk[(tier, user_id)] = value
            keys += 1
            if len(chunk) >= self._chunk_size:
                await self._publish_chunk(window_id, chunk)
                chunk = {}
                chunks += 1
        if chunk:
            await self._publish_chunk(window_id, chunk)
            chunks += 1
        RECONCILE_DURATION.labels(region=self._region).observe(time.time() - start)
        RECONCILE_KEYS.labels(region=self._region).inc(keys)
        return ReconcileStats(keys_processed=keys, chunks_published=chunks)

    async def _publish_chunk(self, window_id: int, slots: dict[tuple[str, str], int]) -> None:
        env = ReconcileEnvelope(
            origin=self._region,
            window_id=window_id,
            ts_ms=int(time.time() * 1000),
            slots=slots,
        )
        payload = serialize_reconcile(env)
        await self._transport.publish_local(payload)
```

- [ ] **Step 4: Run tests to verify passing**

Run: `pytest sync/tests/integration/test_reconciler.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add sync/reconciler.py sync/tests/integration/test_reconciler.py
git commit -m "day7(sync): reconciler.py — 30s window scan + chunked broadcast (own slots only)"
```

---

### Task 20: E2E — basic propagation across 3 regions

**Files:**
- Create: `sync/tests/e2e/test_basic_propagation.py`

- [ ] **Step 1: Write the failing test**

`sync/tests/e2e/test_basic_propagation.py`:
```python
"""
sync/tests/e2e/test_basic_propagation.py — Layer 3 end-to-end: gateway-stub on
3 region Redises + 3 Relay instances. Verifies that a stub-emitted counter
envelope on one region propagates and merges into the other two within 2s.
"""
import asyncio
import pytest
import pytest_asyncio
from redis.asyncio import Redis
from testcontainers.redis import RedisContainer
from sync.counter import RegionalCounter
from sync.transport import Transport
from sync.partition_table import PartitionTable
from sync.buffer import FailoverBuffer
from sync.relay import Relay
from sync.dev.gateway_stub import GatewayStub


@pytest_asyncio.fixture
async def cluster():
    containers = [RedisContainer("redis:7-alpine") for _ in range(3)]
    for c in containers:
        c.start()
    clients: list[Redis] = []
    try:
        for c in containers:
            clients.append(Redis(
                host=c.get_container_host_ip(),
                port=int(c.get_exposed_port(6379)),
                decode_responses=False,
            ))
        regions = ["us", "eu", "asia"]
        by_region = dict(zip(regions, clients))
        yield by_region
        for cl in clients:
            await cl.aclose()
    finally:
        for c in containers:
            c.stop()


@pytest.mark.asyncio
async def test_gateway_publish_propagates_to_all_regions(cluster):
    counters: dict[str, RegionalCounter] = {}
    relays_tasks: list[asyncio.Task] = []
    for region in ("us", "eu", "asia"):
        counters[region] = RegionalCounter(region, cluster[region])
        peers = {r: cluster[r] for r in ("us", "eu", "asia") if r != region}
        transport = Transport(region, cluster[region], peers, "rl:sync:counter")
        relay = Relay(region, counters[region], transport, PartitionTable(), FailoverBuffer(1000))
        relays_tasks.append(asyncio.create_task(relay.run()))

    await asyncio.sleep(0.5)  # let subscribers settle

    stub = GatewayStub("us", cluster["us"])
    await stub.allow_request(tier="free", user_id="u_1", window_id=42)
    await stub.allow_request(tier="free", user_id="u_1", window_id=42)

    await asyncio.sleep(2.0)

    # us slot is gateway-side; eu + asia must have learned it via relay max-merge.
    eu_view = await counters["eu"].get_global("free", "u_1", 42)
    asia_view = await counters["asia"].get_global("free", "u_1", 42)
    assert eu_view == {"us": 2}
    assert asia_view == {"us": 2}

    for t in relays_tasks:
        t.cancel()
```

- [ ] **Step 2: Run test to verify passing**

Run: `pytest sync/tests/e2e/test_basic_propagation.py -v`
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add sync/tests/e2e/test_basic_propagation.py
git commit -m "day7(sync): e2e — basic propagation across 3-region cluster (Layer 3 green)"
```

---

### Task 21: D7 wrap — verify gates, push

- [ ] **Step 1: Run all unit + integration + e2e**

Run: `pytest sync/tests/unit sync/tests/integration sync/tests/e2e -v`
Expected: all green (29 from D6 + 5 partition_table + 4 relay + 3 reconciler + 1 e2e = 42).

- [ ] **Step 2: Lint gate**

Run: `ruff check sync/`
Expected: no errors.

- [ ] **Step 3: Confirm module docstrings**

Run: `grep -l "^Spec:" sync/relay.py sync/reconciler.py sync/partition_table.py sync/metrics.py`
Expected: all four printed (metrics.py uses minimal docstring, that's OK).

- [ ] **Step 4: Push branch (D7)**

Run: `git push origin yashashav/sync-d5-foundation`

---

## Day 8 (2026-05-03) — Robustness + admin + chaos proof

**Gate:** All four test layers green; convergence proof committed under `sync/tests/chaos/results/`; sync **feature-complete** per Constitution Art IX.

---

### Task 22: FailoverBuffer — finish + unit tests

**Files:**
- Modify: `sync/buffer.py`
- Create: `sync/tests/unit/test_buffer.py`

- [ ] **Step 1: Write the failing tests**

`sync/tests/unit/test_buffer.py`:
```python
"""
sync/tests/unit/test_buffer.py — Layer 1 unit tests for the bounded FIFO
failover buffer.

Spec: docs/superpowers/specs/2026-04-25-sync-service-design.md §5.buffer.py
"""
from sync.buffer import FailoverBuffer


def test_push_and_drain_fifo_order():
    b = FailoverBuffer(max_entries_per_kind=10)
    for i in range(5):
        b.push("relay_apply", i)
    assert list(b.drain("relay_apply")) == [0, 1, 2, 3, 4]


def test_drain_empties_queue():
    b = FailoverBuffer(max_entries_per_kind=10)
    b.push("relay_apply", "x")
    list(b.drain("relay_apply"))
    assert b.size("relay_apply") == 0


def test_overflow_drops_oldest_and_returns_false():
    b = FailoverBuffer(max_entries_per_kind=3)
    for i in range(3):
        assert b.push("k", i) is True
    assert b.push("k", 99) is False  # over cap; oldest dropped
    assert list(b.drain("k")) == [1, 2, 99]


def test_size_per_kind_independent():
    b = FailoverBuffer(max_entries_per_kind=10)
    b.push("a", 1)
    b.push("b", 2)
    b.push("b", 3)
    assert b.size("a") == 1
    assert b.size("b") == 2


def test_size_unknown_kind_is_zero():
    b = FailoverBuffer()
    assert b.size("nope") == 0
```

- [ ] **Step 2: Run tests to verify passing**

Run: `pytest sync/tests/unit/test_buffer.py -v`
Expected: 5 passed (the Task 18 stub already implements the behavior).

- [ ] **Step 3: Replace stub with the production implementation**

`sync/buffer.py`:
```python
"""
sync/buffer.py — bounded FIFO failover buffer for degraded-mode replay.

Spec:        docs/superpowers/specs/2026-04-25-sync-service-design.md §5.buffer.py, §6 Flow 5
Constitution: docs/sync-constitution.md Art VII (defaults: 10 000 entries/kind)
Reads:       (in-memory only)
Writes:      (in-memory only — emits Prometheus gauge updates)
Don't:       persist to disk; share across regions; hold references to live
             Redis clients (state must be loseable on restart).

Used when relay's `apply_remote_slot` raises (local Redis dead) or when
reconciler's publish fails. A watchdog drains the buffer when the local
Redis becomes reachable again. Bounded so a long outage cannot OOM the
process; reconcile fills any actually-lost data on recovery.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Iterator
from sync.metrics import BUFFER_SIZE, BUFFER_OVERFLOW


class FailoverBuffer:
    def __init__(self, max_entries_per_kind: int = 10_000, region: str = "unknown") -> None:
        self._cap = max_entries_per_kind
        self._region = region
        self._queues: dict[str, deque] = {}

    def push(self, kind: str, payload: Any) -> bool:
        q = self._queues.setdefault(kind, deque())
        if len(q) >= self._cap:
            q.popleft()
            BUFFER_OVERFLOW.labels(region=self._region, kind=kind).inc()
            q.append(payload)
            BUFFER_SIZE.labels(region=self._region, kind=kind).set(len(q))
            return False
        q.append(payload)
        BUFFER_SIZE.labels(region=self._region, kind=kind).set(len(q))
        return True

    def drain(self, kind: str) -> Iterator[Any]:
        q = self._queues.get(kind)
        if not q:
            return
        while q:
            yield q.popleft()
            BUFFER_SIZE.labels(region=self._region, kind=kind).set(len(q))

    def size(self, kind: str) -> int:
        return len(self._queues.get(kind, ()))
```

- [ ] **Step 4: Re-run buffer + relay tests to verify still green**

Run: `pytest sync/tests/unit/test_buffer.py sync/tests/integration/test_relay.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add sync/buffer.py sync/tests/unit/test_buffer.py
git commit -m "day8(sync): buffer.py — bounded FIFO with overflow + size metrics"
```

---

### Task 23: FastAPI admin + Prometheus

**Files:**
- Create: `sync/admin.py`
- Create: `sync/tests/integration/test_admin.py`

- [ ] **Step 1: Write the failing test**

`sync/tests/integration/test_admin.py`:
```python
"""
sync/tests/integration/test_admin.py — Layer 2 integration tests for the admin
HTTP surface. Uses FastAPI TestClient against a real Redis.
"""
import pytest
from fastapi.testclient import TestClient
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


@pytest.mark.asyncio
async def test_health_returns_200_when_redis_up(redis_client):
    app, _ = _make_app(redis_client)
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["redis_up"] is True


@pytest.mark.asyncio
async def test_admin_state_returns_drift_and_counts(redis_client):
    await redis_client.hset("rl:global:free:u_1:42", mapping={"us": 5, "eu": 3, "asia": 1})
    app, _ = _make_app(redis_client)
    with TestClient(app) as client:
        r = client.get("/admin/state", params={"user_id": "u_1", "tier": "free", "window_id": 42})
        assert r.status_code == 200
        body = r.json()
        assert body["slots"] == {"us": 5, "eu": 3, "asia": 1}
        assert body["drift"] == 4  # max - min


@pytest.mark.asyncio
async def test_admin_partition_and_heal_flip_table(redis_client):
    app, table = _make_app(redis_client)
    with TestClient(app) as client:
        r = client.post("/admin/partition", json={"from": "us", "to": "eu"})
        assert r.status_code == 200
        assert table.blocks("us", "eu") is True

        r = client.post("/admin/heal", json={"from": "us", "to": "eu"})
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
    with TestClient(app) as client:
        r = client.post("/admin/config", json={"reconcile_period_s": 60})
        assert r.status_code == 200
        assert captured == [60]


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_prometheus_text(redis_client):
    app, _ = _make_app(redis_client)
    with TestClient(app) as client:
        r = client.get("/metrics")
        assert r.status_code == 200
        body = r.text
        assert "rl_sync_lag_seconds" in body
        assert "rl_reconcile_period_s" in body
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest sync/tests/integration/test_admin.py -v`
Expected: `ModuleNotFoundError: No module named 'sync.admin'`.

- [ ] **Step 3: Implement `admin.py`**

`sync/admin.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify passing**

Run: `pytest sync/tests/integration/test_admin.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add sync/admin.py sync/tests/integration/test_admin.py
git commit -m "day8(sync): admin.py — FastAPI surface (state/partition/heal/config/metrics)"
```

---

### Task 24: Service orchestrator

**Files:**
- Create: `sync/service.py`

- [ ] **Step 1: Implement `service.py`**

```python
"""
sync/service.py — asyncio orchestrator + entrypoint.

Spec:        docs/superpowers/specs/2026-04-25-sync-service-design.md §5.service.py
Constitution: docs/sync-constitution.md Art II §5 (stateless processes)
Reads:       env vars REGION, LOCAL_REDIS_URL, PEER_REDIS_URLS
Writes:      starts asyncio tasks; stops them cleanly on signal
Don't:       hold persistent state across restart; share connections across regions.

Wires Transport, Counter, Buffer, PartitionTable, Relay, Reconciler, Admin into
one asyncio.gather. Signal-driven shutdown cancels all tasks and closes Redis
clients.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import click
import uvicorn
from redis.asyncio import Redis
from sync.counter import RegionalCounter
from sync.transport import Transport
from sync.partition_table import PartitionTable
from sync.buffer import FailoverBuffer
from sync.relay import Relay
from sync.reconciler import Reconciler
from sync.admin import build_app

CHANNEL = "rl:sync:counter"
ADMIN_PORT = 9100

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("sync")


async def amain(region: str, local_url: str, peer_urls: list[str], reconcile_period_s: int) -> None:
    local = Redis.from_url(local_url, decode_responses=False, health_check_interval=15,
                           socket_keepalive=True)
    peers = {}
    for url in peer_urls:
        peer_region = _infer_region_from_url(url, region)
        peers[peer_region] = Redis.from_url(url, decode_responses=False,
                                            health_check_interval=15, socket_keepalive=True)

    counter = RegionalCounter(region, local)
    partition_table = PartitionTable()
    buffer = FailoverBuffer(max_entries_per_kind=10_000, region=region)
    transport = Transport(region, local, peers, CHANNEL)
    relay = Relay(region, counter, transport, partition_table, buffer)
    reconciler = Reconciler(region, counter, transport, period_s=reconcile_period_s)

    app = build_app(
        region=region, counter=counter, partition_table=partition_table,
        buffer=buffer, set_reconcile_period=reconciler.set_period,
    )
    config = uvicorn.Config(app, host="0.0.0.0", port=ADMIN_PORT, log_level="info")
    server = uvicorn.Server(config)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    log.info("sync-%s booting; peers=%s; reconcile_period=%ds", region, list(peers), reconcile_period_s)
    relay_task = asyncio.create_task(relay.run(), name="relay")
    rec_task = asyncio.create_task(reconciler.run(), name="reconciler")
    server_task = asyncio.create_task(server.serve(), name="admin")

    await stop_event.wait()
    log.info("sync-%s stopping", region)
    server.should_exit = True
    for t in (relay_task, rec_task):
        t.cancel()
    await asyncio.gather(relay_task, rec_task, server_task, return_exceptions=True)
    await local.aclose()
    for c in peers.values():
        await c.aclose()


def _infer_region_from_url(url: str, self_region: str) -> str:
    for r in ("us", "eu", "asia"):
        if r != self_region and r in url:
            return r
    raise RuntimeError(f"cannot infer peer region from URL {url!r}")


@click.command()
@click.option("--region", default=lambda: os.environ.get("REGION"), required=True)
@click.option("--local-redis-url", default=lambda: os.environ.get("LOCAL_REDIS_URL"), required=True)
@click.option("--peer-redis-urls", default=lambda: os.environ.get("PEER_REDIS_URLS", ""))
@click.option("--reconcile-period-s", default=30, type=int)
def main_cli(region: str, local_redis_url: str, peer_redis_urls: str, reconcile_period_s: int) -> None:
    peers = [u.strip() for u in peer_redis_urls.split(",") if u.strip()]
    asyncio.run(amain(region, local_redis_url, peers, reconcile_period_s))
```

- [ ] **Step 2: Verify it imports**

Run: `python -c "from sync.service import main_cli; main_cli.params; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add sync/service.py
git commit -m "day8(sync): service.py — asyncio orchestrator (relay + reconciler + admin under signal handlers)"
```

---

### Task 25: E2E partition + heal

**Files:**
- Create: `sync/tests/e2e/test_partition.py`

- [ ] **Step 1: Write the failing test**

`sync/tests/e2e/test_partition.py`:
```python
"""
sync/tests/e2e/test_partition.py — Layer 3 e2e: 3-region cluster, asymmetric
partition us→eu, divergent traffic, heal, drift collapse < 5s.
"""
import asyncio
import pytest
import pytest_asyncio
from redis.asyncio import Redis
from testcontainers.redis import RedisContainer
from sync.counter import RegionalCounter
from sync.transport import Transport
from sync.partition_table import PartitionTable
from sync.buffer import FailoverBuffer
from sync.relay import Relay
from sync.reconciler import Reconciler
from sync.dev.gateway_stub import GatewayStub


@pytest_asyncio.fixture
async def cluster():
    containers = [RedisContainer("redis:7-alpine") for _ in range(3)]
    for c in containers:
        c.start()
    clients: list[Redis] = []
    try:
        for c in containers:
            clients.append(Redis(
                host=c.get_container_host_ip(),
                port=int(c.get_exposed_port(6379)),
                decode_responses=False,
            ))
        regions = ["us", "eu", "asia"]
        yield dict(zip(regions, clients))
        for cl in clients:
            await cl.aclose()
    finally:
        for c in containers:
            c.stop()


@pytest.mark.asyncio
async def test_partition_drops_traffic_then_heal_converges(cluster):
    counters: dict[str, RegionalCounter] = {}
    tables: dict[str, PartitionTable] = {}
    tasks: list[asyncio.Task] = []
    for region in ("us", "eu", "asia"):
        counters[region] = RegionalCounter(region, cluster[region])
        tables[region] = PartitionTable()
        peers = {r: cluster[r] for r in ("us", "eu", "asia") if r != region}
        transport = Transport(region, cluster[region], peers, "rl:sync:counter")
        relay = Relay(region, counters[region], transport, tables[region], FailoverBuffer(10_000, region))
        rec = Reconciler(region, counters[region], transport, period_s=2, chunk_size=1000)
        tasks.append(asyncio.create_task(relay.run()))
        tasks.append(asyncio.create_task(rec.run()))

    await asyncio.sleep(0.5)

    tables["eu"].add("us", "eu")

    stub_us = GatewayStub("us", cluster["us"])
    for _ in range(20):
        await stub_us.allow_request("free", "u_p", 100)
    await asyncio.sleep(0.5)

    eu_view_partitioned = await counters["eu"].get_global("free", "u_p", 100)
    asia_view = await counters["asia"].get_global("free", "u_p", 100)
    assert "us" not in eu_view_partitioned
    assert asia_view.get("us") == 20

    tables["eu"].remove("us", "eu")

    converged = False
    for _ in range(50):
        await asyncio.sleep(0.1)
        eu_view = await counters["eu"].get_global("free", "u_p", 100)
        if eu_view.get("us") == 20:
            converged = True
            break
    assert converged, "drift did not collapse within 5s after heal"

    for t in tasks:
        t.cancel()
```

- [ ] **Step 2: Run test to verify passing**

Run: `pytest sync/tests/e2e/test_partition.py -v`
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add sync/tests/e2e/test_partition.py
git commit -m "day8(sync): e2e — partition + heal converges < 5s (Layer 3 partition green)"
```

---

### Task 26: Chaos — convergence proof (THE PROOF)

**Files:**
- Create: `sync/tests/chaos/test_convergence.py`
- Create: `sync/tests/chaos/results/.gitkeep`

- [ ] **Step 1: Write the test**

`sync/tests/chaos/test_convergence.py`:
```python
"""
sync/tests/chaos/test_convergence.py — Layer 4 chaos: THE PROOF.

PDF Day 8 requirement. Cluster + brief baseline + ~6s partition with divergent
load + heal → assert convergence < 5s. Writes timestamped result file for the
writeup and Constitution Art V §2. The CI/local run uses a 6s partition for
speed; the pre-demo run uses 60s by setting CONVERGENCE_PARTITION_S=60.
"""
import asyncio
import datetime
import os
import pathlib
import pytest
import pytest_asyncio
import time
from redis.asyncio import Redis
from testcontainers.redis import RedisContainer
from sync.counter import RegionalCounter
from sync.transport import Transport
from sync.partition_table import PartitionTable
from sync.buffer import FailoverBuffer
from sync.relay import Relay
from sync.reconciler import Reconciler
from sync.dev.gateway_stub import GatewayStub

RESULTS_DIR = pathlib.Path(__file__).parent / "results"
CONVERGENCE_TARGET_S = 5.0
PARTITION_S = float(os.environ.get("CONVERGENCE_PARTITION_S", "6"))


@pytest_asyncio.fixture
async def cluster():
    containers = [RedisContainer("redis:7-alpine") for _ in range(3)]
    for c in containers:
        c.start()
    clients: list[Redis] = []
    try:
        for c in containers:
            clients.append(Redis(
                host=c.get_container_host_ip(),
                port=int(c.get_exposed_port(6379)),
                decode_responses=False,
            ))
        regions = ["us", "eu", "asia"]
        yield dict(zip(regions, clients))
        for cl in clients:
            await cl.aclose()
    finally:
        for c in containers:
            c.stop()


@pytest.mark.asyncio
async def test_convergence_after_partition_under_5s(cluster):
    counters: dict[str, RegionalCounter] = {}
    tables: dict[str, PartitionTable] = {}
    tasks: list[asyncio.Task] = []
    for region in ("us", "eu", "asia"):
        counters[region] = RegionalCounter(region, cluster[region])
        tables[region] = PartitionTable()
        peers = {r: cluster[r] for r in ("us", "eu", "asia") if r != region}
        transport = Transport(region, cluster[region], peers, "rl:sync:counter")
        relay = Relay(region, counters[region], transport, tables[region], FailoverBuffer(50_000, region))
        rec = Reconciler(region, counters[region], transport, period_s=2, chunk_size=1000)
        tasks.append(asyncio.create_task(relay.run()))
        tasks.append(asyncio.create_task(rec.run()))

    await asyncio.sleep(0.5)

    stub_us = GatewayStub("us", cluster["us"])

    # Baseline traffic.
    for _ in range(10):
        await stub_us.allow_request("free", "u_X", 200)
        await asyncio.sleep(0.05)

    # Partition us↛eu, divergent load.
    tables["eu"].add("us", "eu")
    partition_started = time.time()
    events_during_partition = 0
    while time.time() - partition_started < PARTITION_S:
        await stub_us.allow_request("free", "u_X", 200)
        events_during_partition += 1
        await asyncio.sleep(0.01)

    eu_view_partitioned = await counters["eu"].get_global("free", "u_X", 200)
    us_value_raw = await cluster["us"].hget("rl:global:free:u_X:200", "us")
    us_value = int(us_value_raw or 0)
    assert eu_view_partitioned.get("us", 0) < us_value, (
        f"partition not effective: eu={eu_view_partitioned} us={us_value}"
    )

    # Heal + measure.
    tables["eu"].remove("us", "eu")
    heal_started = time.time()
    converged_at = None
    deadline = heal_started + CONVERGENCE_TARGET_S * 2
    while time.time() < deadline:
        eu_view = await counters["eu"].get_global("free", "u_X", 200)
        if eu_view.get("us") == us_value:
            converged_at = time.time()
            break
        await asyncio.sleep(0.05)

    convergence_s = (converged_at - heal_started) if converged_at else float("inf")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    artifact = RESULTS_DIR / f"convergence_{stamp}.txt"
    artifact.write_text(
        f"convergence_test\n"
        f"partition_window_s={PARTITION_S}\n"
        f"events_during_partition={events_during_partition}\n"
        f"us_final_value={us_value}\n"
        f"converged_in_s={convergence_s:.3f}\n"
        f"target_s={CONVERGENCE_TARGET_S}\n"
        f"passed={convergence_s < CONVERGENCE_TARGET_S}\n"
    )

    for t in tasks:
        t.cancel()

    assert convergence_s < CONVERGENCE_TARGET_S, (
        f"convergence took {convergence_s:.3f}s > {CONVERGENCE_TARGET_S}s target; see {artifact}"
    )
```

- [ ] **Step 2: Add results dir placeholder**

```bash
mkdir -p sync/tests/chaos/results
touch sync/tests/chaos/results/.gitkeep
```

- [ ] **Step 3: Run test to verify passing**

Run: `pytest sync/tests/chaos/test_convergence.py -v`
Expected: 1 passed; new file under `sync/tests/chaos/results/`.

- [ ] **Step 4: Commit**

```bash
git add sync/tests/chaos/test_convergence.py sync/tests/chaos/results/
git commit -m "day8(sync): chaos — convergence proof (partition heals < 5s, PDF Day 8 deliverable)"
```

---

### Task 27: Chaos — local Redis failure absorbs into buffer

**Files:**
- Create: `sync/tests/chaos/test_redis_failure.py`

- [ ] **Step 1: Write the test**

`sync/tests/chaos/test_redis_failure.py`:
```python
"""
sync/tests/chaos/test_redis_failure.py — Layer 4 chaos: kill local Redis under
load, verify buffer fills.
"""
import asyncio
import pytest
from redis.asyncio import Redis
from testcontainers.redis import RedisContainer
from sync.counter import RegionalCounter
from sync.transport import Transport
from sync.partition_table import PartitionTable
from sync.buffer import FailoverBuffer
from sync.relay import Relay


@pytest.mark.asyncio
async def test_buffer_fills_when_local_redis_fails():
    container_local = RedisContainer("redis:7-alpine").start()
    container_peer = RedisContainer("redis:7-alpine").start()
    try:
        local = Redis(
            host=container_local.get_container_host_ip(),
            port=int(container_local.get_exposed_port(6379)),
            decode_responses=False,
        )
        peer = Redis(
            host=container_peer.get_container_host_ip(),
            port=int(container_peer.get_exposed_port(6379)),
            decode_responses=False,
        )

        counter = RegionalCounter("us", local)
        transport = Transport("us", local, {"eu": peer}, "rl:sync:counter")
        buffer = FailoverBuffer(1_000, region="us")
        relay = Relay("us", counter, transport, PartitionTable(), buffer)
        task = asyncio.create_task(relay.run())
        await asyncio.sleep(0.3)

        # Kill local Redis to force apply_remote_slot failures.
        container_local.stop()

        # Push 10 envelopes from peer; relay buffers them.
        for i in range(10):
            await peer.publish(
                "rl:sync:counter",
                f'{{"tier":"free","user_id":"u_{i}","window_id":1,"region":"eu","value":1,"ts_ms":1}}'.encode(),
            )
        await asyncio.sleep(1.5)
        assert buffer.size("relay_apply") > 0

        task.cancel()
        await peer.aclose()
        try:
            await local.aclose()
        except Exception:
            pass
    finally:
        try:
            container_local.stop()
        except Exception:
            pass
        container_peer.stop()
```

- [ ] **Step 2: Run test**

Run: `pytest sync/tests/chaos/test_redis_failure.py -v`
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add sync/tests/chaos/test_redis_failure.py
git commit -m "day8(sync): chaos — buffer absorbs local Redis outage"
```

---

### Task 28: Solo-demo runner

**Files:**
- Create: `scripts/solo-demo.sh`

- [ ] **Step 1: Implement `scripts/solo-demo.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$ROOT/infra/docker-compose.sync-only.yml"

echo "[1/5] booting 3 Redis + 3 sync ..."
docker compose -f "$COMPOSE_FILE" up -d --build

echo "[2/5] waiting for /health on each sync ..."
for port in 9101 9102 9103; do
  for _ in $(seq 1 30); do
    if curl -sf "http://localhost:${port}/health" >/dev/null 2>&1; then break; fi
    sleep 1
  done
done

echo "[3/5] running gateway-stub against US Redis (50 allow events) ..."
python -c "
import asyncio
from redis.asyncio import Redis
from sync.dev.gateway_stub import GatewayStub
async def main():
    r = Redis(host='localhost', port=6379)
    stub = GatewayStub('us', r)
    for _ in range(50):
        await stub.allow_request('free', 'u_demo', 1)
    await r.aclose()
asyncio.run(main())
"

echo "[4/5] inspecting state across all 3 syncs ..."
python -m sync.dev.sync_cli inspect u_demo --tier free

echo "[5/5] running convergence proof ..."
pytest "$ROOT/sync/tests/chaos/test_convergence.py" -v

echo "demo complete."
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/solo-demo.sh
```

- [ ] **Step 3: Commit**

```bash
git add scripts/solo-demo.sh
git commit -m "day8(sync): scripts/solo-demo.sh — single-command demo runner"
```

---

### Task 29: D8 wrap — final all-layers green + push + open PR

- [ ] **Step 1: Run all four layers**

Run: `pytest sync/tests/unit sync/tests/integration sync/tests/e2e sync/tests/chaos -v`
Expected: every test green. ~50 tests total.

- [ ] **Step 2: Lint gate**

Run: `ruff check sync/`
Expected: no errors.

- [ ] **Step 3: Confirm Constitution Art IX termination conditions**

Conditions to confirm in the PR description:
1. All four test layers green on the branch.
2. Convergence test result < 5s, attached under `sync/tests/chaos/results/convergence_*.txt`.
3. `scripts/solo-demo.sh` runs end-to-end on a clean clone.
4. `docs/sync-design.md` writeup outline ready (D10 finishes; D8 just confirms structure).
5. Day 9 chaos drills + `docs/failure-modes.md` deferred to D9.
6. D10 dress rehearsal deferred.

- [ ] **Step 4: Push branch**

Run: `git push origin yashashav/sync-d5-foundation`

- [ ] **Step 5: Open PR**

Run:
```bash
gh pr create --base main --head yashashav/sync-d5-foundation \
  --title "sync(d5–d8): foundation through chaos proof" \
  --body "$(cat <<'EOF'
## Summary
- Implements the sync service per `docs/superpowers/specs/2026-04-25-sync-service-design.md` (Amendment 1 applied).
- 9 modules (~740 LOC), 4-layer test suite (~50 tests), gateway-stub + sync-cli harnesses, solo-demo runner, convergence proof.
- Handover layer: `AGENTS.md`, `sync/CONTEXT.md`, per-module docstring headers.

## Verification
- All four test layers green: see CI run.
- Convergence proof: `sync/tests/chaos/results/convergence_*.txt` attached.
- Solo demo: `bash scripts/solo-demo.sh` runs without manual intervention.

## Test plan
- [ ] CI green
- [ ] Reviewer runs `make test`
- [ ] Reviewer runs `make convergence-proof`
- [ ] Reviewer skims `sync/CONTEXT.md`

EOF
)"
```

---

## Self-review summary

**Spec coverage** (spot-check against spec sections):
- §3 CRDT: Tasks 5–6 ✓
- §4 Envelope: Tasks 7–8 ✓
- §5.crdt.py: Task 5 ✓
- §5.counter.py: Tasks 9–10 ✓
- §5.transport.py: Tasks 12–13 ✓
- §5.relay.py: Task 18 ✓
- §5.reconciler.py: Task 19 ✓
- §5.buffer.py: Task 22 ✓
- §5.partition_table: Task 17 ✓
- §5.admin.py: Task 23 ✓
- §5.service.py: Task 24 ✓
- §6 Flow 1 (gateway-stub): Task 14 ✓
- §6 Flow 2 (relay): Tasks 18, 20, 25 ✓
- §6 Flow 3 (reconcile): Tasks 19, 25 ✓
- §6 Flow 4 (partition): Tasks 17, 25, 26 ✓
- §6 Flow 5 (failover): Tasks 22, 27 ✓
- §10 Layer 1: Tasks 5, 6, 7, 8, 17, 22 ✓
- §10 Layer 2: Tasks 9, 10, 12, 13, 14, 18, 19, 23 ✓
- §10 Layer 3: Tasks 20, 25 ✓
- §10 Layer 4: Tasks 26, 27; Layer 4 load test deferred to D9 per §14 mitigation
- §15.1 AGENTS.md: Task 3 ✓
- §15.2 sync/CONTEXT.md: Task 4 ✓
- §15.3 module docstrings: every module-creation task includes the docstring header ✓

**Type / signature consistency:**
- `RegionalCounter.apply_remote_slot(tier, user_id, window_id, peer_region, value)` is consistent across counter, relay, reconciler, buffer drain.
- `FailoverBuffer.push(kind, payload)` is consistent across relay (Task 18) and unit tests (Task 22).
- `Transport(region, local_redis, peer_redises, channel)` is consistent across all callers.

**Placeholder scan:** none found.

**Scope:** single feature, four working days, ~50 tests, ~740 LOC application + ~250 LOC tests. Within budget.

---

## Validation gates

Each PDF day's wrap task runs:
1. **Test gate** — `pytest` for the layers in scope that day. D5 = unit + counter integration; D6 = +transport integration; D7 = +relay/reconciler integration + e2e propagation; D8 = +e2e partition + chaos.
2. **Lint gate** — `ruff check sync/`. Cheap, catches drift before push.
3. **Docstring gate** — `grep -l "^Spec:" sync/<new modules>` to confirm the per-module handover header (§15.3) is present on everything new that day.
4. **Push gate** — `git push origin yashashav/sync-d5-foundation`. Branch state durable; tomorrow's session resumes from origin.

### Gates intentionally skipped
- **`mypy` / type-check gate.** Cost > value at 4-day budget; no public-facing types; runtime tests cover behavior. Revisit only if a typing bug actually bites.
- **GitHub Actions CI workflow file (`.github/workflows/sync-ci.yml`).** Spec §10 lists it as a deliverable; deferred to D9 alongside team-integration work. Tonight's `make test` + `ruff check` is the local equivalent and is sufficient for the merge gate at D8.
- **Pre-commit hook installation.** Yashashav can add it in D10 polish if useful; not blocking.

### Per-task gates (subagent-driven)
Inside each task the subagent loop already enforces:
1. **Implementer self-review** — final step of TDD red→green; subagent confirms tests actually exercise the new code path.
2. **Spec compliance review** — fresh subagent compares the diff against the named spec section; rejects under-builds and over-builds.
3. **Code quality review** — fresh subagent flags magic numbers, missing docstrings, oversized files, unclear naming.

A task is not marked complete until all three pass.

---

## Session phasing

Multi-session execution is the recommended path. Each PDF day → one Claude session. `/clear` between sessions; the durable state lives on `yashashav/sync-d5-foundation` (branch), `MEMORY.md` (Yashashav's per-project memory), and this plan file.

| Phase | Calendar | PDF day | Tasks | End state | Session-resume cue |
|---|---|---|---|---|---|
| 1 | 2026-04-30 (tonight) | D5 | 1–11 | Foundation + handover docs + crdt + envelope + counter; Layer 1 + counter L2 green; branch pushed | Memory: "D5 complete; resume D6" |
| 2 | 2026-05-01 | D6 | 12–16 | Transport + gateway-stub + sync-cli; Layer 2 transport green | Memory: "D6 complete; resume D7" |
| 3 | 2026-05-02 | D7 | 17–21 | Relay + reconciler + first 3-region e2e; Layer 3 propagation green | Memory: "D7 complete; resume D8" |
| 4 | 2026-05-03 | D8 | 22–29 | Buffer + admin + service + chaos proof + solo-demo; all 4 layers green; PR open | Memory: "D8 complete; PR open at #N" |
| 5 | 2026-05-04 | D9 | (D9 plan) | Failure-mode drills, team integration, load test, CI workflow | New plan: D9–D10 |
| 6 | 2026-05-05 | D10 | (D10 plan) | Dress rehearsal, sync-design.md writeup ≥1500 words | Constitution Art IX termination |

### Session start checklist (every phase after Phase 1)

When starting a new phase session:

1. **Confirm branch state.** `git checkout yashashav/sync-d5-foundation && git pull origin yashashav/sync-d5-foundation`
2. **Read the durable trio.**
   - `docs/superpowers/specs/2026-04-25-sync-service-design.md` (canonical design)
   - `docs/sync-constitution.md` (rules, especially Appendix C Amendment 1)
   - `docs/superpowers/plans/2026-04-30-sync-service-implementation.md` (this plan)
3. **Spot-check memory.** Read `MEMORY.md` in the project memory dir; the `current_work.md` entry tells you which PDF day to start.
4. **List unfinished tasks.** Skim plan for the first un-checked `- [ ]` item; that is your starting task.
5. **Resume subagent loop.** Dispatch implementer for the next task; do not redo completed tasks.

### Session end checklist (every phase)

1. Run the day's wrap-task gates (test + lint + docstring + push).
2. Update `current_work.md` memory: which PDF day completed, which is next.
3. `/clear` to release context for the next session.

