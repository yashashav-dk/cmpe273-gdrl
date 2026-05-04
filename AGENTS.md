# Agent / LLM guide

This repo is a 4-component team project (CMPE 273). Each top-level dir has one owner; touching another's dir without coordination breaks contracts.

## Layout

| Dir | Owner | Purpose |
|---|---|---|
| `agent/` | Atharv | Observability-driven policy/override writer. Reads Prometheus metrics; writes `policy:*` and `override:*` to all 3 region Redises. |
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

Branches: `<owner>/<topic>` — e.g. `yashashav/sync-d5-foundation`, `atharv/day5-decider`.
Commits: prefix with `dayN(component):` for daily-scope work, or `feat|fix|chore|docs(scope):` for non-day work.
