# Sync Service Constitution

**Project codename:** `gdrl` (placeholder — final name TBD Day 7)
**Project:** CMPE 273 — Geo-distributed AI-driven rate limiter
**Component:** Distributed counter store + cross-region sync service (`gdrl/sync`)
**Owner:** Yashashav
**Ratified:** 2026-04-26
**Status:** Living document. Amendments require explicit reason + diff.

This document codifies the non-negotiable principles, invariants, and boundaries of the sync service. When in doubt during implementation, code review, or scope debate, this is the tiebreaker. Read it on day 1. Re-read it every Monday.

---

## Article I — Mission

The sync service exists to make the AI traffic-shaping agent possible. Its sole purpose is to give the agent a globally-coherent view of per-user request volume across three regions, with bounded staleness, no matter what fails. It does not enforce, it does not decide, it observes and replicates. Every line of code in this component must serve that mission or be deleted.

---

## Article II — Core Principles

### §1. Local enforcement, eventual replication
Gateways enforce on local Redis. Sync replicates eventually. Sync failure must never break a single request. If you find yourself making a sync call on the request hot path, you have made a mistake — back up.

### §2. AP, not CP
We choose availability and partition tolerance over consistency. Under partition, regions continue serving locally and may over-allow. They never under-allow. Over-allow is a recoverable accuracy bug; under-allow is a customer-facing outage. We always pick the recoverable failure mode.

### §3. Monotonic counters, forever
Every replicated counter slot is monotonically non-decreasing. There is no decrement, no reset, no backfill, no manual override. This is the load-bearing invariant of the entire system. Violating it resurrects stale state across regions and silently corrupts every downstream metric. The `RegionalCounter` API does not expose `set` or `decrement` and never will. If a future requirement seems to need decrement, the answer is a new key, not a violated invariant.

### §4. Idempotent everywhere
Every operation that crosses a process or network boundary must be safe to replay. Max-merge is idempotent by construction; we lean on this hard. Apply the same delta a thousand times — state is identical to applying once. Drop a message — next reconcile recovers it. Receive duplicates — no harm. Idempotence is what lets us use unreliable transport (pub/sub) without blocking the hot path.

### §5. Stateless processes, all state in Redis
Sync service processes hold no durable state. Restart at any moment must be safe. The dirty set, partition rules, and failover buffer live in process memory and are explicitly designed to be lost — reconcile rebuilds correctness within 30 seconds. If you find yourself wanting to persist Python state to disk, stop and reconsider; you've drifted from the design.

### §6. Fail open, never silent
Failures are loud. Every Redis disconnect, every dropped message, every buffer overflow emits a metric and a log line. Health endpoints reflect actual capability, not optimism. A `200 OK` from `/health` means the service is genuinely healthy, not "process is alive but pub/sub died 20 minutes ago and we never noticed."

### §7. Demo-first over feature-complete
A working end-to-end demo on day 5 beats three perfect components on day 10. Every feature is justified against a specific demo beat or writeup section. Anything that doesn't make the demo better, prove a tradeoff, or directly satisfy a PDF deliverable does not get built. YAGNI is not a guideline; it is enforced.

### §8. Independence is a feature
Sync ships standalone. It runs without Nikhil's gateway, without Prathamesh's simulator, without Atharv's agent, without Prometheus, without Grafana. The `gateway-stub` harness is a first-class artifact, not a development convenience. Anything that would block solo testing breaks this article.

### §9. Observability is correctness
A behavior that cannot be observed in metrics or logs is a behavior we cannot prove correct. Convergence is not a claim; it is a Prometheus query. Partition tolerance is not a paragraph; it is a `pytest` run. Every guarantee in the spec maps to a metric and a test.

---

## Article III — Architectural Invariants

The following statements must remain true across the lifetime of this codebase. Any change that violates one of them requires a constitutional amendment (this document) before code is written.

1. **One sync process per region.** Three identical containers. No leader, no coordinator, no shared state outside Redis.
2. **Sync subscribes to peer Redis instances directly.** No Redis cluster mode. No Redis-side replication. Stock vanilla Redis 7+.
3. **Cross-region transport is Redis pub/sub on `sync:deltas`.** Coalesced, max-merge G-Counter envelopes. The 30-second full-state reconcile is the correctness mechanism, not a fallback.
4. **The gateway → sync coupling is a single fire-and-forget `PUBLISH dirty:{region}` per allowed request.** Nothing more.
5. **`rl:local:{region}:{tier}:{user_id}` is owned by the gateway as writer; sync reads only.**
6. **`rl:global:{tier}:{user_id}` is owned by the sync service.** Each region writes only its own field. Max-merge on incoming.
7. **Policy and override replication are out of scope.** Sync replicates counters. Period.
8. **No request blocks on a network call to another region.** Ever.

---

## Article IV — Scope Boundaries

### In scope
Counter replication. Coalesced broadcast. Periodic reconcile. Partition simulation. Failover buffering. Admin endpoints. Sync-specific metrics. Sync-specific writeup.

### Out of scope
Rate-limit enforcement. Token bucket logic. Sliding window logic. Policy storage. Override storage. Override replication. Traffic generation. Prometheus deployment. Grafana dashboard layout. AI prediction. AI decision-making. The HTTP `/check` API. Any code that runs in Nikhil's, Prathamesh's, or Atharv's process.

### Explicitly forbidden
- Calling sync from the request hot path
- Reading `rl:global:*` from the gateway for enforcement decisions
- Decrementing any replicated slot
- Strong-consistency primitives (consensus, leader election, distributed locks) in the sync layer
- Hidden state (file-backed caches, persistent in-memory state across restarts)
- Silent error swallowing without metric emission
- Cross-region calls in the request path

When tempted to add something out-of-scope, propose it as a teammate's responsibility or as a future-work entry in the writeup. Do not absorb scope.

---

## Article V — Quality Gates

A change to the sync service merges only if it passes every gate below.

1. **All four test layers green.** Unit, integration, e2e, and chaos. Layer 4 runs nightly; the most recent green run must be within 24 hours of merge.
2. **Convergence test result attached.** Every PR that touches replication logic re-runs the partition convergence test and commits the result file. If convergence drifts above 5 seconds, merge is blocked until root-caused.
3. **No new metric without a Grafana panel proposal.** Coordinate with Prathamesh. Metrics that nobody looks at are dead weight.
4. **No new public method without a unit test.** No exceptions for "trivial" code.
5. **No new dependency without justification in the PR description.** We have eight modules. Adding a ninth require an Article III review.
6. **Spec sync.** If the change alters behavior described in `2026-04-25-sync-service-design.md`, the spec is updated in the same PR. Specs that lag behind code are worse than no spec.

---

## Article VI — Change-Management Rules

### Contracts are sacred
The four cross-team contracts (HTTP API, Redis schema, Prometheus metrics, policy JSON) are immutable from day 1 unless explicitly renegotiated in chat with all four owners present. If you discover you need to change a contract:

1. Stop coding.
2. Post in team chat within the hour: "Proposing contract change: [X] → [Y]. Reason: [Z]."
3. Wait for explicit acks from affected owners.
4. Update the shared contracts doc and this document if Article III is affected.
5. Then code.

### Day-0 contracts that bind sync specifically
- `dirty:{region}` channel format (Nikhil): payload is `"{tier}:{user_id}"` plain string.
- `rl:local:{region}:{tier}:{user_id}` semantics: monotonic request-allowed-count integer.
- `rl:global:{tier}:{user_id}` ownership: sync writes its region's slot, max-merges others.
- `sync:deltas` envelope: versioned JSON, fields per §4 of the spec.

### Amending this constitution
Constitutional amendments require:
1. A short written rationale (one paragraph) explaining what changed in the world to justify the change.
2. A diff of the article being amended.
3. Acknowledgment from at least one teammate that the change does not break their contract.

Amendments that add restrictions are easier than amendments that loosen them. Loosening an architectural invariant requires extra scrutiny — the invariant probably exists for a reason that is not currently top-of-mind.

---

## Article VII — Operational Defaults

These are the tuning values shipped on day 1. Change requires justification, not authorization.

| Knob | Default | Floor | Ceiling | Owner |
|---|---|---|---|---|
| Coalescer interval | 500 ms | 50 ms | 5000 ms | Hot-reload via `/admin/config` |
| Reconcile period | 30 s | 10 s | 300 s | Restart only |
| Failover buffer cap | 10 000 entries per kind | 1 000 | 100 000 | Restart only |
| Reconcile chunk size | 1 000 keys | 100 | 10 000 | Restart only |
| Pub/sub health check interval | 15 s | 5 s | 60 s | Restart only |
| Cross-region reconnect backoff | 1 s → 30 s exp | — | — | Hardcoded |
| Local Redis TTL on counter keys | window + 60 s | — | — | Set by gateway |
| Global hash TTL | 5 minutes | — | — | Set on each HSET |

The coalescer interval floor of 50 ms is set deliberately. Sub-50 ms is a footgun (CPU burn for no real accuracy gain).

---

## Article VIII — Cultural Defaults

These are not enforceable, but they are how this component is built.

1. **Read the spec before writing code each day.** Drift is the slow killer.
2. **One commit, one purpose.** A commit fixes a bug, or adds a feature, or refactors — never two.
3. **A failing test before a fix.** Reproduce the bug as a test, then fix it. The test stays in the repo.
4. **Logs are evidence, not narrative.** No "starting reconcile" / "finished reconcile" pairs. Log when something interesting happens, with structured fields, once.
5. **Comments explain why, never what.** The code says what. If you find yourself writing a what-comment, rename a variable.
6. **Docs ship with code.** The writeup is not a day-12 task; it is a continuous artifact updated alongside design changes.

---

## Article IX — Termination Conditions

Sync service work is "done" when all of the following hold:

1. All four test layers green on `main` for ≥24 hours.
2. Convergence test result < 5 seconds, reproducible across three consecutive nightly runs.
3. `scripts/solo-demo.sh` runs end-to-end without manual intervention on a clean clone.
4. Team integration test (PDF Day 6) passes with all four components live.
5. `docs/sync-design.md` writeup is at ≥1500 words, reviewed by at least one teammate.
6. Failure-mode drills (PDF Day 9) executed and documented in `docs/failure-modes.md`.
7. Demo dress rehearsal (PDF Day 10) completed without intervention.

Until all seven conditions hold, the work is not done — regardless of what the calendar says.

---

## Appendix A — Tiebreakers

Conflicts in priority resolve in this order, top wins:

1. Correctness of the monotonicity invariant (Article II §3).
2. PDF deliverables (the four contracts, the demo scenarios, the writeups).
3. Constitutional principles (Article II).
4. Demo readiness (Article II §7).
5. Code quality and test coverage.
6. Personal preference.

If two of these conflict, the higher one wins. If you find yourself violating #1 to satisfy #6, stop.

---

## Appendix B — On Saying No

"Could we also have sync replicate the policy store?" — No. Article IV.
"Should we add Streams for at-least-once?" — Not yet. Article II §4 plus Article VII (amendment requires justification).
"Can we make the gateway read global counts for accuracy?" — No. Article II §1, hard.
"What about a Raft-based variant for stronger consistency?" — No. Article III §1, Article II §2.
"Could we cache the global hash in-process for performance?" — No. Article II §5.

The sync service is small on purpose. Every "no" preserves that.

---

*"In a partition, the region that keeps serving wins. In a calendar, the team that keeps shipping wins. In a codebase, the engineer who keeps deleting wins."*
