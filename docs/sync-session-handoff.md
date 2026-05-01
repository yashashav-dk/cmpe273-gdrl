# Sync service — session handoff

**Last updated:** 2026-05-01. Update the timestamp + "Where we are" section at the end of every Claude session.

This file is the single starting point for any LLM session resuming sync-service work. Read it first; it routes to everything else.

---

## What this project is

CMPE 273 group project — a 3-region geo-distributed AI rate limiter. Yashashav owns the **sync service**: a stateless Python relay that subscribes to `rl:sync:counter` on three Redis instances and max-merges peer slots into the local `rl:global:{tier}:{user_id}:{window_id}` hash.

Teammates: Atharva (`agent/`), Prathamesh (`simulator/`), Nikhil (`gateway/`). All four components live in this repo. Cross-team boundaries in `AGENTS.md` (when present) and `docs/contracts.md` (always).

---

## Where we are (update this section every session)

**Branch:** `yashashav/sync-d5-foundation`
**Current PDF day:** D5 (not yet started). Calendar slipped by one day; D5 work begins 2026-05-01.
**Next task:** Task 1 — Scaffold sync package (`docs/superpowers/plans/2026-04-30-sync-service-implementation.md`).
**Code in `sync/`:** none yet (only `.gitkeep`).
**Tests passing:** 0 / ~50 planned.
**Open PR:** none yet (D8 task 29 opens it).

History:
- 2026-04-26: project brief, naming, sync constitution, sync design spec committed.
- 2026-04-28: Constitution Amendment 1 + spec §4/§5/§6 rewritten to track merged gateway behavior; spec §14 (compressed timeline) + §15 (handover artifacts) added.
- 2026-04-30: plan written; ruff/mypy/CI gates rationalised; session phasing locked in; this handoff file added.
- **Next session:** begin Phase 1 (Tasks 1–11) per the plan.

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
