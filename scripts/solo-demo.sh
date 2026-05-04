#!/usr/bin/env bash
# solo-demo.sh — single-command demo runner for the sync service.
#
# Per Constitution Art IX termination conditions, this script must run
# end-to-end on a clean clone with only docker installed on the host.
#
# Plan deviation (documented):
#   The plan's Step 3/4/5 invoke bare `python` and `pytest`. Sync requires
#   Python 3.11+, but the team's reference host runs 3.10. The D5 retro
#   solved this by introducing `sync/Dockerfile.dev` (image `sync-dev:latest`)
#   plus `make *-docker` targets. To keep the clean-clone goal intact, this
#   script invokes those same docker targets instead of bare host python.
#   The redises are port-mapped to host (6379/6380/6381) and the syncs to
#   9101/9102/9103, so `--network host` lets the sync-dev container reach
#   them at `localhost:<port>` as the plan-verbatim Python expected.
#
# Boots: 3 redis + 3 sync (docker compose).
# Drives: gateway-stub against US redis (50 allow events).
# Inspects: state across all 3 syncs via sync_cli.
# Proves: convergence (Layer 3 partition heals < 5s).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$ROOT/infra/docker-compose.sync-only.yml"
DEV_IMAGE="sync-dev:latest"

echo "[0/5] ensuring sync-dev image is present ..."
if ! docker image inspect "$DEV_IMAGE" >/dev/null 2>&1; then
  make -C "$ROOT" dev-image
fi

echo "[1/5] booting 3 Redis + 3 sync ..."
docker compose -f "$COMPOSE_FILE" up -d --build

echo "[2/5] waiting for /health on each sync ..."
for port in 9101 9102 9103; do
  for _ in $(seq 1 30); do
    if curl -sf "http://localhost:${port}/health" >/dev/null 2>&1; then break; fi
    sleep 1
  done
done

echo "[3/5] running gateway-stub against US Redis (50 allow events) ..."
docker run --rm --network host -v "$ROOT:/app" -w /app "$DEV_IMAGE" python -c "
import asyncio
from redis.asyncio import Redis
from sync.dev.gateway_stub import GatewayStub
async def main():
    r = Redis(host='localhost', port=6379)
    stub = GatewayStub('us', r)
    for _ in range(50):
        await stub.allow_request('free', 'u_demo', 1)
    await r.aclose()
asyncio.run(main())
"

echo "[4/5] inspecting state across all 3 syncs ..."
docker run --rm --network host -v "$ROOT:/app" -w /app "$DEV_IMAGE" \
  python -m sync.dev.sync_cli inspect u_demo --tier free

echo "[5/5] running convergence proof ..."
make -C "$ROOT" test-chaos-docker

echo "demo complete."
