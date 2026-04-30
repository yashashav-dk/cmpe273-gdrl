from __future__ import annotations

import json
import time
import uuid
from typing import Any

import redis

from decision_log import DecisionLog

# One Redis per region — matches docker-compose ports
_REDIS_HOSTS: dict[str, tuple[str, int]] = {
    "us":   ("localhost", 6379),
    "eu":   ("localhost", 6380),
    "asia": ("localhost", 6381),
}

# Long enough to survive brief agent outages (Day 9 requirement)
_POLICY_TTL = 300   # seconds
_OVERRIDE_TTL = 120  # seconds — shorter, overrides are more surgical


class PolicyWriter:
    def __init__(self, log: DecisionLog | None = None) -> None:
        self._log = log or DecisionLog()
        self._clients: dict[str, redis.Redis] = {}
        for region, (host, port) in _REDIS_HOSTS.items():
            try:
                r: redis.Redis = redis.Redis(host=host, port=port, decode_responses=True)
                r.ping()
                self._clients[region] = r
            except Exception:
                print(f"[policy_writer] Redis {region} unreachable — writes will be logged only")

    def write_policy(
        self,
        region: str,
        tier: str,
        limit_per_minute: int,
        burst: int,
        reason: str,
        ttl_seconds: int = _POLICY_TTL,
    ) -> dict[str, Any]:
        policy: dict[str, Any] = {
            "policy_id":        f"pol_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
            "region":           region,
            "tier":             tier,
            "limit_per_minute": limit_per_minute,
            "burst":            burst,
            "ttl_seconds":      ttl_seconds,
            "reason":           reason,
            "created_at":       time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        client = self._clients.get(region)
        if client:
            client.setex(f"policy:{region}:{tier}", ttl_seconds, json.dumps(policy))
        self._log.append(policy)
        return policy

    def write_override(
        self,
        user_id: str,
        limit_per_minute: int,
        reason: str,
        ttl_seconds: int = _OVERRIDE_TTL,
    ) -> dict[str, Any]:
        override: dict[str, Any] = {
            "policy_id":        f"ovr_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
            "user_id":          user_id,
            "limit_per_minute": limit_per_minute,
            "ttl_seconds":      ttl_seconds,
            "reason":           reason,
            "created_at":       time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        # Override beats tier policy everywhere — write to all regions
        for client in self._clients.values():
            try:
                client.setex(f"override:{user_id}", ttl_seconds, json.dumps(override))
            except Exception:
                pass
        self._log.append(override)
        return override
