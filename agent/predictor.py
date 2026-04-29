from __future__ import annotations

from dataclasses import dataclass

from metrics_client import REGIONS, TIERS

Features = dict[str, dict[str, float]]


@dataclass
class Prediction:
    rps: float      # EWMA-smoothed forecast for the next window
    is_spike: bool  # current > 2x EWMA — traffic already spiking relative to baseline


PredictionResult = dict[str, dict[str, Prediction]]  # {region: {tier: Prediction}}


class EWMAPredictor:
    """Single-exponential smoothing with spike detection.

    Forecast: ŷ_{t+1} = α·x_t + (1−α)·ŷ_t   (alpha=0.3 → slow decay, prefers stability)
    Spike:    x_t > 2·ŷ_t                      (current already double the smoothed baseline)

    warm_up() seeds state from 30 min of history so the first live tick isn't
    starting from zero — without it, EWMA underestimates for the first ~10 ticks.
    """

    def __init__(self, alpha: float = 0.3) -> None:
        self._alpha = alpha
        self._ewma: dict[str, dict[str, float]] = {
            r: {t: 0.0 for t in TIERS} for r in REGIONS
        }

    def warm_up(self, history: dict[str, list[float]]) -> None:
        """Seed EWMA state from historical time series to eliminate cold-start lag."""
        for key, series in history.items():
            if "/" not in key or not series:
                continue
            region, tier = key.split("/", 1)
            if region not in self._ewma or tier not in self._ewma[region]:
                continue
            ewma = series[0]
            for val in series[1:]:
                ewma = self._alpha * val + (1 - self._alpha) * ewma
            self._ewma[region][tier] = ewma

    def update(self, features: Features) -> PredictionResult:
        """Feed current tick's features into EWMA, return per-region+tier predictions."""
        result: PredictionResult = {}
        for region in REGIONS:
            f = features.get(region, {})
            result[region] = {}
            for tier in TIERS:
                current = f.get(f"{tier}_rps", 0.0)
                prev = self._ewma[region][tier]
                # Bootstrap: if EWMA never seeded, skip smoothing for this tick
                new_ewma = (
                    self._alpha * current + (1 - self._alpha) * prev if prev > 0 else current
                )
                self._ewma[region][tier] = new_ewma
                is_spike = new_ewma > 0 and current > 2 * new_ewma
                result[region][tier] = Prediction(rps=round(new_ewma, 2), is_spike=is_spike)
        return result
