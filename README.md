# cmpe273-gdrl

**CMPE 273 — Geo-distributed AI-driven rate limiter**

Working codename: `gdrl`. Final name vote Day 7 — see [`docs/naming.md`](docs/naming.md).

## Team

| Owner | Component | Stack |
|---|---|---|
| Nikhil | API Gateway + Rate Limiting Core | Go, Gin, Redis Lua |
| Yashashav | Distributed Counter Store + Sync Service | Python, asyncio, Redis pub/sub |
| Prathamesh | Traffic Simulator + Metrics Pipeline | Python (asyncio + httpx), Prometheus, Grafana |
| Atharv | AI Traffic Shaping Agent | Python, scikit-learn, Holt-Winters / Prophet |

## What it does

Three regional API gateways enforce rate limits locally on Redis token buckets. A cross-region sync service replicates counters using G-Counter CRDT semantics (max-merge, eventually consistent). An AI traffic-shaping agent reads metrics, predicts spikes, and writes policies that the gateways adopt on a refresh loop. Demo proves three tradeoffs: consistency vs availability, latency vs accuracy, graceful failure handling.

## Repo layout

```
cmpe273-gdrl/
├── gateway/           # Nikhil — Go gateway
├── sync/              # Yashashav — Python sync service
├── simulator/         # Prathamesh — Python traffic simulator
├── agent/             # Atharv — Python AI agent
├── infra/             # docker-compose, Prometheus, Grafana configs
├── docs/
│   ├── project-brief.md         # canonical project brief
│   ├── naming.md                # final-name shortlist + vote protocol
│   ├── sync-constitution.md     # sync service principles & invariants
│   └── superpowers/specs/       # design specs
└── scripts/           # solo-demo, convergence-proof, etc.
```

## Quick start

Once the team has stood the system up, the entire 3-region cluster comes up with:

```sh
docker-compose up
```

Sync service can also run **standalone** (no gateway, no simulator, no Prometheus required) for solo development:

```sh
make demo-sync
```

## Documentation

- [`docs/project-brief.md`](docs/project-brief.md) — full project context. **Read first.**
- [`docs/naming.md`](docs/naming.md) — naming workflow.
- [`docs/sync-constitution.md`](docs/sync-constitution.md) — non-negotiable principles for the sync service.
- [`docs/superpowers/specs/2026-04-25-sync-service-design.md`](docs/superpowers/specs/2026-04-25-sync-service-design.md) — sync service design spec.

## Timeline

2-week build. Day-by-day playbook in [`docs/project-brief.md`](docs/project-brief.md). Key checkpoints:

- **Day 1** — repo + contracts locked, docker-compose up
- **Day 5** — end-to-end loop closed (agent → policy → gateway enforces)
- **Day 6** — full integration test
- **Day 9** — failure-mode drills
- **Day 10** — demo dress rehearsal
- **Day 14** — submit
