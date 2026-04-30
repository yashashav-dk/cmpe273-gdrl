from __future__ import annotations

import time
from dataclasses import dataclass, field

from metrics_client import REGIONS, TIERS
from policy_writer import PolicyWriter
from predictor import PredictionResult

Features = dict[str, dict[str, float]]

# Aggregate tier-level RPS capacity across all users in a region
TIER_CAPACITY_RPS: dict[str, float] = {
    "free":     60.0,
    "premium":  20.0,
    "internal":  8.0,
}

DEFAULT_LIMITS: dict[str, int] = {"free": 100, "premium": 1000, "internal": 10000}
DEFAULT_BURST:  dict[str, int] = {"free":  20, "premium":  200, "internal":  2000}

HYSTERESIS_SECONDS    = 60    # don't reverse a decision within this window
SPIKE_THRESHOLD       = 0.80  # predicted > 80% of capacity → throttle free
RECOVERY_THRESHOLD    = 0.50  # predicted < 50% of capacity → restore free
NOISY_NEIGHBOR_SHARE  = 0.30  # single user_id > 30% of tier traffic → override


@dataclass
class _TierState:
    limit_per_minute: int
    written_at: float = field(default_factory=time.time)
    throttled: bool = False


class Decider:
    """Rules-based v1 policy engine.

    Three rules per tick:
      1. Spike throttle  — free predicted > 80% capacity → cut free limit 30%
      2. Spike recovery  — free drops below 50% capacity + was throttled → restore
      3. Noisy neighbor  — single user > 30% of tier traffic → per-user override

    Hysteresis (60 s) prevents oscillation between throttle and recovery.
    """

    def __init__(self, writer: PolicyWriter) -> None:
        self._writer = writer
        self._state: dict[str, dict[str, _TierState]] = {
            r: {t: _TierState(limit_per_minute=DEFAULT_LIMITS[t]) for t in TIERS}
            for r in REGIONS
        }
        self._overrides: dict[str, float] = {}  # user_id → last override timestamp

    def decide(
        self,
        features: Features,
        predictions: PredictionResult,
        top_users: dict[str, dict[str, tuple[str, float]]],
    ) -> None:
        now = time.time()
        for region in REGIONS:
            self._check_capacity(region, predictions.get(region, {}), now)
            self._check_noisy_neighbor(region, top_users.get(region, {}), now)

    # ── Rule 1 + 2: capacity-based free tier throttle / recovery ─────────────

    def _check_capacity(
        self,
        region: str,
        preds: dict,
        now: float,
    ) -> None:
        free_pred = preds.get("free")
        if free_pred is None:
            return
        predicted_rps = free_pred.rps
        capacity = TIER_CAPACITY_RPS["free"]
        state = self._state[region]["free"]
        age = now - state.written_at

        if predicted_rps > SPIKE_THRESHOLD * capacity and not state.throttled and age > HYSTERESIS_SECONDS:
            new_limit = max(10, int(state.limit_per_minute * 0.70))
            self._writer.write_policy(
                region=region,
                tier="free",
                limit_per_minute=new_limit,
                burst=max(5, new_limit // 5),
                reason=f"predicted_spike_{region}_free_{predicted_rps:.1f}_rps",
            )
            self._state[region]["free"] = _TierState(
                limit_per_minute=new_limit, written_at=now, throttled=True
            )
            print(f"  [decider] {region}/free throttled → {new_limit} req/min  (predicted {predicted_rps:.1f} rps)")

        elif state.throttled and predicted_rps < RECOVERY_THRESHOLD * capacity and age > HYSTERESIS_SECONDS:
            self._writer.write_policy(
                region=region,
                tier="free",
                limit_per_minute=DEFAULT_LIMITS["free"],
                burst=DEFAULT_BURST["free"],
                reason=f"recovery_{region}_free_{predicted_rps:.1f}_rps",
            )
            self._state[region]["free"] = _TierState(
                limit_per_minute=DEFAULT_LIMITS["free"], written_at=now, throttled=False
            )
            print(f"  [decider] {region}/free restored → {DEFAULT_LIMITS['free']} req/min")

    # ── Rule 3: noisy neighbor override ──────────────────────────────────────

    def _check_noisy_neighbor(
        self,
        region: str,
        top_users: dict[str, tuple[str, float]],
        now: float,
    ) -> None:
        for tier, (user_id, share) in top_users.items():
            if share > NOISY_NEIGHBOR_SHARE:
                last = self._overrides.get(user_id, 0.0)
                if (now - last) > HYSTERESIS_SECONDS:
                    self._writer.write_override(
                        user_id=user_id,
                        limit_per_minute=5,
                        reason=f"noisy_neighbor_{user_id}_{tier}_{region}_{share:.0%}_of_tier",
                    )
                    self._overrides[user_id] = now
                    print(f"  [decider] override {user_id} — {share:.0%} of {region}/{tier} traffic")
