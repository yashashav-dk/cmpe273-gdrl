# gdrl — Traffic Simulator

**Owner:** Prathamesh  
**Stack:** Python 3.11, asyncio, httpx, click  
**Targets:** Three regional API gateways on `localhost:8081` (us), `8082` (eu), `8083` (asia)

---

## Setup

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r simulator/requirements.txt
```

Gateways and Redis must be running:

```sh
docker compose up -d
```

---

## CLI — `python -m simulator`

### `steady` — Baseline traffic

Mixed user population (70% free / 20% premium / 10% internal).  
Inter-arrival times follow a **Poisson process** (Exp(rps)) for realistic burstiness.

```sh
# Single region
python -m simulator steady --rps 100 --duration 60 --target-region us

# Round-robin across all three regions
python -m simulator steady --rps 300 --duration 60 --target-region all

# Weighted distribution
python -m simulator steady --rps 300 --duration 60 --distribution us:0.5,eu:0.3,asia:0.2

# Diurnal pattern — full 24-hour sine wave (realistic long-run)
python -m simulator steady --rps 100 --duration 3600 --target-region all --diurnal

# Diurnal pattern — compressed 2-minute demo cycle
python -m simulator steady --rps 100 --duration 120 --target-region all --diurnal --diurnal-period 120
```

| Flag | Default | Description |
|---|---|---|
| `--rps` | 100 | Target requests per second (mean of Poisson process) |
| `--duration` | 60 | Duration in seconds |
| `--target-region` | us | `us \| eu \| asia \| all` |
| `--distribution` | — | Weighted split, e.g. `us:0.5,eu:0.3,asia:0.2`. Overrides `--target-region`. |
| `--diurnal` | off | Enable sine-wave RPS envelope (30%–170% of `--rps`) |
| `--diurnal-period` | 86400 | Cycle length in seconds. Use `120` for a fast demo cycle. |

### `spike` — Product launch simulation

```sh
# 10x spike on US after 30s of baseline
python -m simulator spike --base 100 --peak 1000 --at 30 --target-region us

# Custom spike duration and total runtime
python -m simulator spike --base 50 --peak 500 --at 20 --spike-duration 60 --duration 150 --target-region eu
```

| Flag | Default | Description |
|---|---|---|
| `--base` | 100 | Baseline RPS |
| `--peak` | 1000 | Peak RPS during spike |
| `--at` | 30 | Seconds before spike begins |
| `--spike-duration` | 30 | Duration of the spike (seconds) |
| `--duration` | 120 | Total run time (seconds) |
| `--target-region` | us | Region to spike |

### `noisy` — Noisy neighbor

```sh
# One user sends 90% of traffic
python -m simulator noisy --culprit free_00001 --share 0.9 --rps 100 --target-region us

# With distribution across regions
python -m simulator noisy --culprit free_00001 --share 0.7 --rps 200 --distribution us:0.6,eu:0.4
```

| Flag | Default | Description |
|---|---|---|
| `--culprit` | free_00001 | `user_id` of the noisy neighbor |
| `--share` | 0.9 | Fraction of traffic from culprit (0.0–1.0) |
| `--rps` | 100 | Requests per second |
| `--duration` | 60 | Duration in seconds |
| `--target-region` | us | `us \| eu \| asia \| all` |
| `--distribution` | — | Weighted split. Overrides `--target-region`. |

---

## Named Scenarios — `python -m simulator.scenarios`

Pre-configured end-to-end scenarios for the demo. Each runs with one command.

```sh
python -m simulator.scenarios <scenario>
```

### `global_steady`

300 req/s balanced 1:1:1 across US / EU / Asia for 5 minutes. Use as baseline before any spike demo.

```sh
python -m simulator.scenarios global_steady
```

### `product_launch`

Simulates a US product launch: 30s warmup at 100 RPS → 2min spike at 1000 RPS → 60s cooldown at 100 RPS.

```sh
python -m simulator.scenarios product_launch
```

### `noisy_neighbor`

`free_00001` sends 50% of 200 RPS to the US gateway for 2 minutes. Atharv's agent should detect and write an override within ~30 seconds.

```sh
python -m simulator.scenarios noisy_neighbor
```

### `region_failover`

300 RPS balanced across all regions for 30s, then kills the US gateway container (`docker stop gateway-us`) and reroutes to EU + Asia for the remaining 90s. Restarts the gateway at the end.

**Requires Docker socket access.**

```sh
python -m simulator.scenarios region_failover
```

---

## Output

Progress is written to **stderr** so stdout can be piped:

```sh
# Count requests
python -m simulator steady --rps 10 --duration 5 2>/dev/null | wc -l

# Phase summaries on stderr
[steady] sent=500 errors=0 actual_rps=99.8  |  allowed=42 denied=458 http_err=0 (8% pass)
```

---

## User populations

Generated once with `seed=42` and pickled to `simulator/data/populations.pkl`:

| Tier | Count | user_id format |
|---|---|---|
| free | 10,000 | `free_00000` … `free_09999` |
| premium | 100 | `premium_000` … `premium_099` |
| internal | 5 | `internal_0` … `internal_4` |

Delete `simulator/data/populations.pkl` to regenerate with a new seed.

---

## Gateway ports

| Region | Port | Container |
|---|---|---|
| us | 8081 | `gateway-us` |
| eu | 8082 | `gateway-eu` |
| asia | 8083 | `gateway-asia` |
