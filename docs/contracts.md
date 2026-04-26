# Cross-Team Contracts

**Status:** Locked Day 1. Any change requires explicit ack from all affected owners before code is written.
See `docs/sync-constitution.md` Article VI for the amendment protocol.

---

## Contract 1 — Gateway HTTP API
**Owner:** Nikhil  **Consumers:** Prathamesh (simulator), Atharv (agent reads rejections)

```
POST /check
Request:  { "user_id": "u_123",
            "tier":    "free" | "premium" | "internal",
            "region":  "us" | "eu" | "asia",
            "endpoint": "/api/v1/foo" }

Response: { "allowed":        true | false,
            "remaining":      42,
            "limit":          100,
            "retry_after_ms": 0,
            "policy_id":      "pol_abc" }

HTTP status: 200 always.
  allowed=true  → request is permitted.
  allowed=false → rate-limited (NOT a 4xx/5xx error).
```

Gateways run on:
| Region | Port |
|--------|------|
| us     | 8081 |
| eu     | 8082 |
| asia   | 8083 |

---

## Contract 2 — Redis Key Schema
**Owners:** Nikhil (writes local), Yashashav (writes global)

```
Local counter:   rl:local:{region}:{tier}:{user_id}    (TTL = window + 60s, INTEGER — monotonic allowed-count)
Global view:     rl:global:{tier}:{user_id}            (HASH — one field per region, max-merge G-Counter)
Policy cache:    policy:{region}:{tier}                (JSON string — set by Atharv's agent)
User override:   override:{user_id}                    (JSON string — set by Atharv's agent)
Dirty signal:    dirty:{region}                        (pub/sub channel — payload: "{tier}:{user_id}")
Sync broadcast:  sync:deltas                           (pub/sub channel — cross-region G-Counter envelopes)
```

Semantics:
- `rl:local:*` is written ONLY by the gateway (Nikhil). Monotonically increasing.
- `rl:global:*` is written ONLY by the sync service (Yashashav). One field per region, max-merge on receive.
- `policy:*` and `override:*` are written ONLY by the AI agent (Atharv). Gateways read-only.
- Gateway publishes `dirty:{region}` after every allowed request (fire-and-forget).

---

## Contract 3 — Prometheus Metrics
**Emitters:** Nikhil (gateway), Yashashav (sync service)
**Consumers:** Prathamesh (Grafana dashboard), Atharv (agent feature extraction)

```
# Gateway metrics
rl_requests_total{region, tier, endpoint, decision="allow|deny"}   counter
rl_decision_duration_seconds{region}                                histogram
rl_counter_value{region, tier, user_id}                             gauge  (sampled)
rl_policy_version{region, tier}                                     gauge

# Sync service metrics
rl_sync_lag_seconds{from_region, to_region}                         histogram
  buckets: [0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10]
```

Additional sync metrics are in `docs/superpowers/specs/2026-04-25-sync-service-design.md` §8.

---

## Contract 4 — Policy JSON
**Writer:** Atharv (AI agent)  **Reader:** Nikhil (gateway, polls every 2-5s)

```json
{
  "policy_id":        "pol_20260425_001",
  "region":           "eu",
  "tier":             "free",
  "limit_per_minute": 50,
  "burst":            10,
  "ttl_seconds":      60,
  "reason":           "predicted_spike_in_120s",
  "created_at":       "2026-04-25T10:00:00Z"
}
```

Stored at Redis key `policy:{region}:{tier}`.
- Gateway caches in-memory with 5s TTL to avoid per-request Redis hit.
- `reason` field is mandatory — it is the audit trail and demo gold.
- User overrides (`override:{user_id}`) beat tier policy. Gateway checks override first.
