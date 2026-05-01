# Failure Modes

Each component owner documents: what fails, how it's detected, what the system does, and recovery time.

---

## AI Traffic Agent (Atharv)

### Failure 1 — Prometheus unreachable

**What fails:** The agent cannot pull fresh metrics from Prometheus (process down, network partition, scrape config broken).

**How it's detected:** `PrometheusClient._query()` catches the connection exception and returns `None`. `seconds_since_live()` begins counting up from the last successful query.

**What the system does:**
- For the first 120 seconds after Prometheus drops, `FeatureExtractor` serves the last successfully cached feature set — predictions and decisions continue using stale-but-real traffic data.
- After 120 seconds, the extractor switches to zero-RPS static defaults. With no traffic signal, the decider sees nothing above any throttle threshold and stops writing new policies. Existing Redis policies remain enforced by the gateway until their TTL expires (300 s for tier policies, 120 s for per-user overrides).

**Recovery time:** Instant — on the next tick after Prometheus comes back, `_query()` succeeds, `_last_success` resets, and the extractor starts caching fresh features again. No manual intervention needed.

---

### Failure 2 — Agent process killed / crashes

**What fails:** The agent loop exits mid-run. No new policies or overrides are written to Redis.

**How it's detected:** Nothing in-band detects this — the agent is stateless from the gateway's perspective. Grafana will show `rl_policy_version` frozen (no new version bumps).

**What the system does:** Gateways continue enforcing the last policies written to Redis. All policy keys have `TTL = 300 s` (5 minutes) and override keys have `TTL = 120 s`. For normal steady-state traffic this is safe — default limits are conservative. For an active throttle, the throttled limit stays in place until TTL expiry, then the gateway falls back to its own in-memory defaults.

**Recovery time:** Restart the agent process (`python -m agent` from repo root). Predictor warm-up from 30-minute Prometheus history takes ~1 second. First tick fires within 10 seconds and resumes normal policy writing.

---

### Failure 3 — Redis unreachable (one or more regions)

**What fails:** `PolicyWriter.write_policy()` / `write_override()` cannot reach a regional Redis instance.

**How it's detected:** `redis.Redis.ping()` fails at startup, so that region is excluded from `_clients`. Mid-run `setex` exceptions are caught and silently skipped.

**What the system does:** Decisions are still logged to `agent/decisions.jsonl` (the audit trail is preserved). The affected region simply doesn't receive new policy updates. Existing cached policies on that Redis stay live until their TTL expires; after that the gateway falls back to in-memory defaults.

**Recovery time:** Redis reconnection is not retried automatically — a process restart picks up healthy Redis instances. Low priority fix: add a reconnect loop in `PolicyWriter.__init__`.

---

<!-- Nikhil, Yashashav, Prathamesh — append your sections below in the same format -->
