# Sync Service Design Spec

**Project codename:** `gdrl` (placeholder — final name TBD Day 7)
**Project:** CMPE 273 — Geo-distributed AI-driven rate limiter
**Owner:** Yashashav
**Component:** Distributed counter store + cross-region sync service (`gdrl/sync`)
**Date:** 2026-04-25
**Status:** Approved (brainstorm), pending user review

---

## 1. Goal & non-goals

### Goal
Build the cross-region sync layer for a 3-region rate limiter. Each region has its own Redis token-bucket store; this service replicates per-user request counts across regions so the AI agent has a global view for policy decisions.

### Non-goals
- Not the rate-limit decision engine (Nikhil owns enforcement in the Go gateway).
- Not the AI agent or policy/override replication (Atharv writes policies directly to all 3 region Redises or a shared policy store).
- Not the traffic generator or Prometheus/Grafana setup (Prathamesh).
- Not strong global consistency. AP from CAP — partition tolerance with eventual consistency.

### Success criteria
- Counters propagate across all 3 regions with p95 lag < 1s at 500 ms sync interval under normal load.
- After a 60 s simulated partition between any two regions, all regions agree within 5 s of `/admin/heal` (formal convergence test).
- Sync service survives local Redis failure with bounded in-memory buffer; drains on recovery without data loss within buffer cap.
- Demo runnable standalone (no teammate dependencies) via single `make demo-sync` command.

---

## 2. Architecture

One Python sync service process per region. Three identical instances (`sync-us`, `sync-eu`, `sync-asia`). Each owns its region's Redis, talks pub/sub to the other two.

```
┌──────────── REGION us ────────────┐    ┌──────────── REGION eu ────────────┐    ┌──────── asia ────────┐
│                                   │    │                                   │    │                      │
│  gateway-us (Go) ─PUBLISH dirty─▶ │    │  gateway-eu                       │    │  gateway-asia        │
│         │                         │    │                                   │    │                      │
│         ▼ INCR rl:local:us:...    │    │                                   │    │                      │
│  ┌─────────────┐                  │    │  ┌─────────────┐                  │    │  ┌─────────────┐     │
│  │  redis-us   │◀─SUB dirty:us──┐ │    │  │  redis-eu   │                  │    │  │ redis-asia  │     │
│  │  :6379      │                │ │    │  │  :6380      │                  │    │  │  :6381      │     │
│  └─────────────┘                │ │    │  └─────────────┘                  │    │  └─────────────┘     │
│         ▲                       │ │    │                                   │    │                      │
│         │ HSET rl:global        │ │    │                                   │    │                      │
│         │                       ▼ │    │                                   │    │                      │
│  ┌─────────────────────────────┐ │    │  ┌─────────────────────────────┐   │    │  ┌──────────────┐    │
│  │     sync-us  (Python)       │ │    │  │     sync-eu                 │   │    │  │  sync-asia   │    │
│  │  asyncio orchestrator       │ │◀──▶│  │                             │◀─▶│    │  │              │    │
│  │  ── coalescer (every Nms)   │ │    │  │                             │   │    │  │              │    │
│  │  ── reconciler (every 30s)  │ │    │  │                             │   │    │  │              │    │
│  │  ── /admin (FastAPI)        │ │    │  │                             │   │    │  │              │    │
│  └─────────────────────────────┘ │    │  └─────────────────────────────┘   │    │  └──────────────┘    │
│         │                         │    │                                   │    │                      │
└─────────┼─────────────────────────┘    └───────────────────────────────────┘    └──────────────────────┘
          │
          │  PUBLISH sync:deltas (cross-region, all 3 Redis subscribed)
          ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │  Cross-region pub/sub mesh                                           │
   │  Each sync-X publishes to its OWN local Redis sync:deltas channel    │
   │  Each sync-X subscribes to ALL 3 Redis sync:deltas channels          │
   └──────────────────────────────────────────────────────────────────────┘
```

### Process boundary
- One Python container per region. Identical image, differs by `--region`, `--local-redis-url`, `--peer-redis-urls`.
- Stateless across restarts. All persistent state in Redis. Restart = catch up via reconcile.
- Single asyncio event loop per process. Tasks: local-subscriber, peer-subscribers (×2), coalescer-publisher, reconciler, FastAPI server, watchdog.

### Network topology
- Each sync subscribes to its **local** Redis for `dirty:{region}` (gateway signals).
- Each sync subscribes to **all three** Redis instances for `sync:deltas` (peer state). 3 connections per sync = 9 cross-region subscribes total in the cluster.
- Each sync publishes only to its **local** Redis `sync:deltas` channel.
- Cross-region delivery happens via subscribers reaching peer Redises directly. No Redis cluster mode. No Redis-side replication.

### Why this shape
- One process per region matches geo-distributed framing in the writeup. Crash of `sync-us` doesn't affect EU/Asia.
- Subscribing across regions (vs Redis-side replication) keeps Redis stock vanilla and makes partition simulation trivial (subscriber filters by `from_region`).
- All state in Redis means no in-process cache to invalidate on restart. Reconcile is the universal recovery mechanism.

### Sync role: observability + agent input only (NOT enforcement)
Gateway enforces purely on local Redis token bucket (fast path). Sync replicates monotonic per-region request-allowed counts to `rl:global:*`. Agent reads global to detect cross-region noisy neighbors and writes overrides. Gateway never reads global view. Clean G-Counter semantics (always monotonic), no decrement bug.

---

## 3. CRDT model

**G-Counter, state-based, max-merge per slot.**

### Data shape
- Per (tier, user_id), each region maintains a monotonic count of requests allowed locally.
- Global state for that key = a vector of per-region counts, stored as a Redis hash:
  ```
  HSET rl:global:{tier}:{user_id} us 47 eu 42 asia 1
  ```
- Global value = sum of all slots.
- Merge rule: `slot[r] = max(local_slot[r], incoming_slot[r])` for each region r. Idempotent, commutative, associative.

### Why G-Counter
- Conflict-free: only one writer per slot (each region writes its own slot). Impossible to disagree.
- Eventually consistent under any message ordering or duplication.
- Tolerates message loss (max-merge is idempotent — replay is safe).
- Tolerates clock skew (no timestamps for ordering).

### Hard invariant
**Local slot counts only increase.** Never decrement. Token-bucket "refill" semantics are gateway-side (Lua script handles via TTL); sync-replicated counter is monotonic request-allowed-count, never tokens-remaining.

If this invariant is violated, max-merge will resurrect old values across regions. Enforced at the `RegionalCounter` API: only `increment()` is exposed, no `set()` or `decrement()`.

### Reference implementations
- `python3-crdt` (anshulahuja98, MIT, ~150 LOC G-Counter class) — lifting the data-structure code with attribution.
- `grow-counter-crdt` (sultaniman, Apache, ~100 LOC pub/sub transport pattern) — lifting the broadcast pattern with attribution.
- `akka-distributed-data` GCounter.scala — algorithm reference for correctness sanity check.

---

## 4. Wire envelope (cross-region channel `sync:deltas`)

```json
{
  "v": 1,
  "kind": "delta" | "reconcile",
  "origin": "us",
  "ts_ms": 1714060800123,
  "slots": {
    "free:u_123": {"us": 47},
    "premium:u_456": {"us": 1203}
  }
}
```

- `slots` keyed by `"{tier}:{user_id}"`. Value is origin region's monotonic slot count for that key. Only origin's slot included; receivers max-merge into their own hash.
- `kind=delta` — coalesced batch from dirty set (every N ms).
- `kind=reconcile` — full local-namespace dump, chunked at 1000 keys/message (every 30 s).
- `ts_ms` used for `rl_sync_lag_seconds` metric. Not used for ordering (max-merge is order-independent).

### Bandwidth math
Steady state, 500 ms interval, 100 active users/region:
- Per tick ~100 dirty entries × ~50 bytes JSON = ~5 KB envelope.
- 2 publish/sec × 5 KB = 10 KB/sec per region.
- Cross-region 30 KB/sec aggregate. Peer subscribers ingest 60 KB/sec per sync. Trivial.

Reconcile every 30 s, 10 k keys × 50 bytes = 500 KB chunked into 10 messages of 50 KB. ~1 msg/sec aggregate. Trivial.

Even at 5 k req/s sustained load, dirty-set coalescing keeps publish rate at 2 Hz. Pub/sub output buffer never near 32 MB cap.

---

## 5. Components

8 modules. Each ≤ 150 LOC. Single-purpose, isolated, independently testable.

### `sync/crdt.py` — G-Counter primitive (~120 LOC)
Pure data structure. No I/O. Lifted from `python3-crdt` (MIT, attribution in header).
```python
class GCounter:
    def __init__(self, region: str): ...
    def increment(self, n: int = 1) -> None        # only local region's slot
    def merge(self, other: dict[str,int]) -> None  # max-per-slot
    def value(self) -> int                          # sum of all slots
    def slots(self) -> dict[str,int]                # for serialization
    @classmethod
    def from_slots(cls, region: str, slots: dict[str,int]) -> "GCounter"
```

### `sync/counter.py` — Redis-backed regional counter (~100 LOC)
Owns Contract 2 key schema. PDF-named methods.
```python
class RegionalCounter:
    def __init__(self, region: str, redis: Redis): ...
    async def increment(self, tier: str, user_id: str) -> int
        # INCR rl:local:{region}:{tier}:{user_id}, EX window+60
    async def get_local(self, tier: str, user_id: str) -> int
        # GET rl:local:{region}:{tier}:{user_id}
    async def get_global(self, tier: str, user_id: str) -> dict[str,int]
        # HGETALL rl:global:{tier}:{user_id}
    async def apply_remote_slot(self, tier, user_id, region, count) -> None
        # Atomic max-merge via Lua: only writes if incoming > current
    async def scan_dirty_local(self) -> AsyncIterator[tuple[str,str,int]]
        # SCAN MATCH rl:local:{self.region}:*
```
Atomic max-merge Lua:
```lua
local cur = redis.call('HGET', KEYS[1], ARGV[1])
if (not cur) or (tonumber(cur) < tonumber(ARGV[2])) then
  redis.call('HSET', KEYS[1], ARGV[1], ARGV[2])
  return 1
end
return 0
```

### `sync/transport.py` — Pub/sub publish + subscribe (~100 LOC)
Wraps redis-py async PubSub. Reconnection, health checks, message envelope.
```python
class Transport:
    def __init__(self, local_redis, peer_redises: dict[str,Redis]): ...
    async def publish_local(self, channel: str, payload: bytes) -> None
    async def subscribe_local(self, channel: str) -> AsyncIterator[bytes]
    async def subscribe_peers(self, channel: str) -> AsyncIterator[tuple[str,bytes]]
```
Settings: `health_check_interval=15`, `socket_keepalive=True`. Auto-reconnect with exponential backoff (1s → 2s → 4s → max 30s). Re-subscribe on reconnect (subscriptions are per-connection, not server-side).

### `sync/coalescer.py` — Dirty-set + periodic broadcast (~120 LOC)
```python
class Coalescer:
    def __init__(self, region, counter, transport, interval_ms: int): ...
    def mark_dirty(self, tier: str, user_id: str) -> None
    async def run(self) -> None  # every interval_ms
    def set_interval(self, ms: int) -> None  # hot-reload from /admin/config
```
Dirty set = `set[tuple[str,str]]`. Bounded at 50 k (drop oldest on overflow, log warning, count overflow metric, reconciler covers gaps).

### `sync/reconciler.py` — 30s full-state max-merge (~80 LOC)
```python
class Reconciler:
    def __init__(self, region, counter, transport, period_s: int = 30): ...
    async def run(self) -> None
    async def reconcile_once(self) -> ReconcileStats
        # SCAN local rl:local:{region}:*, chunk into 1000-key messages,
        # publish on sync:deltas with envelope kind=reconcile
```
Runs immediately on startup (cold-start catch-up), then every 30 s.

### `sync/buffer.py` — In-memory degraded-mode buffer (~60 LOC)
```python
class FailoverBuffer:
    def __init__(self, max_entries: int = 10_000): ...
    def push(self, kind: Literal["dirty","delta"], payload) -> None
    def drain(self) -> Iterator
    def size(self) -> int
```
Used by Coalescer + Transport when calls fail. Drain triggered on reconnect. Bounded; on overflow drops oldest with metric.

### `sync/admin.py` — FastAPI admin server (~100 LOC)
```
GET  /health                          → 200 if all subscribers alive
GET  /admin/state?user_id=X           → per-region counts + drift + staleness
POST /admin/partition {from,to}       → block messages (asymmetric supported)
POST /admin/heal {from?,to?}          → clear partition rules
POST /admin/config {sync_interval_ms} → hot-reload coalescer interval
GET  /metrics                         → Prometheus scrape
```

### `sync/service.py` — Orchestrator + entrypoint (~100 LOC)
asyncio main. Wires everything. CLI flags.
```python
async def main(region, local_redis_url, peer_redis_urls, sync_interval_ms): ...
```
Tasks under one `asyncio.gather` with cancellation on signal.

### Module dependency graph
```
service.py ─┬─▶ coalescer.py ─┬─▶ counter.py ─▶ crdt.py
            │                 ├─▶ transport.py
            │                 └─▶ buffer.py
            ├─▶ reconciler.py ─▶ counter.py
            │                  └─▶ transport.py
            └─▶ admin.py ─▶ (refs to coalescer, counter, transport)
```
No circular deps. crdt.py is leaf, testable in isolation.

### Total LOC
~780 LOC application + ~200 LOC tests + ~50 LOC `gateway-stub` dev harness. Within budget for 4-5 effective build days.

---

## 6. Data flow

### Flow 1 — Hot path: gateway request → counter increment
```
1. Client → POST /check {user_id:u_123, tier:free, region:us, endpoint:/api/v1/foo}
2. gateway-us runs Lua: token bucket check → allow.
3. gateway-us: INCR rl:local:us:free:u_123  EX 120          (Nikhil)
4. gateway-us: PUBLISH dirty:us "free:u_123"                (Nikhil, Day-0 contract)
5. gateway-us → client: {allowed:true, remaining:9, ...}
```
Sync coupling adds 1 PUBLISH (~0.1 ms). Fire-and-forget; doesn't block response.

### Flow 2 — Sync path: dirty signal → cross-region broadcast
```
1. sync-us local-subscriber receives "free:u_123" on dirty:us
2. coalescer.mark_dirty("free", "u_123") → adds to in-memory set
3. Every sync_interval_ms (default 500), coalescer tick:
   a. drain dirty set
   b. for each: count = await counter.get_local(tier, user_id)
   c. build envelope kind=delta with slots
   d. transport.publish_local("sync:deltas", envelope)
   e. clear dirty set
```

### Flow 3 — Sync path: peer broadcast → local hash merge
```
1. sync-eu peer-subscriber receives envelope from redis-us sync:deltas
2. parse → check partition table (drop if (origin, self) blocked)
3. record lag: rl_sync_lag_seconds.observe(now_ms - envelope.ts_ms)
4. for each (key, slot_dict) in envelope.slots:
     for region, count in slot_dict.items():
       await counter.apply_remote_slot(tier, user_id, region, count)
5. metric: rl_sync_messages_total{kind=delta, origin=us}.inc()
```

### Flow 4 — Reconcile: 30 s full-state catch-up
```
Every 30 s in each sync-X:
1. reconciler.reconcile_once():
   a. SCAN MATCH rl:local:{region}:*
   b. for each key, parse → (tier, user_id), GET count
   c. accumulate into chunks of 1000 entries
   d. for each chunk: build envelope kind=reconcile, publish
2. Also write own slots into local rl:global:* (covers cold-start)
3. Receivers process reconcile envelopes identically to delta.
   Max-merge is idempotent → safe to replay.
4. metric: rl_reconcile_duration_seconds.observe(elapsed)
```

### Flow 5 — Partition simulation
```
Operator: POST /admin/partition {"from":"us","to":"eu"}
1. admin handler: partition_set.add(("us","eu"))
2. peer-subscriber on sync-eu, receiving envelope where origin=us:
     if (origin, self.region) in partition_set: drop, increment metric
3. After 60s: POST /admin/heal
4. partition_set.clear()
5. Next reconcile (≤30s) → drift converges via max-merge
```
Asymmetric drops supported.

### Flow 6 — Degraded mode: local Redis dies
```
1. counter.get_local raises ConnectionError
2. coalescer pushes (tier, user_id) into FailoverBuffer kind=dirty
3. coalescer logs, increments rl_sync_buffer_size{kind=dirty}
4. Transport.publish_local fails → buffer push for kind=delta
5. background watchdog (1s tick) PINGs Redis
6. on success: drain buffer FIFO, retry each entry
7. metric returns to 0
```
Buffer cap 10 k. Overflow drops oldest with metric. Reconcile fills any actually-lost data.

---

## 7. Failure mode matrix (PDF Day 9 requirement)

| Mode | Detection | Response | Recovery time |
|---|---|---|---|
| F1 Local Redis down | ConnectionError + watchdog PING fail | Buffer dirty + delta entries; `/health`=503 | Buffer drain on PING success |
| F2 Peer Redis down | Subscriber raises | Reconnect with backoff (max 30s); other peers unaffected | ≤30s + next reconcile |
| F3 Pub/sub message drop | Output-buffer overflow → disconnect | Reconnect, resubscribe | ≤30s via reconcile |
| F4 Sync service crash | Process exit | Decoupled from gateway. On restart: connect, subscribe, immediate reconcile | ≤30s + reconcile (~1-2s for 10k keys) |
| F5 Network partition | Operator-initiated `/admin/partition` (or real F2) | Continue local; `rl:global` becomes one-sided | ≤5s after `/admin/heal` (test-enforced) |
| F6 Clock skew | `rl_sync_lag_seconds` shows negative | Tolerated. Timestamps used only for observation, not ordering | None needed (CRDT property) |
| F7 Reconcile partial failure | apply_remote_slot raises mid-chunk | Log + continue. Max-merge is idempotent → next reconcile retries | ≤30s |

### Why no consensus / no leader
- Consensus = blocking. Rate-limit decisions must be ms-fast.
- Leader-based = SPOF or expensive failover.
- CRDT max-merge = always-write, eventually-consistent, partition-tolerant. Correct tool. AP from CAP. Justified for use case (rate limiting tolerates over-allow during partitions; under-allow would be worse).

---

## 8. Metrics

### Required by PDF Contract 3
```
rl_sync_lag_seconds{from_region, to_region}   histogram
  buckets [0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10]
  sampled per received envelope
```

### Sync-owned additional
```
rl_sync_messages_total{kind, origin_region, dest_region}    counter
rl_messages_dropped_total{cause}                            counter
rl_dirty_set_size{region}                                   gauge
rl_sync_buffer_size{region, kind}                           gauge
rl_sync_buffer_overflow_total{region, kind}                 counter
rl_local_redis_up{region}                                   gauge (0/1)
rl_peer_connection_up{from_region, to_region}               gauge (0/1)
rl_peer_reconnect_total{from_region, to_region}             counter
rl_subscriber_disconnects_total{from_region}                counter
rl_reconcile_duration_seconds                               histogram
rl_reconcile_keys_processed{region}                         counter
rl_partition_active{from_region, to_region}                 gauge (0/1)
rl_coalescer_interval_ms{region}                            gauge
rl_global_counter_drift{tier, user_id}                      gauge (sampled top-100 active)
```

`rl_global_counter_drift` = `max(slot) − min(slot)` across regions per key. Spikes during partition, collapses after heal. Demo signal.

---

## 9. Demo plan

### Standalone runtime: `make demo-sync`
Single command brings up only what sync needs: 3 Redis + 3 sync containers + `gateway-stub` (50-LOC Python harness mimicking Nikhil's `PUBLISH dirty:{region}` calls). No teammate code required.

When Nikhil's real gateway lands, swap `gateway-stub` for `gateway-us` in compose file. Zero sync code changes.

### Demo arc — 4 minutes of Yashashav-narrated content
1. **Steady state (45s).** Grafana sync-lag p95 < 200ms across regions. Drift near zero.
2. **Crank the knob (30s).** `POST /admin/config sync_interval_ms=5000` → lag spikes, drift widens. Crank back to 50ms → converges instantly. Demonstrates the latency-vs-accuracy tradeoff live.
3. **Partition (75s).** `POST /admin/partition us eu` + spike traffic on US for 30s. Counts diverge visibly. `POST /admin/heal` → drift collapses < 5s. Show `GET /admin/state?user_id=X` from both syncs side-by-side.
4. **Local Redis dies (45s).** `docker stop redis-eu`, run traffic, watch `rl_sync_buffer_size{region=eu}` climb. `docker start redis-eu` → buffer drains to 0.
5. **Convergence test result (45s).** `pytest tests/chaos/test_convergence.py -v` → "Partition 60s, 1247 events, converged in 3.2s ✓"

### Demo aids
- `GET /admin/state?user_id=X` returns `{tier, user_id, local_count, global_view, drift, stale_seconds}` — narration anchor.
- `sync-cli` (~50 LOC click app):
  - `sync-cli inspect <user_id>` — calls all 3 `/admin/state`, side-by-side table
  - `sync-cli partition us eu`
  - `sync-cli heal`
  - `sync-cli config us --interval 5000`

### Grafana panels (built by Prathamesh, spec'd by us)
```
Row 1 — Sync health
  A: rl_sync_lag_seconds p50/p95/p99 by from→to
  B: rl_sync_messages_total rate by origin
  C: rl_local_redis_up + rl_peer_connection_up status grid

Row 2 — Coalescing
  D: rl_dirty_set_size per region
  E: rl_coalescer_interval_ms (single stat — DEMO KNOB INDICATOR)
  F: messages/sec on sync:deltas

Row 3 — Drift / convergence
  G: rl_global_counter_drift top-N
  H: rl_partition_active binary timeline

Row 4 — Reconcile + buffer
  I: rl_reconcile_duration_seconds + key count
  J: rl_sync_buffer_size by region+kind
```

---

## 10. Test plan

### Layer 1 — Unit (no Redis, no network) — `tests/unit/`
Pure logic, <1s per test, runs in CI on every PR.
- `test_crdt.py` — increment/merge max-per-slot, idempotency (apply 100x same), commutativity
- `test_envelope.py` — serialize roundtrip, version field, reject unknown version
- `test_buffer.py` — FIFO drain, overflow drops oldest, size metric
- `test_partition_table.py` — direction blocking, asymmetric, heal clears

### Layer 2 — Integration (real Redis via testcontainers) — `tests/integration/`
- `test_counter_redis.py` — TTL persistence, max-merge Lua atomic, no-decrement protection, scan filters region
- `test_transport_pubsub.py` — publish/subscribe local, peer subscriber yields origin, reconnect resubscribes, health check detects dead connection (toxiproxy fixture)
- `test_coalescer.py` — dirty signal triggers publish within interval, multiple signals same key coalesce to 1 publish, set_interval hot-reload

### Layer 3 — End-to-end with full 3-region cluster — `tests/e2e/`
Uses `docker-compose.sync-only.yml`.
- `test_basic_propagation.py` — increment in US visible in EU within 2s, also in Asia, global view sums regions
- `test_partition.py` — partition drops messages, EU view of US freezes, heal converges < 5s, asymmetric works

### Layer 4 — Chaos / soak — `tests/chaos/`
Long-running; nightly CI + manual pre-demo.
- `test_convergence.py` — **THE PROOF (PDF Day 8 requirement).** Cluster + 30s baseline + 60s partition + 60s divergent load + heal → assert convergence < 5s. Writes `tests/chaos/results/convergence_YYYYMMDD.txt`.
- `test_redis_failure.py` — kill local Redis, buffer fills, restart, drains < 10s, no loss within cap.
- `test_load.py` — 5 k RPS for 30 min. Assert no buffer overflow, p95 lag < 1s throughout.

### Independent demo script: `scripts/solo-demo.sh`
Reproducible, idempotent, runs without teammates' code. Whole demo runs in ~3 minutes. Teammates can watch pre-merge for confidence.

### Proof artifacts (commit to repo, show in writeup)
- `tests/chaos/results/convergence_*.txt` — historical convergence times
- `tests/chaos/results/load_5krps_30min.txt` — sustained-load proof
- `docs/sync-design.md` — design writeup with diagrams
- `docs/failure-modes.md` — F1-F7 table from §7
- `scripts/solo-demo.sh`
- Make targets: `make test`, `make test-chaos`, `make demo-sync`, `make convergence-proof`

### CI setup (`.github/workflows/sync-ci.yml`)
- On every PR touching `sync/`: Layer 1 + 2 + 3 (fast, ~2 min total).
- Nightly cron: Layer 4 (auto-commit results).
- Coverage gate: ≥85% line coverage on `sync/` package.

### Independence guarantee
| Need from teammate | Why not blocking |
|---|---|
| Nikhil's gateway | Replaced by 50-LOC `gateway-stub` for dev + tests + solo demo |
| Prathamesh's simulator | Same — `gateway-stub` covers traffic generation |
| Atharv's agent | Sync doesn't read policy/override — agent is downstream consumer |
| Prometheus/Grafana | `/metrics` scrapeable by curl; raw counts assertable in tests |
| Day-0 contract sign-off | Run with stub until ratified; swap mechanically |

Sync service ships to "done + tested + demo-rehearsed" by Day 7 even if other components slip.

---

## 11. Cross-team contract changes (Day 0 sign-off required)

### Contract addendum 1 — Gateway dirty signal (Nikhil)
After every successful Lua call (allow path), gateway publishes:
```
PUBLISH dirty:{region} "{tier}:{user_id}"
```
Payload is plain string `"{tier}:{user_id}"`. ~5 line Go change. Local Redis only.

### Contract 2 reframe — Counter slot semantics (Nikhil)
`rl:local:{region}:{tier}:{user_id}` is a monotonic request-allowed-count integer. Gateway INCRs on allow. Token-bucket internal state (tokens-remaining, last-refill-ts) lives under separate Redis keys owned by gateway and is NOT replicated.

### Out of scope for sync — Override replication (Atharv)
`override:{user_id}` writes are NOT replicated by sync service. Agent must write to all 3 region Redises directly, or use a shared single-instance policy Redis. Decided by Atharv + Nikhil.

---

## 12. Tech stack & repo layout

- Python 3.11
- redis-py async (`redis>=5.0`) with `health_check_interval=15`, `socket_keepalive=True`
- asyncio, pydantic, FastAPI, uvicorn, click, prometheus-client
- pytest, pytest-asyncio, testcontainers, toxiproxy (chaos)
- Redis 7+ (vanilla, 3 containers, ports 6379/6380/6381 named redis-us/eu/asia)
- docker-compose for local cluster
- Lifted code attributed in headers: `python3-crdt` (MIT), `grow-counter-crdt` (Apache)

```
sync/
  crdt.py
  counter.py
  transport.py
  coalescer.py
  reconciler.py
  buffer.py
  admin.py
  service.py
  __main__.py
  dev/
    gateway_stub.py        # solo-demo harness
    sync_cli.py            # CLI inspector
  tests/
    unit/
    integration/
    e2e/
    chaos/
infra/
  docker-compose.yml             # full system (with teammates)
  docker-compose.sync-only.yml   # standalone for solo demo
docs/
  sync-design.md          # Yashashav writeup
  failure-modes.md        # F1-F7 table
scripts/
  solo-demo.sh
Makefile
pyproject.toml
.github/workflows/sync-ci.yml
```

---

## 13. Writeup outline (Days 11-12)

Title: *Consistency vs availability: a CRDT approach to geo-distributed counters.*

| § | Section | Words |
|---|---|---|
| 1 | Problem framing (rate limiting + multi-region) | 200 |
| 2 | CAP positioning + why AP | 250 |
| 3 | G-Counter CRDT design (with diagram) | 300 |
| 4 | Coalescing + reconcile (latency-vs-accuracy knob, with chart) | 300 |
| 5 | Partition tolerance proof + convergence test | 250 |
| 6 | Failure mode table | 150 |
| 7 | Limitations + future work (Streams, true global enforcement) | 200 |
| Total | | ~1650 |

Most content already drafted in this spec — rephrase for prose.

---

## 14. Build timeline (mapped to PDF days)

| Day | Deliverable |
|---|---|
| D1 | docker-compose 3 Redis up. `sync/` Python project initialized. Standalone `make demo-sync` skeleton (just brings up containers). |
| D2 | `RegionalCounter` complete with unit tests. `SyncService` stub. `crdt.py` complete with tests. `gateway-stub` working. |
| D3 | `transport.py` complete. `coalescer.py` complete. `publish_delta` + `subscribe` working between sync-us and sync-eu. End-to-end propagation test green. `docs/sync-design.md` v1. |
| D4 | `reconciler.py` complete. Wired into gateway flow (via stub). `rl_sync_lag_seconds` metric live. All Layer 2 tests green. |
| D5 | `admin.py` complete. `/admin/partition` + `/admin/heal` working. Partition writeup section. Layer 3 e2e tests green. |
| D6 | Team integration day. Swap `gateway-stub` for Nikhil's real gateway. Verify all flows still work. |
| D7 | `buffer.py` complete (degraded mode for D9 chaos). Convergence test green. |
| D8 | Chunked reconcile. `rl_global_counter_drift` metric. Layer 4 chaos tests green. Convergence proof committed. |
| D9 | Failure-mode drills with whole team. `docs/failure-modes.md` complete. |
| D10 | Demo dress rehearsal. `scripts/solo-demo.sh` polished. |
| D11-12 | Writeup. |
| D13-14 | Slides + dry runs + submit. |

Sync service is feature-complete by D8 with two days of buffer before integration freeze.
