# Demo Script — Geo-Distributed Rate Limiter

**Duration:** 8–10 minutes  
**Format:** one shared screen, two terminals visible side-by-side (left = simulator/Grafana, right = agent)

---

## Pre-demo checklist (run 5 min before)

```bash
# From repo root
docker compose up -d          # Redis ×3, Prometheus, Grafana
# Verify all three gateways are up
curl -s localhost:8081/health && curl -s localhost:8082/health && curl -s localhost:8083/health
# Open Grafana at http://localhost:3000 → main dashboard
# Clear any stale policy keys
redis-cli -p 6379 keys "policy:*" | xargs redis-cli -p 6379 del
redis-cli -p 6380 keys "policy:*" | xargs redis-cli -p 6380 del
redis-cli -p 6381 keys "policy:*" | xargs redis-cli -p 6381 del
```

---

## Scene 1 — Baseline steady state (~1 min)

**Speaker: Prathamesh** (runs simulator), **Atharv** narrates agent

**Terminal left — run steady load:**
```bash
python simulate.py --pattern global_steady --duration 120
```

**Terminal right — agent OFF (nothing running)**

> "This is our system under normal load — about 45 req/s on the free tier across three regions.
> No agent. The gateways apply static limits from the policy store.
> Watch the Grafana dashboard — rejection rate near zero, latency flat."

**Point to Grafana:** RPS by region panel, rejection rate row.

---

## Scene 2 — Product launch spike, agent OFF (~2 min)

**Speaker: Prathamesh** triggers spike, **Atharv** narrates what breaks

**Terminal left:**
```bash
python simulate.py --pattern product_launch --duration 120
```

> "Product launch — 10× spike on the US free tier.
> The agent is still off. Static limits kick in immediately and start rejecting free-tier traffic.
> But look — premium users are also getting throttled because the gateway can't distinguish
> between the spike and premium workload. This is the failure mode we're solving."

**Point to Grafana:** rejection rate climbing on free AND premium tier in US region.

**Wait ~30 seconds for the spike to show clearly in Grafana.**

---

## Scene 3 — Same spike, agent ON (~2 min)

**Speaker: Atharv** runs agent, narrates decisions

**Restart simulator with fresh spike:**
```bash
# Terminal left
python simulate.py --pattern product_launch --duration 120
```

**Terminal right — start the agent:**
```bash
# From repo root
python -m agent
```

> "Now the agent is running. It's pulling metrics from Prometheus every 10 seconds,
> feeding them into a Holt-Winters predictor, and deciding policy."

**Watch terminal right for:**
```
[2026-...] agent tick #1
  us/free: actual=420.0 rps  predicted=48.2 rps  *** SPIKE ***
  [decider] us/free throttled → 70 req/min  (predicted 420.0 rps, anomaly=False)
```

> "There — within one tick the agent detected free-tier RPS is 10× above the baseline forecast.
> It wrote a throttle policy to Redis: free tier in US drops from 100 to 70 req/min.
> The gateway picks that up on its next policy refresh."

**Point to Grafana:** rejection rate on free tier in US spikes, but premium stays clean.

> "Premium users are unaffected. The agent raised the problem at the right tier."

---

## Scene 4 — Noisy neighbor (~1.5 min)

**Speaker: Prathamesh** triggers noisy scenario, **Atharv** shows override

**Terminal left:**
```bash
python simulate.py --pattern noisy_neighbor --culprit u_999 --share 0.9
```

> "One user — u_999 — is sending 90% of the free tier's traffic. Classic noisy neighbor.
> Watch the agent's next tick."

**Terminal right — watch for:**
```
  [decider] override u_999 — 90% of us/free traffic
  [DRY-RUN is OFF so this is live] override write → u_999  limit=5/min  reason=noisy_neighbor_u_999_free_us_90%_of_tier
```

> "The agent set a per-user override on u_999 — 5 requests per minute.
> That override is written to all three regional Redis instances simultaneously.
> u_999 is throttled everywhere, and every other free-tier user returns to normal limits."

**Verify in Redis:**
```bash
redis-cli -p 6379 get "override:u_999"
```

> "The override has a 120-second TTL. If the noisy neighbor stops, the override expires
> and they're automatically restored to full limits — no manual cleanup."

---

## Scene 5 — Region failure (~1.5 min)

**Speaker: Yashashav/Nikhil** kills gateway, **Prathamesh** shows redistribution, **Atharv** shows agent resilience

**Terminal left:**
```bash
docker stop gateway-us
```

> "US gateway is dead. The simulator will see connection refused and reroute to EU and Asia.
> Watch Grafana — US RPS drops to zero, EU and Asia climb."

**What the agent does (terminal right):**
```
[2026-...] agent tick #N
  us/free: actual=0.0 rps  predicted=38.1 rps
  us/premium: actual=0.0 rps  predicted=11.2 rps
```

> "The agent sees zero RPS for US — Prometheus is still scraping, just nothing to count.
> It doesn't panic. It won't write a bogus throttle for US since zero < 80% of capacity.
> EU and Asia policies are still being managed independently."

**Restart gateway:**
```bash
docker start gateway-us
```

> "US recovers. Policy keys with 5-minute TTL are still in Redis — gateway enforces them
> immediately on restart with no agent intervention needed."

---

## Scene 6 — Kill Prometheus (failure handling demo) (~1 min)

**Speaker: Atharv**

```bash
docker stop prometheus
```

**Terminal right:**
```
[metrics_client] Prometheus unreachable at http://localhost:9090 — using synthetic data
```

> "Prometheus is down. The agent detects this — seconds_since_live starts counting.
> For the next 120 seconds it serves the last cached feature set and keeps making
> real predictions. After 2 minutes it enters safe mode: zero-RPS defaults,
> no new throttles written. Existing policies stay enforced via their TTL."

```bash
docker start prometheus
```

> "Prometheus restarts. On the next successful query, the cache resets and the agent
> returns to normal operation automatically."

---

## Scene 7 — Network partition (CRDT convergence) (~1 min)

**Speaker: Yashashav**

```bash
curl -X POST localhost:8090/admin/partition -d '{"from":"us","to":"eu","drop":true}'
```

> "US↔EU partition. Counters start drifting — US only sees local increments.
> [Yashashav narrates CRDT divergence and convergence after heal]"

```bash
curl -X POST localhost:8090/admin/heal
```

> "Partition healed. G-Counter semantics: each region keeps its own slot, global count
> is the sum. Convergence is instant — no conflicts possible."

---

## Closing (30 sec)

**Speaker: Atharv**

> "The agent is the control plane. Without it, the system is a static rate limiter —
> good, but dumb. With it, you get predictive throttling, noisy-neighbor isolation,
> and automatic recovery — all with a full audit trail in decisions.jsonl.
> Every decision has a reason field. That's your compliance story and your demo gold."

```bash
tail -f agent/decisions.jsonl | python -m json.tool
```

---

## Rehearsal commands (dry-run mode)

Practice all agent decisions without touching live Redis state:

```bash
python -m agent --dry-run
```

All predictions and decisions run normally. Policies are logged to `decisions.jsonl`
and printed with a `[DRY-RUN]` prefix. Redis is not touched.
