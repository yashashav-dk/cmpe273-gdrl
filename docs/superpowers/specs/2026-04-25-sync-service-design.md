# Sync Service Design Spec

**Project codename:** `gdrl` (placeholder — final name TBD Day 7)
**Project:** CMPE 273 — Geo-distributed AI-driven rate limiter
**Owner:** Yashashav
**Component:** Distributed counter store + cross-region sync service (`gdrl/sync`)
**Date:** 2026-04-25
**Status:** Approved (brainstorm). Amended 2026-04-28 to track merged gateway behavior — see Constitution Appendix C, Amendment 1. Sections §4, §5, §6, §10, §11, §14 carry the changes.

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
┌─────────────────── REGION us ───────────────────┐  ┌─── REGION eu ──┐  ┌─── REGION asia ──┐
│                                                  │  │                │  │                  │
│  gateway-us (Go)                                 │  │  gateway-eu    │  │  gateway-asia    │
│   ├─ INCR rl:local:us:{tier}:{user}              │  │  (mirror)      │  │  (mirror)        │
│   ├─ HIncrBy rl:global:{tier}:{user}:{w} us 1    │  │                │  │                  │
│   ├─ HGetAll rl:global:{tier}:{user}:{w}  ◀ sum  │  │                │  │                  │
│   └─ PUBLISH rl:sync:counter {Contract-2 JSON}   │  │                │  │                  │
│         │                                         │  │                │  │                  │
│         ▼                                         │  │                │  │                  │
│  ┌─────────────┐                                  │  │  ┌──────────┐  │  │  ┌────────────┐  │
│  │  redis-us   │                                  │  │  │ redis-eu │  │  │  │ redis-asia │  │
│  │  :6379      │                                  │  │  │  :6380   │  │  │  │  :6381     │  │
│  └─────┬───────┘                                  │  │  └────┬─────┘  │  │  └─────┬──────┘  │
│        │ SUB rl:sync:counter (local + 2 peers)    │  │       │        │  │        │         │
│        ▼                                          │  │       │        │  │        │         │
│  ┌────────────────────────────────────────────┐   │  │  ┌────▼─────┐  │  │  ┌─────▼──────┐  │
│  │   sync-us  (Python)                        │   │  │  │ sync-eu  │  │  │  │ sync-asia  │  │
│  │   ── relay (subscribe → max-merge peer)    │◀──┼──┼──│          │──┼──┼──│            │  │
│  │   ── reconciler (30s broadcast own slots)  │   │  │  │          │  │  │  │            │  │
│  │   ── /admin (FastAPI)                      │   │  │  │          │  │  │  │            │  │
│  │   ── failover buffer + watchdog            │   │  │  │          │  │  │  │            │  │
│  └────────────────────────────────────────────┘   │  │  └──────────┘  │  │  └────────────┘  │
│         │ HSET rl:global:..:{w} {peer} {value}    │  │                │  │                  │
│         ▼ (only peer slots; never own)            │  │                │  │                  │
│      back to redis-us                             │  │                │  │                  │
└──────────────────────────────────────────────────┘  └────────────────┘  └──────────────────┘
```

### Process boundary
- One Python container per region. Identical image, differs by `--region`, `--local-redis-url`, `--peer-redis-urls`.
- Stateless across restarts. All persistent state in Redis. Restart = catch up via reconcile.
- Single asyncio event loop per process. Tasks: peer-subscribers (×3, including local), reconciler, FastAPI server, watchdog.

### Network topology
- Each sync subscribes to **all three** Redis instances on `rl:sync:counter` (3 connections per sync = 9 cross-region subscribes total). Local-Redis subscription is included so partition simulation can drop self-origin slots if needed.
- Each sync publishes only to its **local** Redis `rl:sync:counter` channel — and only `kind=reconcile` envelopes. Gateway publishes `kind=counter` (Contract 2) on its local Redis directly.
- Cross-region delivery happens via subscribers reaching peer Redises directly. No Redis cluster mode. No Redis-side replication.

### Why this shape
- One process per region matches geo-distributed framing in the writeup. Crash of `sync-us` doesn't affect EU/Asia.
- Subscribing across regions (vs Redis-side replication) keeps Redis stock vanilla and makes partition simulation trivial (subscriber filters by `from_region`).
- All state in Redis means no in-process cache to invalidate on restart. Reconcile is the universal recovery mechanism.

### Sync role: cross-region max-merge relay + observability
Gateway enforces locally. It writes its own region's slot in `rl:global:{tier}:{user}:{w}` and reads the local hash for global aggregate enforcement — both are local Redis I/O. Sync makes the gateway's local read globally-coherent by max-merging peer slots (received over `rl:sync:counter` from peer Redises) into the local hash. Sync does NOT write its own region's slot; the gateway already did that. Single-writer-per-slot is preserved by construction. Agent consumes the same hash via Prometheus metrics.

---

## 3. CRDT model

**G-Counter, state-based, max-merge per slot.**

### Data shape
- Per (tier, user_id, window_id), each region maintains a monotonic-within-window count of requests allowed locally.
- Global state = a vector of per-region counts, stored as a Redis hash, segmented by `window_id` (= `floor(unix_ts/60)`):
  ```
  HSET rl:global:free:u_123:29620586 us 47 eu 42 asia 1
  ```
- Global value = sum of all slots in that window.
- Merge rule: `slot[r] = max(local_slot[r], incoming_slot[r])` for each region r. Idempotent, commutative, associative.
- Reset semantics: rollover happens by writing a new key (next `window_id`); the old key TTLs out. No in-place reset.

### Why G-Counter
- Conflict-free: only one writer per slot (each region writes its own slot). Impossible to disagree.
- Eventually consistent under any message ordering or duplication.
- Tolerates message loss (max-merge is idempotent — replay is safe).
- Tolerates clock skew (no timestamps for ordering).

### Hard invariant
**Within a window, local slot counts only increase.** Never decrement, never in-place reset. Window rollover (next `window_id` → new key) is the only path back to zero, and it goes through Redis TTL on the old key, not via mutation. Token-bucket "refill" semantics are gateway-private state on separate keys, not replicated. Sync-replicated counter is the request-allowed-count returned by the gateway's HIncrBy — never tokens-remaining.

If this invariant is violated, max-merge will resurrect old values across regions. Enforced at the `RegionalCounter` API: `apply_remote_slot` rejects writes to own region's slot and rejects values lower than the current slot value (Lua-atomic).

### Reference implementations
- `python3-crdt` (anshulahuja98, MIT, ~150 LOC G-Counter class) — lifting the data-structure code with attribution.
- `grow-counter-crdt` (sultaniman, Apache, ~100 LOC pub/sub transport pattern) — lifting the broadcast pattern with attribution.
- `akka-distributed-data` GCounter.scala — algorithm reference for correctness sanity check.

---

## 4. Wire envelope (cross-region channel `rl:sync:counter`)

Two envelope kinds share the same channel.

### 4a. `kind=counter` — gateway-emitted, one per allowed request (Contract 2 verbatim)

```json
{
  "tier":      "free",
  "user_id":   "u_123",
  "window_id": 29620586,
  "region":    "us",
  "value":     47,
  "ts_ms":     1714060800123
}
```

- Emitted by gateway after a successful `HIncrBy rl:global:{tier}:{user_id}:{window_id} {region} 1`.
- `value` is the absolute slot count returned by `HIncrBy` (not a delta).
- Receivers (the other two regions' sync services) max-merge `value` into their own local `rl:global:{tier}:{user_id}:{window_id}` hash on field `region`.
- `ts_ms` populates `rl_sync_lag_seconds`.
- This shape is fixed by Contract 2; sync does not get to change it.

### 4b. `kind=reconcile` — sync-emitted, every 30s, chunked

Distinguished from `kind=counter` by the presence of a top-level `"kind"` field. Counter envelopes have no `"kind"` field (Contract 2 lock).

```json
{
  "kind":     "reconcile",
  "v":        1,
  "origin":   "us",
  "ts_ms":    1714060800123,
  "window_id": 29620586,
  "slots": {
    "free:u_123":      47,
    "premium:u_456":   1203
  }
}
```

- One reconcile message covers one window for the origin region only. `slots` map values are the origin's own slot count for that (tier, user_id) at that window.
- Chunked at 1000 entries per message.
- Receivers max-merge each entry into local `rl:global:{tier}:{user_id}:{window_id}` field `origin`. Idempotent — replay-safe.

### Bandwidth math
Steady state, 1k req/s/region, ~100 active users/region:
- Counter envelopes: 1k publish/s × ~120 bytes = ~120 KB/sec per region. Cross-region ingress per sync: 240 KB/sec from two peers. Comfortably below pub/sub 32 MB output buffer cap.
- Reconcile every 30 s, 10 k keys × ~30 bytes packed = 300 KB/window chunked into 10 × 30 KB messages. ~0.3 msg/sec aggregate. Trivial.

At 5k req/s sustained the counter-channel rate scales linearly. If buffer pressure shows up, the back-pressure response is Contract 2 — gateway can sample (e.g. publish only every Nth allowed request) — not sync coalescing. Sync remains a stateless relay.

---

## 5. Components

9 modules. Each ≤ 150 LOC. Single-purpose, isolated, independently testable. Coalescer is gone (§4 explains: gateway publishes one envelope per allowed request, so sync has no batching to do); replaced by `relay.py`.

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
Owns Contract 2 key schema. Sync writes peer slots only; gateway writes own slot (Contract 2).
```python
class RegionalCounter:
    def __init__(self, region: str, redis: Redis): ...
    async def get_global(self, tier: str, user_id: str, window_id: int) -> dict[str,int]
        # HGETALL rl:global:{tier}:{user_id}:{window_id}
    async def get_own_slot(self, tier: str, user_id: str, window_id: int) -> int
        # HGET ... region — used by reconciler to read what gateway last wrote
    async def apply_remote_slot(self, tier, user_id, window_id, peer_region, value) -> bool
        # Atomic max-merge via Lua. Returns True if value was applied.
        # MUST refuse if peer_region == self.region (constitution III §6).
    async def scan_window_keys(self, window_id: int) -> AsyncIterator[tuple[str,str]]
        # SCAN MATCH rl:global:*:*:{window_id} → yield (tier, user_id)
```
Atomic max-merge Lua (`max_merge.lua`):
```lua
local cur = redis.call('HGET', KEYS[1], ARGV[1])
if (not cur) or (tonumber(cur) < tonumber(ARGV[2])) then
  redis.call('HSET', KEYS[1], ARGV[1], ARGV[2])
  redis.call('EXPIRE', KEYS[1], 300)
  return 1
end
return 0
```
TTL refresh on every merge keeps the window key alive across the (window + grace) period.

### `sync/transport.py` — Pub/sub publish + subscribe (~100 LOC)
Wraps redis-py async PubSub. Reconnection, health checks. Channel is `rl:sync:counter` for both kinds.
```python
class Transport:
    def __init__(self, local_redis, peer_redises: dict[str,Redis]): ...
    async def publish_local(self, payload: bytes) -> None        # for reconcile envelopes
    async def subscribe_peers(self) -> AsyncIterator[tuple[str,bytes]]
        # yields (origin_region, raw_envelope) from all 3 Redises (incl. local — relay drops self-origin counter envelopes)
```
Settings: `health_check_interval=15`, `socket_keepalive=True`. Auto-reconnect with exponential backoff (1s → 2s → 4s → max 30s). Re-subscribe on reconnect.

### `sync/relay.py` — Receive → parse → max-merge (~80 LOC)
The hot loop on the sync side. Replaces the old `coalescer.py`.
```python
class Relay:
    def __init__(self, region, counter, transport, partition_table, metrics, buffer): ...
    async def run(self) -> None
        # async for (origin, raw) in transport.subscribe_peers():
        #     env = parse_envelope(raw)
        #     if partition_table.blocks(origin, self.region): drop, metric, continue
        #     if env.kind == "counter":
        #         if env.region == self.region: continue  # gateway already wrote own slot locally
        #         await counter.apply_remote_slot(env.tier, env.user_id, env.window_id, env.region, env.value)
        #     elif env.kind == "reconcile":
        #         for (tier, user_id), value in env.slots.items():
        #             await counter.apply_remote_slot(tier, user_id, env.window_id, env.origin, value)
        #     metrics.observe_lag(now - env.ts_ms, from=origin, to=self.region)
```
Stateless (no dirty set, no batching). Backpressure handling: if `apply_remote_slot` raises (local Redis dead), envelope goes to `FailoverBuffer`; relay continues consuming so subscriber doesn't fall behind.

### `sync/reconciler.py` — 30s full-window max-merge broadcast (~100 LOC)
```python
class Reconciler:
    def __init__(self, region, counter, transport, period_s: int = 30): ...
    async def run(self) -> None
    async def reconcile_once(self) -> ReconcileStats
        # for window_id in {current, current-1}:
        #   scan rl:global:*:*:{window_id}
        #   for each key, HGET own slot → accumulate (tier, user_id, value)
        #   chunk 1000 entries → build envelope kind=reconcile, publish on rl:sync:counter
```
Runs immediately on startup (cold-start catch-up), then every 30s. Two windows scanned because messages near a minute boundary may have been mis-bucketed by skewed clocks; the older window is cheap insurance.

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
POST /admin/config {reconcile_period_s} → hot-reload reconcile period
GET  /metrics                         → Prometheus scrape
```

### `sync/service.py` — Orchestrator + entrypoint (~100 LOC)
asyncio main. Wires everything. CLI flags.
```python
async def main(region, local_redis_url, peer_redis_urls, reconcile_period_s): ...
```
Tasks under one `asyncio.gather` with cancellation on signal.

### Module dependency graph
```
service.py ─┬─▶ relay.py ──┬─▶ counter.py ─▶ crdt.py
            │              ├─▶ transport.py
            │              ├─▶ buffer.py
            │              └─▶ partition_table.py
            ├─▶ reconciler.py ─▶ counter.py
            │                  └─▶ transport.py
            └─▶ admin.py ─▶ (refs to relay, counter, transport, partition_table)
```
No circular deps. crdt.py is leaf, testable in isolation. partition_table is a small (~30 LOC) shared module holding the `set[(from, to)]` partition rules; relay reads, admin writes.

### Total LOC
~740 LOC application + ~250 LOC tests + ~60 LOC `gateway-stub` dev harness. Net −40 LOC vs. pre-amendment design (coalescer −120, relay +80). Within budget for 4-5 effective build days.

---

## 6. Data flow

### Flow 1 — Hot path: gateway request → local + global update
All steps below execute against `redis-us` (local). No cross-region call.
```
1. Client → POST /check {user_id:u_123, tier:free, region:us, endpoint:/api/v1/foo}
2. gateway-us Lua: token bucket check on rl:local:us:free:u_123 → allow.
3. gateway-us: INCR rl:local:us:free:u_123  EX (window+60)
4. gateway-us: HIncrBy rl:global:free:u_123:{window_id} us 1  → newSlot
5. gateway-us: HGetAll rl:global:free:u_123:{window_id}  → sum, compare to GlobalLimit
6. gateway-us: Publish rl:sync:counter {tier, user_id, window_id, region:us, value:newSlot, ts_ms}
7. gateway-us → client: {allowed, remaining, limit, retry_after_ms, policy_id}
```
Sync coupling adds one local Redis Publish (~0.1 ms). Fire-and-forget.

### Flow 2 — Sync relay: peer envelope → local hash merge
```
1. sync-us subscribes to rl:sync:counter on redis-us, redis-eu, redis-asia.
2. Envelope arrives from redis-eu (origin=eu).
3. Relay: partition_table.blocks(eu, us)? if yes → drop, metric, continue.
4. Relay: env.region == self.region? if yes → drop (counter envelope from own gateway,
   redundant; sync never writes own slot). For reconcile envelopes, env.origin == self
   is similarly skipped.
5. counter.apply_remote_slot(tier, user_id, window_id, peer_region=eu, value)
   → Lua atomically HSETs the slot if value > current. EXPIRE refreshed.
6. metrics: rl_sync_messages_total{kind=counter, origin=eu, dest=us}.inc();
            rl_sync_lag_seconds{from=eu, to=us}.observe(now_ms - env.ts_ms).
```
Stateless. No batching. One pub/sub message → one max-merge.

### Flow 3 — Reconcile: 30 s broadcast of own region's slots
```
Every 30 s in each sync-X:
1. reconciler.reconcile_once():
   a. for window_id in {now/60, now/60 - 1}:
        SCAN MATCH rl:global:*:*:{window_id} on local Redis
        for each key: parse (tier, user_id); HGET field={region} → value
        accumulate into chunks of 1000 entries
   b. for each chunk: publish kind=reconcile envelope on local rl:sync:counter
2. Receivers (Flow 2 above) process reconcile envelopes via max-merge — idempotent.
3. metric: rl_reconcile_duration_seconds.observe(elapsed); keys_processed counter.
```
Note: sync does NOT write its own slot anywhere in this flow. It only publishes what the gateway already HIncrBy'd, so peer regions can max-merge.

### Flow 4 — Partition simulation
```
Operator: POST /admin/partition {"from":"us","to":"eu"}
1. admin handler: partition_table.add(("us","eu"))
2. relay on sync-eu receives envelope from redis-us with origin=us:
     partition_table.blocks(us, eu) → True → drop, increment rl_messages_dropped_total.
3. After Nseconds: POST /admin/heal {"from":"us","to":"eu"}
4. partition_table.remove(("us","eu"))
5. Next reconcile (≤30s) on sync-us → broadcasts current window slots →
   sync-eu max-merges → drift collapses.
```
Asymmetric drops supported (partition us→eu without affecting eu→us).

### Flow 5 — Degraded mode: local Redis dies
```
1. counter.apply_remote_slot raises ConnectionError.
2. relay pushes (tier, user_id, window_id, peer_region, value) into FailoverBuffer
   tagged kind=relay_apply.
3. relay logs, increments rl_sync_buffer_size{kind=relay_apply}.
4. transport.publish_local (reconcile) fails → buffer push for kind=reconcile_publish.
5. watchdog (1s tick) PINGs local Redis.
6. on success: drain FIFO, retry each entry. apply_remote_slot is idempotent.
7. /health returns 503 while local Redis is down. Returns 200 once buffer is drained.
```
Buffer cap 10 k per kind. Overflow drops oldest with metric. Reconcile from peers fills any actually-lost data on recovery.

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
rl_relay_inflight{region}                                   gauge   (currently-processing peer envelopes)
rl_sync_buffer_size{region, kind}                           gauge
rl_sync_buffer_overflow_total{region, kind}                 counter
rl_local_redis_up{region}                                   gauge (0/1)
rl_peer_connection_up{from_region, to_region}               gauge (0/1)
rl_peer_reconnect_total{from_region, to_region}             counter
rl_subscriber_disconnects_total{from_region}                counter
rl_reconcile_duration_seconds                               histogram
rl_reconcile_keys_processed{region}                         counter
rl_partition_active{from_region, to_region}                 gauge (0/1)
rl_reconcile_period_s{region}                               gauge
rl_global_counter_drift{tier, user_id}                      gauge (sampled top-100 active)
```

`rl_global_counter_drift` = `max(slot) − min(slot)` across regions per key. Spikes during partition, collapses after heal. Demo signal.

---

## 9. Demo plan

### Standalone runtime: `make demo-sync`
Single command brings up only what sync needs: 3 Redis + 3 sync containers + `gateway-stub` (~60-LOC Python harness emitting Contract-2 envelopes on `rl:sync:counter` after a fake `HIncrBy` on local Redis — mimics Nikhil's gateway exactly at the sync surface). No teammate code required.

When Nikhil's real gateway lands, swap `gateway-stub` for `gateway-us` in compose file. Zero sync code changes.

### Demo arc — 4 minutes of Yashashav-narrated content
1. **Steady state (45s).** Grafana sync-lag p95 < 200ms across regions. Drift near zero.
2. **Crank the knob (30s).** `POST /admin/config reconcile_period_s=300` → drift after a partition heals in ~5min instead of 30s. Crank back to 10s → next heal converges instantly. Demonstrates that reconcile is the correctness floor (counter pub/sub still flows in real time; reconcile only matters for messages dropped during partition).
3. **Partition (75s).** `POST /admin/partition us eu` + spike traffic on US for 30s. Counts diverge visibly. `POST /admin/heal` → drift collapses < 5s. Show `GET /admin/state?user_id=X` from both syncs side-by-side.
4. **Local Redis dies (45s).** `docker stop redis-eu`, run traffic, watch `rl_sync_buffer_size{region=eu}` climb. `docker start redis-eu` → buffer drains to 0.
5. **Convergence test result (45s).** `pytest tests/chaos/test_convergence.py -v` → "Partition 60s, 1247 events, converged in 3.2s ✓"

### Demo aids
- `GET /admin/state?user_id=X` returns `{tier, user_id, local_count, global_view, drift, stale_seconds}` — narration anchor.
- `sync-cli` (~50 LOC click app):
  - `sync-cli inspect <user_id>` — calls all 3 `/admin/state`, side-by-side table
  - `sync-cli partition us eu`
  - `sync-cli heal`
  - `sync-cli config us --reconcile-period 300`

### Grafana panels (built by Prathamesh, spec'd by us)
```
Row 1 — Sync health
  A: rl_sync_lag_seconds p50/p95/p99 by from→to
  B: rl_sync_messages_total rate by origin
  C: rl_local_redis_up + rl_peer_connection_up status grid

Row 2 — Throughput + knobs
  D: messages/sec on rl:sync:counter by kind (counter vs reconcile)
  E: rl_reconcile_period_s (single stat — DEMO KNOB INDICATOR)
  F: rl_sync_messages_total rate (counter kind) — confirms gateway publish rate

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
- `test_envelope.py` — both kinds (counter Contract-2 shape, reconcile shape) roundtrip; reject malformed; reject unknown version on reconcile
- `test_buffer.py` — FIFO drain, overflow drops oldest, size metric
- `test_partition_table.py` — direction blocking, asymmetric, heal clears

### Layer 2 — Integration (real Redis via testcontainers) — `tests/integration/`
- `test_counter_redis.py` — max-merge Lua atomic; idempotent replay; refuses to write own region's slot (constitution III §6); window-id scan returns only matching window; TTL refreshed on each merge
- `test_transport_pubsub.py` — peer subscriber yields (origin, raw) from all 3 Redises; reconnect resubscribes; health check detects dead connection (toxiproxy fixture)
- `test_relay.py` — counter envelope from peer applies; counter envelope where region == self drops; reconcile envelope applies all slots; partition rule blocks; lag metric observed; local-Redis-down path goes to buffer

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

## 11. Cross-team contract status

As of Amendment 1 (2026-04-28), the cross-team contracts are codified in `docs/contracts.md` and the sync service consumes them as-is. No new sign-off required.

### Contract 2 — sync's read/write surface
- **Reads from local Redis** on hot path of relay loop:
  - Subscribes `rl:sync:counter` on all 3 Redis instances
  - HGET on local `rl:global:{tier}:{user_id}:{window_id}` (reconciler scan)
- **Writes to local Redis only**:
  - HSET (via Lua max-merge) on `rl:global:{tier}:{user_id}:{window_id}` field={peer_region}
  - PUBLISH `rl:sync:counter` (kind=reconcile envelopes only)
- **Never writes**: own region's slot in `rl:global:*` (gateway exclusive); `rl:local:*` (gateway exclusive); `policy:*` / `override:*` (agent exclusive).

### Out of scope for sync (unchanged)
- `override:{user_id}` and `policy:*` replication. Atharv's agent writes directly to all 3 region Redises.
- Token-bucket refill internals (gateway-private keys; not replicated).
- Cross-region transport for anything other than counter slot replication.

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
  relay.py
  reconciler.py
  buffer.py
  partition_table.py
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

## 14. Build timeline (compressed; mapped to PDF days)

The project started 2026-04-26 (PDF Day 1). The other three components shipped through Days 1–8 in parallel; sync was deferred. Day 5 (2026-04-30) is the start of sync's effective build window. The original D1–D8 plan compresses into D5–D8 below. Total feature-complete budget: 4 working days for ~740 LOC + 4 test layers + harness. Each day = one PR, gated on tests + spec compliance + Constitution Art V quality gates.

| PDF day | Date | Deliverable |
|---|---|---|
| D5 | 2026-04-30 | **Foundation + handover docs.** `crdt.py`, `counter.py` (with own-slot-write refusal Lua), `pyproject.toml`, `requirements.txt`, `infra/docker-compose.sync-only.yml`, `Makefile`. Layer 1 unit tests for crdt + envelope. Layer 2 integration test for counter (Lua atomic, refuses own slot, window scan, TTL refresh). `AGENTS.md` + `sync/CONTEXT.md` + module docstrings on `crdt.py`, `counter.py`. **Gate:** Layer 1 + counter integration green. |
| D6 | 2026-05-01 | **Transport + harness.** `transport.py` (peer subscriber, reconnect backoff, health check). `sync/dev/gateway_stub.py` (Contract-2 envelope emitter). `sync/dev/sync_cli.py` (inspect/partition/heal/config). Layer 2 test for transport (peer-yield, reconnect-resub, toxiproxy disconnect detection). Module docstring on `transport.py`. **Gate:** Layer 2 transport green; stub publishes to all 3 Redis. |
| D7 | 2026-05-02 | **Relay + reconciler.** `partition_table.py`, `relay.py`, `reconciler.py`. Layer 1 partition_table test. Layer 2 relay test (counter applies, self-origin drops, reconcile applies, partition blocks, lag observed). Layer 3 e2e basic propagation test (3-region cluster, US publish visible in EU+Asia within 2s). Module docstrings on `relay.py`, `reconciler.py`, `partition_table.py`. **Gate:** Layer 3 propagation green. |
| D8 | 2026-05-03 | **Robustness + admin + chaos proof.** `buffer.py`, `admin.py`, `service.py`. Layer 1 buffer test. Layer 3 partition+heal test (asymmetric, drift collapses < 5s). Layer 4 convergence proof (60s partition + heal → assert convergence < 5s; result committed under `tests/chaos/results/`). Layer 4 redis-failure test. Module docstrings on `buffer.py`, `admin.py`, `service.py`. `scripts/solo-demo.sh`. **Gate:** all 4 layers green; convergence proof committed; sync **feature-complete**. |
| D9 | 2026-05-04 | Layer 4 load test (5k RPS for 30 min). `docs/failure-modes.md` (F1–F7 executed). Team integration: swap `gateway-stub` for Nikhil's `gateway-us`. **Gate:** PDF Day 9 deliverable signed off. |
| D10 | 2026-05-05 | Dress rehearsal. `scripts/solo-demo.sh` polished. `docs/sync-design.md` writeup ≥1500 words. **Gate:** Constitution Art IX termination conditions satisfied. |
| D11–12 | 2026-05-06 → 07 | Writeup polish, second teammate review pass. |
| D13–14 | 2026-05-08 → 09 | Slides + dry runs + submit. |

### LOC budget tracking
| Day | Module | LOC | Cumulative |
|---|---|---|---|
| D5 | crdt + counter | 220 | 220 |
| D6 | transport | 100 | 320 |
| D7 | relay + reconciler + partition_table | 210 | 530 |
| D8 | buffer + admin + service | 260 | 790 |

Within ±10% of the 740 LOC application budget. Tests +250 LOC, harness +60 LOC.

### Compression risk and mitigation
The original spec budgeted 8 build days (D1–D8); we have 4 (D5–D8). Mitigation:
1. The CRDT primitive (`crdt.py`) is lifted from `python3-crdt` (MIT) — not built from scratch. Saves ~1 day.
2. Coalescer is gone (Amendment 1) — saves another ~0.5 day.
3. Constitution Art VIII §3 (failing test before fix) is non-negotiable; we do not compress by skipping tests. We compress by parallelizing test-writing with code-writing within each day's PR, not across days.
4. If D7 slips, D8 absorbs by deferring the load test (Layer 4 `test_load.py`) into D9. Convergence proof is the load-bearing PDF deliverable; the load test is a nice-to-have.

---

## 15. Handover artifacts (LLM-aware + human-readable)

A cold reader — fresh LLM session, new teammate, post-mortem six months from now — should be productive in five minutes. Three artifacts, total ~250 lines of prose, no standing maintenance burden.

### 15.1 `AGENTS.md` (repo root, ~80 lines)

Single navigation file at the repo root. Picked up automatically by LLM tools that honor the AGENTS.md convention (Claude Code, Cursor, Codex, etc.). Read first by any LLM dropped into the repo.

Required content:
- **Layout.** One line per top-level dir, naming owner and one-sentence purpose.
- **Before touching `<component>/` read.** Pointer list to docs/contracts.md plus per-component constitution and latest design spec.
- **Cross-team rules.** The four "do not break this" invariants:
  1. Gateway is the only writer of `rl:local:*` and own-region slot of `rl:global:*:{w}`.
  2. Sync is the only writer of peer-region slots in `rl:global:*:{w}`.
  3. Agent is the only writer of `policy:*` and `override:*`.
  4. No cross-region call on a request hot path. Ever.
- **Routing rule.** If working in `sync/`, also read `sync/CONTEXT.md` next.

Maintenance: update only when team boundaries change (rare).

### 15.2 `sync/CONTEXT.md` (~120 lines)

Sync-internal primer. Loaded by anyone working inside `sync/`.

Sections (mandatory):
- **§1 Mission** — five-line paraphrase of constitution Art I. "Make the agent possible by giving it a globally-coherent counter view."
- **§2 Load-bearing invariants** — quoted verbatim from constitution (single-writer-per-slot, monotonic-within-window, no cross-region call on hot path, stateless processes). Prose paraphrase invites drift; quote is durable.
- **§3 Module map** — one sentence per module with a `→ spec §5.<n>` pointer. Plus the dep graph from spec §5.
- **§4 Common pitfalls** — what a fresh LLM tends to do wrong here:
  - Decrementing slots (NEVER — see Constitution Art II §3).
  - Sync writing own region's slot (NEVER — gateway already did via Contract 2; sync's `apply_remote_slot` rejects this).
  - Coalescing or batching (NEVER — gateway emits per-request; sync relays one-for-one).
  - Subscribing only to peer Redises (DO subscribe to all 3 incl. local, then drop self-origin counter envelopes in relay; this keeps partition simulation symmetric).
  - Reading peer Redis from anywhere outside `sync/` (NEVER — sync's relay is the only path).
- **§5 Pointers** — one-line summary each:
  - `docs/sync-constitution.md` — non-negotiable rules.
  - `docs/superpowers/specs/2026-04-25-sync-service-design.md` — this design (canonical).
  - `docs/contracts.md` — the four cross-team contracts.
  - `AGENTS.md` — repo-wide LLM router.
- **§6 Test-first reminder** — for the change you're making, which test layer comes first?
  - Pure logic (CRDT, envelope, partition table, buffer) → Layer 1 unit.
  - Anything touching Redis (counter Lua, transport pubsub, reconciler scan) → Layer 2 integration.
  - Cross-region behavior (propagation, partition, drift) → Layer 3 e2e.
  - Convergence guarantees, redis-down recovery, sustained load → Layer 4 chaos.

Maintenance: update §1 only on constitutional amendment; §3/§5 on module rename/spec rename; §4 grows as new pitfalls are discovered (a discovered pitfall = a fresh LLM made a mistake we want to prevent next time).

### 15.3 Per-module docstring header (~6 lines × 9 modules ≈ 55 lines)

Lives at the top of each `sync/*.py`. Cheapest, longest-lived form of handover — lives next to the code it describes; rot is forced visible at PR review.

Template (apply to every module):
```python
"""
sync/<module>.py — <one-sentence purpose>.

Spec:        docs/superpowers/specs/2026-04-25-sync-service-design.md §5 <module>, §6 Flow <n>
Constitution: docs/sync-constitution.md Art <n> §<n> (relevant invariants)
Reads:       <Redis keys / channels read>
Writes:      <Redis keys / channels written, plus what the module is forbidden from writing>
Don't:       <2–3 most likely fresh-LLM mistakes for this module>
"""
```

Worked example (`relay.py`):
```python
"""
sync/relay.py — peer envelope receiver + max-merge applicator.

Spec:        docs/superpowers/specs/2026-04-25-sync-service-design.md §5 relay.py, §6 Flow 2
Constitution: docs/sync-constitution.md Art III §3 (transport), Art III §6 (single-writer)
Reads:       rl:sync:counter on local + 2 peer Redises
Writes:      local rl:global:{tier}:{user_id}:{window_id} (peer slots only — never own region)
Don't:       coalesce, batch, write own region's slot, decrement.
"""
```

Maintenance: changes when the module is rewritten — same PR, same review. No standing burden.

### 15.4 What handover does NOT cover

- Implementation pseudocode lives in spec §5, not in handover docs. Don't duplicate.
- Test-writing patterns live in spec §10. Handover §6 is a routing pointer, not a tutorial.
- Architecture diagrams live in spec §2. Handover does not redraw.
- Constitutional rules live in `sync-constitution.md`. Handover quotes; does not paraphrase.

The rule: handover is a **router**, not a copy. Each line either points to canonical content elsewhere or describes a "don't" that no other doc captures.
