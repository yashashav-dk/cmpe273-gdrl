# Project Naming

**Working name:** `gdrl` (Geo-Distributed Rate Limiter)
**Decision deadline:** Day 7 (post-integration test, before writeups begin Day 11)
**Why a placeholder:** zero naming politics during build, course-coded for easy chat reference, forces explicit rename PR before submission.

## Final-name candidates (shortlist of 12, collision-checked)

Each name is one-word, evocative of the system's behavior, and clean of major OSS / commercial collisions in the distributed-systems / rate-limiting / observability space.

### Strongest semantic match
1. **Triveni** *(Sanskrit — "braiding of three rivers")* — three regions merging counter state via CRDT. Triveni Sangam is the sacred confluence of Ganges, Yamuna, and the invisible Saraswati. Maps directly to G-Counter (3 region slots merging).
   *Tagline: "Three streams, one flow."*

2. **Anemoi** *(Greek — three named wind gods, one per direction)* — Boreas / Notos / Zephyros, one per region. Logo writes itself.
   *Tagline: "Three winds, one sky."*

3. **Penstock** *(Scots English — mill-gate that regulates water flow)* — most precise engineering metaphor. A penstock IS a rate-limiting hydraulic gate.
   *Tagline: "The gate that opens just enough."*

### Strong alternates
4. **Triskele** *(Greek — three-armed rotational symbol)* — three rotational arms = three regions, motion = sync.
5. **Mascaret** *(French — tidal bore, a wave moving upstream ahead of the tide)* — captures the predictive AI angle.
6. **Headrace** *(Old English — mill channel feeding the wheel)* — the channel between traffic and decision.
7. **Eunomia** *(Greek — goddess of "good order")* — eventual consistency = order without central rule.
8. **Stilling** *(hydraulic engineering — basin that damps turbulent flow)* — traffic shaping = literal stilling.
9. **Skopos** *(Greek — "watcher, target")* — for the AI agent angle.
10. **Aequora** *(Latin — "calm seas, level surface")* — balance + ocean basins.
11. **Limen** *(Latin — "threshold")* — every request crosses the line.
12. **Tula** *(Sanskrit — "scales, balance")* — four letters, root of zodiac sign Libra.

## Hard skip (collisions found)
Aperture (FluxNinja rate limiter), Sentinel (Alibaba flow control), Cadence (Uber), Flux (CNCF), Helix (Apache), Lighthouse, Iris, Tessera, Prism, Kairos, Argus, Hermes.

## Voting protocol (Day 7)
1. Each teammate writes one sentence under their preferred name in this file.
2. Async +1 in chat for tied candidates.
3. If still tied: highest-vote run-off, simple majority. Owner of the project (everyone collectively) makes final call.
4. Rename PR same day. Find-replace across `pyproject.toml`, `docker-compose.yml`, `README.md`, `gdrl/` folder, plus update of all three core docs. ~6 files.

## Why renaming is cheap
Folder structure does not embed `gdrl` deeply. Component folders are functional (`gateway/`, `sync/`, `simulator/`, `agent/`). Top-level codename appears only in:
- `pyproject.toml` package name
- `docker-compose.yml` project label
- `README.md` title
- `Makefile` image tag prefix
- `docs/*.md` headers
- One namespace import in Python (`from gdrl.sync import ...`)

Single PR, ~30-minute change.

## Working-name guidance during build
- Use `gdrl` everywhere a project name is needed — repo, README, package names, slide deck titles.
- Never embed it in cross-region keys or wire formats (those are versioned via `v: 1` envelope and don't change with rename).
- If you find yourself wanting to bikeshed the name before Day 7, **stop and code instead.**
