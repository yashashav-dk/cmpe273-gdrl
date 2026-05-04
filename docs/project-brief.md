# CMPE 273 — Project Brief

**Project codename:** `gdrl` (Geo-Distributed Rate Limiter — placeholder; team votes final name by Day 7)
**Project description:** Geo-distributed AI-driven rate limiter
**Team:** 4 — Nikhil, Yashashav, Prathamesh, Atharv
**Duration:** 2 weeks
**Source:** `CMPE 273 work.pdf` (transcribed verbatim into this document for LLM and teammate consumption)
**Final-name shortlist:** Triveni, Anemoi, Penstock, Triskele, Mascaret, Eunomia, Skopos, Aequora, Limen, Tula, Headrace, Stilling (see `docs/naming.md` once created)

This is the canonical project brief, transcribed verbatim from the PDF. Some technical specifics have been superseded by post-Day-0 amendments. When the brief and a later document conflict, the later document wins:

- **Sync wire channel** is `rl:sync:counter` (not `sync:deltas`) — see `docs/contracts.md` Contract 2 and `docs/sync-constitution.md` Appendix C, Amendment 1.
- **Global counter key** is `rl:global:{tier}:{user_id}:{window_id}` — window-id segmented for per-minute reset via TTL.
- **Sync writes peer slots only** — the gateway HIncrBy's its own region's slot. Single-writer-per-slot invariant preserved.

For sync-service work specifically, start at `docs/sync-session-handoff.md`.

---

## System Architecture

The system is a geo-distributed rate limiter with an AI traffic-shaping agent in the control loop. Read the architecture top-down:

1. Traffic enters from a **simulator** (free / premium / internal user populations).
2. A **global load balancer** routes traffic by geography and health.
3. Three regional clusters serve traffic — **US, EU, Asia**. Each region has:
   - An **API gateway** doing local enforcement.
   - A **Redis counter** acting as the regional token-bucket store.
4. A **sync & replication service** keeps regional counters loosely consistent across regions, using gossip / pub-sub. This is where the consistency-vs-latency tradeoff lives — a major writeup section.
5. Every gateway and every Redis emits metrics into a **metrics pipeline** built on Prometheus and a time-series store.
6. An **AI traffic agent** reads those metrics, predicts spikes, and decides new policies.
7. The agent writes those policies into a **policy / config store** (tier limits, regional caps, overrides). Gateways read policies on a refresh loop.

Critically, the agent is *in* the control loop — it is not a dashboard. It actually changes the limits gateways enforce.

```
                    ┌─────────────────────┐
                    │  Traffic simulator  │
                    │ free/premium/internal│
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Global load balancer │
                    │ Routes by geo & health│
                    └──────────┬──────────┘
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
       ┌───────────┐    ┌───────────┐    ┌───────────┐
       │ US region │    │ EU region │    │Asia region│
       │  Gateway  │    │  Gateway  │    │  Gateway  │
       │  Redis    │    │  Redis    │    │  Redis    │
       └─────┬─────┘    └─────┬─────┘    └─────┬─────┘
             │                │                │
             └────────────────┼────────────────┘
                              ▼
                  ┌───────────────────────┐
                  │ Sync & replication svc│
                  │ Cross-region consistency│
                  │ (gossip / pub-sub)     │
                  └───────┬───────┬───────┘
                          │       │
                          ▼       ▼
                  ┌───────────┐ ┌───────────────┐
                  │  Metrics  │ │ AI traffic    │
                  │  pipeline │→│ agent         │
                  │ Prometheus│ │ Predict spikes│
                  │   + TSDB  │ │ Set policies  │
                  └─────┬─────┘ └───────┬───────┘
                        │               │
                        └───────┬───────┘
                                ▼
                    ┌───────────────────────┐
                    │  Policy / config store │
                    │ Tier limits, regional  │
                    │ caps, overrides        │
                    └───────────────────────┘
```

Solid arrows = data flow. Dashed arrows = sync / config push.

---

## Workload Split

The team is split so each person owns one vertical slice end-to-end, with clean contracts between them.

### Nikhil — API Gateway & Rate Limiting Core

You own the data plane — the thing that actually says "allow" or "deny" on every request.

**What to build:** a Go or Node.js service that exposes `POST /check` taking `{user_id, tier, region, endpoint}` and returning `{allowed, remaining, retry_after}`. Implement two algorithms — **token bucket** (per user) and **sliding window log** (per tier+region) — behind a strategy interface so the agent can switch between them at runtime. Store counters in Redis using Lua scripts so the read-decrement-write is atomic (this is where most homegrown rate limiters break under load). Add a config-refresh goroutine that polls the policy store every 2-5 seconds for new limits. Expose Prometheus metrics: `requests_total`, `rejections_total`, `decision_latency_ms`, all labeled by `tier`, `region`, `endpoint`. Run three instances locally on different ports to simulate three regions.

**Deliverable:** three running gateway containers, a documented HTTP contract, and a load test showing it holds up at 5-10 k req/s per node.

### Yashashav — Distributed Counter Store & Sync Service

You own consistency across regions. This is the hardest distributed-systems piece.

**What to build:** each region gets its own Redis (you can run three Redis containers locally with different ports). Build a **sync service** in Python or Go that subscribes to local counter updates and publishes deltas to the other regions. Pick one of these patterns and justify it in the writeup:

- **(a) CRDT-style G-Counter** where each region keeps a vector of counts and the global count is the sum — eventually consistent, no conflicts;
- **(b) Redis pub/sub gossip** where each node broadcasts deltas every N ms;
- **(c) Leader-based** where one region is authoritative and others lease quotas.

Recommended: **(a)** — cleanest semantics, easiest to write up.

Add a configurable sync interval (50 ms / 500 ms / 5 s) so you can demo the latency-vs-accuracy tradeoff during the presentation. Build a chaos toggle: a `/partition` endpoint that drops messages between two regions, so you can show what happens during a network split.

**Deliverable:** working sync between three Redis nodes, a script that demonstrates eventual consistency after a partition heals, and a one-page writeup of the tradeoff you picked.

### Prathamesh — Traffic Simulator & Metrics Pipeline

You own everything that *feeds* the system — both the load and the observability.

**What to build:** a Python simulator using `asyncio` + `httpx` that generates realistic traffic with three knobs:

- **Base rate** (steady requests/sec)
- **Spike profile** (sudden 10x bursts simulating a product launch)
- **Noisy neighbor** (one user_id sending 90% of one tier's traffic)

Mix three user populations: 10 k free users at low RPS, 100 premium clients at higher RPS, and 5 internal services at very high RPS. Output traffic to whichever regional gateway you tell it to (round-robin, weighted, or one region only — for the failover demo).

On the metrics side: stand up Prometheus locally, scrape all three gateways and all three Redis nodes, and build a Grafana dashboard with rows for request volume, rejection rate per tier, decision latency p50/p95/p99, and counter drift between regions. The dashboard is also your demo screen.

**Deliverable:** a CLI like `python simulate.py --pattern spike --duration 5m --target eu` plus a Grafana dashboard JSON committed to the repo.

### Atharv — AI Traffic Shaping Agent

You own the brain. This is the differentiator — without you it's just another rate limiter.

**What to build:** a Python service that does three things on a loop.

1. **First**, pull last-N-minutes of metrics from Prometheus (Prathamesh's pipeline).
2. **Second**, predict the next 1-5 minutes of traffic per region per tier — start simple with **EWMA + a Holt-Winters or Prophet model** for spike detection; if you have time, layer in an LSTM or a scikit-learn `IsolationForest` for anomaly flags.
3. **Third**, decide policy: if predicted load > 80% of capacity for region X, *raise* limits for enterprise tier and *lower* limits for free tier in that region; if a region is unhealthy, shed free traffic first; if a noisy neighbor is detected (one user_id > some threshold of their tier's traffic), set a per-user override.

Write the decisions to the policy store as JSON like `{region: "eu", tier: "free", limit: 50, ttl: 60s, reason: "predicted_spike"}`. Every decision must include a `reason` field — that's your audit trail and your demo gold.

**Deliverable:** an agent service running its loop every 10-30 seconds, a log of decisions with reasons, and a notebook showing the prediction model's accuracy on synthetic data.

---

## Contracts Between People (Lock These on Day 1)

The single most important thing for a 4-person project: agree on the interfaces *before* anyone writes code. Spend a 30-minute call defining:

- The gateway's `/check` HTTP request and response shape (Nikhil → everyone)
- The Redis key schema for counters: probably `rl:{region}:{tier}:{user_id}` (Nikhil ↔ Yashashav)
- The metrics names and labels (Nikhil and Yashashav emit, Prathamesh scrapes, Atharv reads)
- The policy store schema and refresh protocol (Atharv writes, Nikhil reads)

Once these four things are written down in a shared doc, all four of you can work in parallel without blocking each other.

---

## Suggested Two-Week Timeline

- **Days 1-2:** contracts locked, repos set up, docker-compose with Redis × 3 + Prometheus + Grafana running.
- **Days 3-7:** each person builds their piece in isolation against mocked dependencies.
- **Days 8-10:** integration — wire it all together, run the simulator end-to-end.
- **Days 11-12:** demo scenarios — spike, noisy neighbor, region failover.
- **Days 13-14:** writeups for the three tradeoffs (consistency/availability, latency/accuracy, failure handling), slides, dry runs.

A complete day-by-day playbook follows. Before laying out 14 days of tasks, the foundation gets locked — the contracts everyone codes against. Each person's daily steps reference these.

---

# Day 0 — Foundation (everyone, before day 1)

## Tech Stack (recommended)

- **Language for gateway:** Go (best for high-RPS services) OR Node.js with Fastify (easier if team knows JS). Playbook assumes **Go for gateway, Python for everything else**.
- **Counter store:** Redis 7+ (one container per region)
- **Sync transport:** Redis pub/sub (built-in, no extra infra)
- **Metrics:** Prometheus + Grafana
- **Policy store:** Redis (separate DB index) or a simple Postgres table
- **Orchestration:** docker-compose (everyone runs the whole stack locally)
- **Repo layout:** monorepo with folders `gateway/`, `sync/`, `simulator/`, `agent/`, `infra/`

---

## The Four Contracts (copy this into a shared doc)

### Contract 1 — Gateway HTTP API (Nikhil owns)

```
POST /check
Request:  { "user_id": "u_123", "tier": "free|premium|internal",
            "region": "us|eu|asia", "endpoint": "/api/v1/foo" }
Response: { "allowed": true, "remaining": 42, "limit": 100,
            "retry_after_ms": 0, "policy_id": "pol_abc" }
Status:   200 always (allowed=false means rate-limited, not error)
```

### Contract 2 — Redis Counter Key Schema (Nikhil + Yashashav agree)

```
Local counter:  rl:local:{region}:{tier}:{user_id}    (TTL = window + 60s)
Global view:    rl:global:{tier}:{user_id}            (vector of region counts)
Policy cache:   policy:{region}:{tier}                (JSON)
Override:       override:{user_id}                    (JSON, set by agent)
```

### Contract 3 — Prometheus Metrics (Nikhil + Yashashav emit; Prathamesh + Atharv consume)

```
rl_requests_total{region, tier, endpoint, decision="allow|deny"}
rl_decision_duration_seconds{region}              (histogram)
rl_counter_value{region, tier, user_id}           (gauge, sampled)
rl_sync_lag_seconds{from_region, to_region}       (gauge)
rl_policy_version{region, tier}                   (gauge)
```

### Contract 4 — Policy JSON (Atharv writes, Nikhil reads)

```json
{
  "policy_id": "pol_20260425_001",
  "region": "eu",
  "tier": "free",
  "limit_per_minute": 50,
  "burst": 10,
  "ttl_seconds": 60,
  "reason": "predicted_spike_in_120s",
  "created_at": "2026-04-25T10:00:00Z"
}
```

---

## Day-by-Day Playbook

Each person's tasks are independent unless marked with **[BLOCKS X]** or **[NEEDS X]**.

---

# Day 1 — Project setup (everyone together, ~3 hours)

**Together (one call, screenshare):**

1. Create the GitHub repo, add all four as collaborators, agree on branch protection (PRs require 1 review).
2. Create the folder structure above. Add an empty `README.md` and `docker-compose.yml`.
3. Paste the four contracts into `docs/contracts.md`. Everyone reads, asks questions, signs off.
4. Decide who runs what during demos (probably Prathamesh runs the simulator, Atharv narrates the agent decisions).

**Then split off:**

**Nikhil:** Initialize Go module in `gateway/`. Run `go mod init` and pull `github.com/redis/go-redis/v9`, `github.com/gin-gonic/gin`, `github.com/prometheus/client_golang`. Get a "hello world" `GET /health` endpoint running on port 8081.

**Yashashav:** Write `infra/docker-compose.yml` that spins up three Redis containers on ports 6379, 6380, 6381 named `redis-us`, `redis-eu`, `redis-asia`. Verify you can `redis-cli -p 6380 ping` and get `PONG` from each. Initialize `sync/` as a Python project with `pyproject.toml` or `requirements.txt`, add `redis`, `asyncio`, `pydantic`.

**Prathamesh:** Add Prometheus + Grafana to the docker-compose (use `prom/prometheus:latest` and `grafana/grafana:latest`). Create `infra/prometheus.yml` with empty scrape configs for now. Initialize `simulator/` Python project with `httpx`, `asyncio`, `numpy`, `click` for the CLI.

**Atharv:** Initialize `agent/` Python project. Add `prometheus-api-client`, `redis`, `pandas`, `scikit-learn`, `prophet` (or `statsmodels` if Prophet is annoying to install — it sometimes is). Get a "hello world" loop that prints "agent tick" every 10 seconds.

**End of day 1:** docker-compose up brings up 3 Redis + Prometheus + Grafana. Each person has a hello-world service in their folder.

---

# Day 2 — Core skeletons

## Nikhil — Gateway skeleton with token bucket

1. Create `gateway/internal/limiter/` package. Define a `Limiter` interface with one method: `Check(ctx, key, limit, burst) (allowed bool, remaining int, err error)`.
2. Implement `TokenBucketLimiter` using a Redis Lua script. The Lua script does: read current tokens + last refill time → compute new tokens based on elapsed time → if tokens >= 1, decrement and return allowed, else return denied. Atomic in one round trip.
3. Wire it to `POST /check`. Hardcode limits for now: free=10/min, premium=100/min, internal=1000/min. Use `redis-us` (port 6379) only.
4. Test with `curl`: send 15 requests as a free user, confirm 11th onwards returns `allowed: false`.

The Lua script is the crux of this whole project. Search "redis token bucket lua atomic" if you get stuck — there are well-known reference implementations.

## Yashashav — Local Redis wrapper + key schema

1. Create `sync/counter.py` with a `RegionalCounter` class wrapping Redis. Methods: `increment(region, tier, user_id)`, `get_local(region, tier, user_id)`, `get_global(tier, user_id)`. Use the key schema from Contract 2.
2. Write a unit test: `RegionalCounter("us").increment("free", "u1")` then `get_local` returns 1.
3. Stub a `SyncService` class with empty `start()`, `publish_delta()`, `apply_remote_delta()` methods. You'll fill these on day 4-5.

## Prathamesh — Simulator skeleton

1. Create `simulator/cli.py` with click commands: `simulate steady --rps 100 --duration 60`, `simulate spike --base 100 --peak 1000 --at 30s`, `simulate noisy --culprit u_999 --share 0.9`.
2. For now, just print the request it *would* send. Generate 10k fake free user_ids, 100 premium, 5 internal — pickle them to a file so the same population is reused across runs.
3. Write the request loop using `asyncio.gather` with a semaphore to control concurrency.

## Atharv — Metrics reader skeleton

1. Create `agent/metrics_client.py` that connects to Prometheus at `http://localhost:9090` and runs a query like `sum(rate(rl_requests_total[1m])) by (region, tier)`.
2. Since no metrics exist yet, mock it: have the client return synthetic data shaped like Prometheus output. This unblocks you while waiting for Nikhil.
3. Create `agent/decision_log.py` that appends every decision to a JSONL file. You'll thank yourself at demo time.

**End of day 2:** Nikhil has a working single-region rate limiter you can curl. Everyone else has skeletons.

---

# Day 3 — First integration

## Nikhil — Multi-region gateway + Prometheus metrics [BLOCKS Prathamesh, Atharv]

1. Refactor so the gateway can be started with `--region us` flag and connects to the right Redis (`redis-us` for us, etc.). Run three instances on ports 8081, 8082, 8083.
2. Add Prometheus metrics from Contract 3. Expose `/metrics` endpoint on each instance.
3. Update `infra/prometheus.yml` to scrape all three gateways. Verify in Prometheus UI at `localhost:9090` that metrics show up with correct `region` labels.
4. **Hand off to team:** post in chat "gateways live on 8081/8082/8083, metrics flowing."

## Yashashav — Sync transport choice

1. Decide the sync model. **Recommended for this project: G-Counter CRDT over Redis pub/sub.** Each region maintains its own count; the "global" count for a key is the sum across regions. Conflicts impossible because each region only writes its own slot.
2. Document the choice in `docs/sync-design.md` — one page covering: the data structure, why CRDT over leader-based, the eventual consistency guarantee, the bounded staleness window.
3. Implement `publish_delta(region, tier, user_id, count)` that publishes to a Redis pub/sub channel `sync:deltas`. Implement `subscribe()` that reads the channel and writes to `rl:global:{tier}:{user_id}` as a hash with one field per region.

## Prathamesh — Real traffic against gateway [NEEDS Nikhil end-of-day]

1. Replace the print statement with real `httpx.AsyncClient.post()` to `localhost:8081/check`.
2. Add a `--target-region` flag that picks which gateway to hit. For multi-region demos, add `--distribution us:0.5,eu:0.3,asia:0.2`.
3. Run a 1-minute steady test at 100 RPS against the US gateway. Confirm in Prometheus UI that `rl_requests_total{region="us"}` is climbing.
4. Start building the Grafana dashboard. Add panels for: total RPS by region, rejection rate by tier, p95 decision latency. Save the dashboard JSON to `infra/grafana/dashboard.json`.

## Atharv — Switch from mock to real Prometheus [NEEDS Nikhil + Prathamesh]

1. Once Prathamesh is generating traffic, point your metrics client at real Prometheus.
2. Build a "feature extractor" function: given the last 5 minutes of metrics, return a dict like `{"us": {"free_rps": 45, "premium_rps": 12, "rejection_rate": 0.02}, ...}`. This is what your model will consume.
3. Run it every 10 seconds in your loop and print the features. No decisions yet — just observation.

**End of day 3:** End-to-end traffic flow works for one region. Three people have hands-on data.

---

# Day 4 — Cross-region sync goes live

## Nikhil — Sliding window log + policy refresh

1. Add a second algorithm: `SlidingWindowLogLimiter`. Use Redis sorted sets — `ZADD` request timestamps, `ZREMRANGEBYSCORE` to drop old ones, `ZCARD` to count. More accurate than token bucket for tier-level limits.
2. Add a strategy switcher: gateway reads policy from Redis key `policy:{region}:{tier}` every 5 seconds. If policy says `algorithm: "sliding_window"`, use that. This is how Atharv's agent will control your gateway.
3. Add unit tests for both limiters covering: under-limit allow, over-limit deny, recovery after window passes.

## Yashashav — Wire sync into gateway flow [COORDINATES with Nikhil]

1. Modify Nikhil's gateway (or give him a Go client he calls) so every successful `Check` increments local counter AND publishes a delta to your sync channel.
2. Run your subscriber in each region. Verify: a request to US gateway increments `rl:local:us:free:u1=1` AND `rl:global:free:u1` shows `{us: 1, eu: 0, asia: 0}`.
3. Add `rl_sync_lag_seconds` metric: timestamp deltas at publish time, measure subtraction at apply time, expose to Prometheus.

## Prathamesh — Scenario library

1. Build named scenarios in `simulator/scenarios.py`:
   - `product_launch`: 10x spike on US for 2 minutes, then back to baseline
   - `noisy_neighbor`: one free user sending 50% of free traffic
   - `region_failover`: kill US gateway mid-run, traffic should redistribute (you'll need help from Nikhil to actually kill a gateway — `docker stop gateway-us`)
   - `global_steady`: balanced load across all three regions for baseline metrics
2. Each scenario runs with one command. Add docs in `simulator/README.md`.

## Atharv — First prediction model

1. Build `agent/predictor.py`. Input: time series of RPS per region+tier from last 30 minutes. Output: predicted RPS for next 2 minutes.
2. Start dead simple: **Exponentially Weighted Moving Average (EWMA)** with alpha=0.3. Add a "spike detector" — if current RPS > 2x EWMA, flag a spike.
3. Test against Prathamesh's `product_launch` scenario. Print predictions vs actuals every 10 seconds. They'll be wrong; that's fine, you'll improve on day 8.

**End of day 4:** Sync works across regions. Multiple scenarios available. Predictor is making (bad) predictions.

---

# Day 5 — Policy plane goes live

## Nikhil — Policy + override enforcement

1. Make the gateway read TWO things on every `/check`:
   - **Tier policy:** `policy:{region}:{tier}` (limit, burst, algorithm)
   - **User override:** `override:{user_id}` (per-user limit, used for noisy neighbors)
2. Override beats tier policy. If `override:{u_999}` says `limit: 1`, that user gets 1/min regardless of their tier.
3. Cache both in-memory with 5-second TTL to avoid Redis hit on every request. Update `rl_policy_version` metric every time a new policy is loaded.

## Yashashav — Partition simulation

1. Add a `/admin/partition` endpoint to the sync service: `POST /admin/partition {from: "us", to: "eu", drop: true}` causes your subscriber to drop messages between those regions.
2. Add `/admin/heal` to undo it.
3. Write `docs/sync-design.md` section on what happens during a partition: counters drift, gateways over-allow (they only see local), then converge after heal. This is the "consistency vs availability" tradeoff for your final writeup.

## Prathamesh — Grafana dashboard v1

1. Finalize the main dashboard with these rows:
   - **Traffic:** RPS by region, RPS by tier, total
   - **Decisions:** allow rate, deny rate, deny rate by tier
   - **Latency:** p50/p95/p99 of decision_duration
   - **Sync health:** sync lag by region pair, counter drift between regions
   - **Policy:** current policy_version per region+tier (stat panel)
2. Add Grafana annotations that fire on agent decisions (you'll wire this with Atharv on day 6).

## Atharv — First real decision [NEEDS Nikhil's policy plane]

1. Build `agent/decider.py`. Rules-based v1, no ML yet:
   - If predicted RPS for `(region, free)` > 80% of capacity → write policy lowering free limit by 30%
   - If predicted RPS for `(region, premium)` < 50% of capacity AND free is throttled → raise free limit back up
   - If a single user_id is > 30% of their tier's traffic → write `override` for that user
2. Write decisions to Redis as Contract 4 JSON. Log every decision with `reason`.
3. Test loop: start `noisy_neighbor` scenario → within 30 seconds, agent should detect the culprit and write an override → gateway should start throttling them → metrics should show their rejection rate spike. **This is your money demo.**

**End of day 5:** End-to-end loop closed. Agent observes → predicts → decides → writes → gateway enforces. Even if dumb, it works.

---

# Day 6 — First integration test (everyone together, half day)

Block out 4 hours. Run scenarios end-to-end and find what breaks.

1. **Steady state:** run `global_steady` for 5 minutes. Confirm metrics look normal, no flapping policies, sync lag < 1s.
2. **Spike:** run `product_launch`. Watch the agent detect → react → policies change → free users start getting throttled → premium stays unaffected. Capture screenshots.
3. **Noisy neighbor:** run that scenario. Time how long until the override fires. Tune the threshold.
4. **Partition:** trigger US↔EU partition mid-run. Watch counters drift. Heal. Watch them converge.
5. **Region failure:** `docker stop gateway-us`. Confirm simulator sees errors and Prathamesh's `--distribution` reroutes to other regions.

Make a punch list of every bug. Assign each bug to whoever owns that component. Day 7 is fixing.

---

# Day 7 — Bug fixes + polish

Each person fixes their punch list items. Specific known issues you'll likely hit:

**Nikhil:** Lua script edge cases (clock skew, TTL expiry mid-decrement). Race condition where two policy updates arrive within the cache TTL window.

**Yashashav:** Pub/sub message loss when subscriber is slow. Solution: switch to Redis Streams with consumer groups, OR add a periodic full-state reconciliation (every 60s, dump local counters to global).

**Prathamesh:** Simulator can't generate enough load (Python GIL). Solution: `multiprocessing` with one process per target region.

**Atharv:** Agent flapping — keeps changing policy back and forth. Solution: add hysteresis (don't reverse a decision within 60 seconds of making it) and a minimum policy lifetime.

---

# Day 8 — ML upgrades + chaos

## Nikhil — Performance + graceful degradation

1. Add a circuit breaker: if Redis is down, fall back to in-memory limits (degraded mode). Better to over-allow than to fail closed and reject everyone.
2. Run a load test: `vegeta` or `k6` at 5k RPS for 5 minutes. Tune Redis pool size. Document p99 latency.

## Yashashav — Reconciliation

1. Add the periodic reconciliation if you didn't on day 7. Every 30s, each region publishes its full count vector. Receivers merge using `max()` per slot (G-Counter semantics).
2. Write a test that proves convergence: partition for 60s, generate divergent load, heal, verify all regions agree within 5 seconds.

## Prathamesh — Realistic patterns

1. Replace flat RPS with **Poisson-distributed inter-arrival times**. Real traffic is bursty even at steady state.
2. Add diurnal patterns: a sine wave overlay so RPS varies smoothly over a 5-minute "day."
3. This makes Atharv's predictor look way better.

## Atharv — Better predictor

1. Replace EWMA with **Holt-Winters exponential smoothing** (`statsmodels.tsa.holtwinters.ExponentialSmoothing`) — handles trend + seasonality, perfect for diurnal patterns.
2. Add an `IsolationForest` from scikit-learn for anomaly detection — flags "this RPS is unusual for this time of day" which is better than a fixed threshold.
3. Train both on Prathamesh's diurnal scenario data. Show MAE improvement vs EWMA in your notebook.

---

# Day 9 — Failure handling

Whole team focuses on the third tradeoff. Run these drills and document results:

1. **Kill a Redis:** `docker stop redis-eu`. Gateway should circuit-break to in-memory, sync service should buffer deltas, agent should detect missing metrics and not panic.
2. **Kill a gateway:** simulator gets connection refused, retries to next region.
3. **Kill the agent:** policies stay in place (they have TTL — set it long enough that brief agent outages are fine, e.g. 5 minutes), gateway keeps enforcing last-known policy.
4. **Kill Prometheus:** agent uses last-known features for up to 2 minutes, then enters "safe mode" (revert to default static limits).
5. **Network partition between two regions:** as on day 5.

Each person writes a paragraph in `docs/failure-modes.md` for their component covering: what fails, how it's detected, what the system does, recovery time.

---

# Day 10 — Demo dress rehearsal

1. Write the demo script: 8-10 minute flow, who speaks when, which terminal/dashboard is shown.
2. Suggested narrative arc:
   - "Static limits — watch what happens during a launch" — run `product_launch` with agent disabled, show premium getting throttled
   - "Now turn on the agent" — same scenario, agent intervenes, premium stays clean
   - "Noisy neighbor" — show override being written in real-time
   - "Region failure" — kill US, show traffic redistribution
   - "Partition" — show CRDT convergence
3. Record a backup video of the full demo in case of live failure.

---

# Days 11-12 — Writeups (split by person)

Each person writes one section of the final report.

**Nikhil — "Rate limiting algorithms and the local enforcement plane."** Token bucket vs sliding window math, the Lua atomicity argument, latency numbers from your load test.

**Yashashav — "Consistency vs availability: a CRDT approach to geo-distributed counters."** The G-Counter design, why eventual consistency is acceptable for rate limiting, partition tolerance proof, convergence test results.

**Prathamesh — "Observability and traffic modeling."** How you generated realistic traffic, the Poisson + diurnal model, what the Grafana dashboards show, screenshots.

**Atharv — "AI in the control plane."** Why predictive limits beat static limits, model comparison (EWMA vs Holt-Winters vs IsolationForest), decision-loop architecture, examples of decisions with reasons.

---

# Days 13-14 — Slides, dry runs, submission

**Day 13:** build slides (one section per writeup, plus a system architecture slide using the diagram from the brief). Two dry runs of the demo.

**Day 14:** final dry run morning, submit by afternoon, breathe.

---

## Critical Things That Will Save You Pain

**Use a shared Notion or Google Doc for daily standups.** Each person writes 3 lines every morning: yesterday, today, blockers. Catches integration issues before they fester.

**The contracts on day 0 are not optional.** Most 4-person projects fail because two people implemented the same thing differently. If you change a contract, post it in chat the same hour.

**Atharv's work depends on everyone else's.** Make sure Nikhil and Prathamesh prioritize getting metrics flowing by end of day 3. If Atharv is blocked past day 4, the project is at risk.

**Demo first, perfection second.** A working end-to-end flow on day 5 (even if dumb) is worth more than three perfect components on day 10. The day 6 integration test is the most important day on this calendar.

---

## Appendix — Notes for LLMs and New Teammates

If you are a teammate or an LLM picking this project up cold, read in this order:

1. This file (`docs/project-brief.md`) — full project context.
2. `docs/contracts.md` — once written by the team, this is the source of truth for cross-component interfaces. (Build from §"The Four Contracts" above on day 1.)
3. `docs/sync-design.md` (Yashashav) — sync model and tradeoffs.
4. `docs/failure-modes.md` (everyone, day 9) — operational behavior.
5. `docs/sync-constitution.md` (Yashashav) — sync service principles and invariants. Read before touching `sync/`.
6. `docs/superpowers/specs/2026-04-25-sync-service-design.md` (Yashashav) — full sync service spec.

Per-component owners and entry points:

- Gateway: `gateway/` (Go) — Nikhil
- Sync service: `sync/` (Python) — Yashashav
- Simulator + metrics infra: `simulator/`, `infra/` — Prathamesh
- AI agent: `agent/` (Python) — Atharv

When writing code, always check the contracts first, then the relevant component's design doc, then this brief. The contracts win in any conflict — they are the binding interface.

---

*Original source: `CMPE 273 work.pdf`. This document is the canonical machine-readable transcription. If the PDF and this document disagree, this document wins for in-repo use; flag the discrepancy in chat.*
