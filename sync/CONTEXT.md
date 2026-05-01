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
