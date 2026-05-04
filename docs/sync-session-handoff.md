# Sync service — session handoff

**Last updated:** 2026-05-03 (D8 wrap, PR #20 open). Update the timestamp + "Where we are" section at the end of every Claude session.

This file is the single starting point for any LLM session resuming sync-service work. Read it first; it routes to everything else.

---

## What this project is

CMPE 273 group project — a 3-region geo-distributed AI rate limiter. Yashashav owns the **sync service**: a stateless Python relay that subscribes to `rl:sync:counter` on three Redis instances and max-merges peer slots into the local `rl:global:{tier}:{user_id}:{window_id}` hash.

Teammates: Atharva (`agent/`), Prathamesh (`simulator/`), Nikhil (`gateway/`). All four components live in this repo. Cross-team boundaries in `AGENTS.md` (when present) and `docs/contracts.md` (always).

---

## Where we are (update this section every session)

**Branch:** `yashashav/sync-d5-foundation` (pushed @ `533cad5`)
**Current PDF day:** D5 + D6 + D7 + D8 done. **All 29 plan tasks complete.** D9 next.
**Next task:** D9 plan TBD (failure-mode drills, `docs/failure-modes.md`, team integration, load test, CI workflow `.github/workflows/sync-ci.yml`, plan-defect amendments).
**Code in `sync/`:** crdt.py, envelope.py, counter.py, transport.py, partition_table.py, metrics.py, relay.py, buffer.py, reconciler.py, admin.py, service.py, dev/{__init__.py, gateway_stub.py, sync_cli.py} + Dockerfile + Dockerfile.dev + tests/conftest.py + 9 test files (unit: crdt, envelope, partition_table, buffer; integration: counter_redis, transport_pubsub, gateway_stub, relay, reconciler, admin; e2e: basic_propagation, partition; chaos: convergence, redis_failure). Plus `scripts/solo-demo.sh`.
**Tests passing:** 59 / ~50 planned (28 unit: 8 crdt + 10 envelope + 5 partition_table + 5 buffer; 27 integration: 11 counter + 3 transport + 1 stub + 4 relay + 3 reconciler + 5 admin; 2 e2e: basic_propagation + partition; 2 chaos: convergence + redis_failure). Plan miscount streak holds for 4th day (+4/day; D8 ended at +9 vs plan's 50). Lint clean.
**Open PR:** **#20** — `sync(d5–d8): foundation through chaos proof` (https://github.com/yashashav-dk/cmpe273-gdrl/pull/20).
**Convergence proof:** 15 runs in `sync/tests/chaos/results/`, all `passed=True`, range 0.962s–1.031s, target <5s. Constitution Art IX termination conditions satisfied for D8 scope.

History:
- 2026-04-26: project brief, naming, sync constitution, sync design spec committed.
- 2026-04-28: Constitution Amendment 1 + spec §4/§5/§6 rewritten to track merged gateway behavior; spec §14 (compressed timeline) + §15 (handover artifacts) added.
- 2026-04-30: plan written; ruff/mypy/CI gates rationalised; session phasing locked in; this handoff file added.
- 2026-05-01 → 2026-05-02 02:30: D5 executed (Tasks 1–11) via subagent-driven dev. 15 commits. All 4 D5 gates green (tests/lint/docstrings/push). Branch pushed.
- 2026-05-02: D6 executed (Tasks 12–16) via subagent-driven dev. 4 commits. All 4 D6 gates green (tests/lint/docstrings/push). Branch pushed @ `dcf2867`. 33 tests passing (+4 vs D5). Notable: Task 13 TDD deviation — disconnect-recovery test passed against minimal `_pump` because redis-py auto-reconnects pubsub on `CLIENT KILL TYPE pubsub` transparently; reviewer accepted (spec mandates explicit reconnect loop regardless).
- 2026-05-02: D7 executed (Tasks 17–21) via subagent-driven dev. 5 commits (+1 fix-up commit on Task 18). All 4 D7 wrap gates green (tests/lint/docstrings/push). Branch pushed @ `91315e2`. 46 tests passing (+13 vs D6). Three reviewer-approved deviations (see retro). Wall-clock ~45 min autonomous after delegation.
- 2026-05-03: D8 executed (Tasks 22–29) via subagent-driven dev. 10 commits (+1 prod fix-up on `service.py` socket timeouts triggered by Task 27 chaos diagnosis, +1 chaos test fix-up bumping polling 5s→15s after D8-wrap reproducible failure surfaced socket_timeout/EVALSHA-fallback timing). All 4 D8 wrap gates green (4 layers/lint/docstrings/push) + PR #20 opened. 59 tests passing (+13 vs D7). Convergence proof: 15 runs all <1.05s, target <5s. **Five plan defects** worked around (T18 partition, T19 reconcile-skip, T22 stub overflow, T25/26 hardcoded windows, T27 socket timeouts). Wall-clock ~3 hrs (long-running chaos diagnosis ate ~30 min).
- **Next session:** begin D9 (new plan TBD). Scope: failure-mode drills, `docs/failure-modes.md`, team integration, load test, CI workflow, plan-source amendments for the 5 defects. PR #20 stays open until reviewer feedback round closes.

## Deferred concerns (not blocking; track for D9 polish)

- Plan typo: "Atharva" → "Atharv" still in plan source (lines 319, 353). Fixed in AGENTS.md only.
- Plan mislabel: §2 of `sync/CONTEXT.md` quotes labelled "verbatim" are paraphrases of constitution. Fixed inline; plan source still mislabeled.
- Plan miscount: Task 11 expected "25 tests"; actual 29. Task 16 expected "29 tests"; actual 33. Plan source not updated.
- Plan miscalibration (Task 13): expected disconnect-recovery test to fail against minimal `_pump`; redis-py auto-reconnects pubsub transparently so test passes either way. Spec-mandated reconnect loop still required and shipped — test now serves as regression guard for harder failure modes. Document the redis-py behavior in spec §5.transport.py if a future session re-adds the test.
- TTL inconsistency: `sync/dev/gateway_stub.py` uses `expire(global_key, 120)` while `sync/counter.py` uses `GLOBAL_TTL_SECONDS = 300`. Last-writer-wins on TTL means stub will shorten TTL on every allow_request after counter sets it to 300. Plan-verbatim, not blocking — but reconcile to a shared constant in D9.
- `transport.py` magic numbers `1.0` / `30.0` for backoff — promote to module constants `BACKOFF_INITIAL_S` / `BACKOFF_MAX_S` (D9).
- `transport.py:54` `except (asyncio.CancelledError, Exception):` is functionally identical to `except Exception:` (CancelledError derives from BaseException in 3.11). Either narrow or comment.
- `transport.py:_pump` `queue` parameter unparametrized vs the `subscribe_peers` local at line 40 which is `asyncio.Queue[tuple[str, bytes]]`. Tighten.
- `gateway_stub.py` `int(new_value)` cast applied twice on the same value — pure style, bind once.
- `sync_cli.py` httpx 2.0s timeout undocumented magic — promote to constant or comment.
- Tests use undocumented `0.3s` settle / `0.5s` reconnect / `5.0s`/`10.0s` consumer-deadline magic numbers — comment intent.
- Test duplication: `test_transport_pubsub.py` has near-duplicate `Transport(...)` construction across the 3 tests; could fixture-ize.
- `LICENSE-3RD-PARTY.md` for python3-crdt MIT attribution (D9).
- `.dockerignore` at repo root (`__pycache__` lands in build context).
- `EXPOSE 9100` in `sync/Dockerfile`.
- `version: "3.9"` deprecated in compose; remove (D9).
- `[tool.ruff.lint].select` not configured; defaults catch only F+E. Consider adding `B,UP,I,ASYNC` (D9).
- README.md → AGENTS.md pointer (one-liner).
- `from_slots` docstring: clarify rehydration-only intent.
- `OwnSlotWriteError` test uses `pytest.raises(OwnSlotWriteError)` — keep distinct from ValueError.
- testcontainers `@wait_container_is_ready` deprecation warning. Upstream-only.
- D7 Task 18 partition deviation: plan's `_handle` checks `self._partition.blocks(origin, self._region)` using transport-tagged origin. Switched to envelope-asserted region (`env.region` for counter, `env.origin` for reconcile) because test fixture uses `peer_redises={}` so transport tag is always local — plan-byte-exact code can't pass the test. In production both coincide for trusted peers. Metric labels (lag/messages_total) still use transport tag. Plan-source not amended.
- D7 Task 19 reconcile-skip deviation: plan's `if value <= 0: continue` (using `get_own_slot`) contradicts plan's own test 2 (writes `us=0` for `u_0`, asserts 5 keys broadcast). `get_own_slot` cannot distinguish absent slot (HGET None → 0) from slot=0. Switched to `get_global` + `if self._region not in global_slots: continue`. Trade-off: HGETALL per user vs HGET. ~3× bytes. Negligible at chunk_size=1000 every 30s.
- D7 Task 19 deferred polish: per-key `RECONCILE_KEYS.inc(1)` instead of post-loop `inc(keys)` (loses signal on long-pass crashes); `_tick`'s `except Exception: continue` lacks `logger.warning` line; `stats.chunks_published` not asserted in test 2 (only wire-side `len(received)`).
- D7 Task 18 deferred polish: bare `except Exception:` in `_handle_counter`/`_handle_reconcile` swallows errors silently (Constitution Art II §6 / Art IV concern). Constitution-faithful fix lands in Task 22 when `Buffer.push` itself emits `BUFFER_SIZE`/`BUFFER_OVERFLOW` metrics. Buffer payload tuple shape `(tier, user_id, window_id, region, value)` is untyped — consider `BufferedSlot` NamedTuple in Task 22.
- D7 Task 18 deferred polish: `metrics.py` has only `Spec:` line; missing `Reads:`/`Writes:`/`Don't:` (other modules carry full quintuplet per §15.3 convention). `buffer.py` has no `Spec:` line — Task 22 finishes it.
- D7 Task 17 deferred polish: `PartitionTable.snapshot()` returns mutable `set`; could be `frozenset` for type-level immutability. No `__repr__` (will hurt operator CLI dumps). No idempotence test for repeated `add`.
- D7 Task 20 deferred polish: `test-docker` aggregate Makefile target only runs unit+integration; could include `test-e2e-docker` and `test-chaos-docker` for completeness (D8 added the e2e+chaos targets).
- D8 Task 22 plan defect: plan claimed Step-2 ("run tests against the Task 18 stub") yields 5 pass — actually only 4 pass; D7 stub `push` returns False on overflow without appending the new payload (drops new), so `test_overflow_drops_oldest_and_returns_false` fails until prod impl swap. Prod impl correct (drops oldest, appends new). Plan source not amended.
- D8 Task 23 test deviation: `fastapi.testclient.TestClient` swapped for `httpx.AsyncClient` + `httpx.ASGITransport` because `redis_client` conftest fixture lives on pytest-asyncio loop while TestClient spawns its own anyio portal loop — cross-loop futures error fires on `/health` and `/admin/state`. Same endpoints + assertions; test driver only.
- D8 Task 25/26 plan defect: plan-byte-exact tests use literal `window_id=100` / `window_id=200`. Reconciler scans `now_window = int(time.time() // 60)` (epoch-minute, ~29M today) + previous minute only — literal windows never converge. Both tests use dynamic `window = int(time.time() // 60)` instead. Affects partition+heal e2e and chaos convergence proof. Plan source not amended.
- D8 Task 27 plan defect + production gap: chaos test required `socket_connect_timeout=1.0` AND `socket_timeout=1.0` AND polling-loop deadline 15s (not 1.5s sleep) for reliability across reruns in docker-in-docker. Underlying production gap also fixed: `service.py`'s `Redis.from_url` now sets the same fast-fail kwargs (commit `eea9b4a`). Reason: Constitution Art VII degraded-mode buffer cannot engage if relay wedges 9s on TCP connect. EVALSHA→EVAL fallback path under socket_timeout adds ~4-5s end-to-end before the first apply_remote_slot raises.
- D8 Task 28 plan deviation: `scripts/solo-demo.sh` uses `docker run --network host -v ... sync-dev:latest python ...` for steps 3/4 and `make test-chaos-docker` for step 5. Plan-byte-exact bare `python`/`pytest` would fail on host py3.10. The `[0/5]` step builds `sync-dev:latest` if not already present.
- D8 Task 27 chaos test fix-up: 5s polling deadline raced the EVALSHA→EVAL script-load fallback (~4-5s end-to-end). Bumped to 15s with comment explaining the timing. 3/3 stable on rerun.
- Recurring D9 polish: extract `cluster` fixture used by `test_basic_propagation`, `test_partition`, `test_convergence` (3 near-identical 3-region testcontainer fixtures). Extract `make_app` test helper from `test_admin.py` and `test_relay.py` (similar Counter+Transport+Buffer construction).
- D8 untracked artifacts: 14 extra `convergence_*.txt` results in `sync/tests/chaos/results/` from D8-wrap reruns; only the canonical `convergence_20260503-071116.txt` is committed. Either gitignore the rest, prune them, or commit one fresh canonical artifact at PR-merge time.
- `scripts/solo-demo.sh` was syntax-validated (`bash -n`) but NOT run end-to-end. Pre-demo run on a clean clone in D9 or D10 before the dress rehearsal.
- D8 service.py prod gap (now fixed): `_infer_region_from_url` substring match on `("us", "eu", "asia")` is fragile (matches "eustace.example.com" / "busy-host"). Solo-demo URLs work but D9 should harden this for production hostname schemes.

## Execution-mode note (D5 retrospective)

- Subagent-driven workflow (implementer + spec reviewer + code quality reviewer per task) worked through Tasks 1–9. Task 10 implementer subagent crashed mid-step ("internal error"); recovered manually because tests were already written byte-exact to plan and pytest validated behavior — saved one round-trip.
- Two minor plan deviations landed mid-flight, both reviewer-approved: (a) requirements split (runtime vs dev) before Task 2 Dockerfile; (b) `sync/Dockerfile.dev` + Makefile docker targets to handle host Python 3.10 / pyproject `>=3.11` mismatch (no local python install).
- Lint auto-fix at D5 wrap removed 2 unused imports from `conftest.py`. `OwnSlotWriteError` import in `test_counter_redis.py` became used in Task 10 (no fix needed).
- Time: D5 wall-clock ~3 hrs. Subagent dispatch overhead ~50% of wall time. Acceptable for quality bar.

## Execution-mode note (D6 retrospective)

- Subagent-driven workflow held through Tasks 12–15 (4 implementer + 7 reviewer dispatches; Task 15 used a single combined reviewer because the CLI skeleton has no test coverage to split spec vs quality concerns over).
- Two plan deviations, both reviewer-approved: (a) Task 14 `gateway_stub.py` docstring augmented with `Spec:` and `Constitution:` lines because Task 16 wrap-task grep checks both `transport.py` and `gateway_stub.py`; plan code block omitted them. (b) Task 13 TDD discipline violation — disconnect-recovery test passed against the minimal `_pump` (redis-py auto-reconnects pubsub on `CLIENT KILL TYPE pubsub`), so the failing-test-first step never failed. Spec-mandated reconnect loop shipped anyway; test serves as regression guard for harder failure modes (server restart, full TCP teardown).
- D6 wall-clock ~30 min (autonomous mode after user delegated). All 4 wrap gates first-try green.

## Execution-mode note (D7 retrospective)

- Subagent-driven workflow held through Tasks 17–20 (4 implementer + 6 reviewer dispatches + 1 fix-up implementer dispatch on Task 18; Task 20 used a single combined reviewer per Task-15 precedent because the e2e is a single test + tiny Makefile diff). Task 21 wrap ran in main session (5 verification commands, no subagent needed).
- Three reviewer-approved deviations: (a) Task 18 partition check switched from transport-tag to envelope-asserted region (test fixture necessitates; production-equivalent for trusted peers). (b) Task 18 fix-up commit (`ee05c66`) corrected `_handle` to thread transport-tag through to metric labels — original commit accidentally used asserted region for both partition AND metrics. (c) Task 19 reconcile-skip: plan's `if value <= 0: continue` was buggy vs plan's own test 2 (`us=0` for u_0); switched to `get_global` + presence check. Spec reviewer confirmed plan code was wrong; implementer's reading was spec-faithful (§5.reconciler.py + §6 Flow 3 say no value threshold).
- Plan miscount streak holds: D5 +4, D6 +4, D7 +4 (predicted 42 / actual 46).
- D7 wall-clock ~45 min (autonomous mode after user delegated). All 4 wrap gates first-try green; one mid-task reviewer fix-up.

## Execution-mode note (D8 retrospective)

- Subagent-driven workflow held through Tasks 22–28 (7 implementer + 8 reviewer dispatches + 2 fix-up implementer dispatches; Task 26 convergence proof skipped dual review because the proof is its own validation per Constitution Art IX; Task 24 skipped tests because plan declared it integration-tested via Tasks 20/25/26/27). Task 29 wrap ran in main session.
- Six reviewer-approved deviations + 1 production-side fix triggered by chaos diagnosis:
  - **T22:** D7 stub overflow path was buggy (drops new instead of appending); prod impl in this task fixes. Plan claimed Step-2 stub-passes but actually 4/5 — implementer caught it.
  - **T23:** `TestClient` → `httpx.AsyncClient`+`ASGITransport` for cross-loop compat with pytest-asyncio.
  - **T25:** dynamic `int(time.time() // 60)` window instead of literal 100.
  - **T26:** dynamic window again, instead of literal 200.
  - **T27:** test-only `socket_connect_timeout=1.0` + `socket_timeout=1.0`; polling 1.5s → 3.0s → 5.0s → 15.0s as flake forced upward bumps. Production fix (commit `eea9b4a`) added same kwargs to `service.py`'s `Redis.from_url` calls.
  - **T28:** `solo-demo.sh` uses `sync-dev:latest` docker invocations (host py3.10 mismatch).
- D8-wrap chaos rerun surfaced a chaos test flake post-T28: same `test_buffer_fills_when_local_redis_fails` that passed in implementer's verification became reproducibly failing on full-suite rerun. Diagnostic agent traced root cause: redis-py first-attempt read on dead-local socket blocks indefinitely without `socket_timeout`; with it, EVALSHA→EVAL script-load fallback path takes ~4-5s end-to-end in docker-in-docker. 5s deadline raced; bumped to 15s. 3/3 stable rerun.
- Plan miscount streak holds: D5 +4, D6 +4, D7 +4, D8 +9 (predicted 50 / actual 59). D8 increment larger because plan's chaos count was 2 but the implementer wrote 2 separate test files matching plan; the +9 comes from accumulation across the four days.
- D8 wall-clock ~3 hrs (autonomous mode). One reviewer fix-up (T18 metric labels — wait, that was D7; D8 had T27 chaos polling fix-up). Long tail eaten by chaos test diagnosis (~30 min) + waiting on testcontainers across reruns.
- Five real plan defects discovered in D8 alone (T22 stub, T25/T26 windows, T27 timeouts; T18 + T19 from D7 already known). D9 plan should account for plan-source amendments OR explicitly mark plan as historical-only and rely on the handoff doc + this retrospective for source-of-truth.

---

## Resume protocol — read at start of every new session

1. **Confirm branch state.**
   ```bash
   git checkout yashashav/sync-d5-foundation
   git pull origin yashashav/sync-d5-foundation
   git status -sb
   ```
   You should be on the branch with no unexpected drift.

2. **Read the durable trio.** These three files are canonical; everything else points back at them.
   - `docs/sync-constitution.md` — non-negotiable rules. Pay attention to Appendix C Amendment 1.
   - `docs/superpowers/specs/2026-04-25-sync-service-design.md` — design. §15 = handover artifacts.
   - `docs/superpowers/plans/2026-04-30-sync-service-implementation.md` — TDD plan, 29 tasks across D5–D8.

3. **Check this file's "Where we are" section** for the current PDF day and next task.

4. **Read project memory.** `MEMORY.md` in the per-project memory dir indexes user / project / current-work entries.

5. **Skim the plan for the first un-checked `- [ ]` step.** That is your starting task. Do not redo completed tasks.

6. **Dispatch the next implementer subagent** per the subagent-driven-development workflow (one fresh subagent per task; spec reviewer + code quality reviewer between tasks).

---

## Execution decisions locked in

These are settled. Do not re-litigate:

| Decision | Choice | Why |
|---|---|---|
| Owner of cross-region max-merge | sync (peer slots only) | Constitution Art III §6 (single-writer-per-slot) |
| Channel name | `rl:sync:counter` | Contract 2 (PR #8) |
| Gateway hot-path read of `rl:global` | allowed (local Redis only) | Constitution Amendment 1 |
| Coalescing on the sync side | none | Gateway emits one envelope per allowed request |
| Test discipline | TDD (failing test first) | Constitution Art VIII §3 |
| Lint gate | `ruff check sync/` at each day's wrap | Plan's Validation gates section |
| Type-check gate | skipped | cost > value at 4-day budget |
| CI workflow file | deferred to D9 | not blocking the merge gate |
| Session phasing | one PDF day per Claude session, `/clear` between | context-window economy |
| Execution mode | subagent-driven, one implementer + 2 reviewers per task | quality gates per task |

If a future session questions any of these: re-read Constitution Art VI before changing. Constitutional amendments are not casual.

---

## Validation gates per day's wrap

Every wrap task (Tasks 11, 16, 21, 29) runs:

1. **Test gate** — pytest for the layers in scope.
2. **Lint gate** — `ruff check sync/`.
3. **Docstring gate** — `grep -l "^Spec:" sync/<new modules>` to confirm §15.3 module headers.
4. **Push gate** — `git push origin yashashav/sync-d5-foundation`.

If any gate fails, stop and fix before the day's PR.

---

## Session phasing map

| Phase | Calendar (slipped +1 day) | PDF day | Tasks | End state |
|---|---|---|---|---|
| 1 | 2026-05-01 | D5 | 1–11 | crdt + envelope + counter + handover docs; L1 + counter L2 green |
| 2 | 2026-05-02 | D6 | 12–16 | transport + gateway-stub + sync-cli; L2 transport green |
| 3 | 2026-05-03 | D7 | 17–21 | relay + reconciler + first 3-region e2e; L3 propagation green |
| 4 | 2026-05-04 | D8 | 22–29 | buffer + admin + service + chaos proof + solo-demo; all 4 layers green; PR open |
| 5 | 2026-05-05 | D9 | (new plan) | failure-mode drills, team integration, load test, CI workflow |
| 6 | 2026-05-06 | D10 | (new plan) | dress rehearsal, sync-design.md writeup ≥1500 words |

If the schedule slips again, reduce scope before extending dates: defer Layer 4 load test to D9, then defer CI workflow to D10. Do not slip the convergence proof or the all-layers-green gate — those are PDF-required.

Constitution Art IX termination conditions verified by end of Phase 6.

---

## Subagent dispatch rules

- **One fresh subagent per task.** Do not reuse a subagent for two tasks; context pollutes.
- **Implementer first.** Hand it the task's full text + the spec/constitution sections it touches. Subagent runs the TDD loop.
- **Spec compliance reviewer second.** Fresh subagent. Compares the diff against the named spec section. Rejects under-builds and over-builds.
- **Code quality reviewer third.** Fresh subagent. Flags magic numbers, missing docstrings, oversized files, unclear naming.
- A task is not complete until all three pass. Do not ship a task that's only "implementer says done."

---

## Where to update what

| Change type | File |
|---|---|
| Code | `sync/<module>.py` per the plan |
| Test | `sync/tests/<layer>/test_<module>.py` |
| Per-module handover docstring | top of the `.py` file |
| Cross-team navigation | `AGENTS.md` (root) |
| Sync-internal primer | `sync/CONTEXT.md` |
| Architectural rule change | `docs/sync-constitution.md` (requires Amendment per Art VI) |
| Design clarification | `docs/superpowers/specs/2026-04-25-sync-service-design.md` |
| Cross-team contract change | `docs/contracts.md` (requires all-owner sign-off per Art VI) |
| Day plan adjustment | `docs/superpowers/plans/2026-04-30-sync-service-implementation.md` |
| Session-handoff state | this file (`docs/sync-session-handoff.md`) — update "Where we are" + history bullet at end of every session |

---

## End-of-session checklist

Before `/clear`:

1. Day's wrap-task gates green (test + lint + docstring + push).
2. Update this file's "Where we are" section: branch state, current PDF day, next task, tests passing, open PR.
3. Append a one-line history bullet for the session.
4. Update project memory `current_work.md` with the same.
5. `/clear`.
