from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from metrics_client import REGIONS, TIERS

Features = dict[str, dict[str, float]]


@dataclass
class Prediction:
    rps: float      # forecast for next window
    is_spike: bool  # current > 2x forecast — traffic already above predicted baseline
    anomaly: bool = False  # IsolationForest flag — statistically unusual for this series


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


class HoltWintersPredictor:
    """Holt-Winters triple exponential smoothing — handles trend + seasonality.

    Falls back to EWMA until 2 full seasonal cycles are available (< min_fit samples).

    Refitting HW happens every `retrain_every` ticks; forecasts from each fit are
    cached and consumed one-step-at-a-time between refits so per-tick latency stays low.

    seasonal_periods=30 assumes a 10s tick interval and a ~5-minute diurnal cycle
    matching Prathamesh's sine-wave overlay in the simulator.
    """

    def __init__(
        self,
        seasonal_periods: int = 30,
        max_history: int = 120,
        retrain_every: int = 5,
        ewma_alpha: float = 0.3,
    ) -> None:
        self._sp = seasonal_periods
        self._min_fit = 2 * seasonal_periods
        self._retrain_every = retrain_every
        self._alpha = ewma_alpha

        self._history: dict[str, dict[str, deque[float]]] = {
            r: {t: deque(maxlen=max_history) for t in TIERS} for r in REGIONS
        }
        # Multi-step forecasts cached between refits
        self._hw_cache: dict[str, dict[str, deque[float]]] = {
            r: {t: deque() for t in TIERS} for r in REGIONS
        }
        self._tick: dict[str, dict[str, int]] = {
            r: {t: 0 for t in TIERS} for r in REGIONS
        }
        self._ewma: dict[str, dict[str, float]] = {
            r: {t: 0.0 for t in TIERS} for r in REGIONS
        }

    def warm_up(self, history: dict[str, list[float]]) -> None:
        """Seed history buffers and EWMA state from historical time series."""
        for key, series in history.items():
            if "/" not in key or not series:
                continue
            region, tier = key.split("/", 1)
            if region not in self._history or tier not in self._history[region]:
                continue
            for val in series:
                self._history[region][tier].append(val)
            ewma = series[0]
            for val in series[1:]:
                ewma = self._alpha * val + (1 - self._alpha) * ewma
            self._ewma[region][tier] = ewma

    def update(self, features: Features) -> PredictionResult:
        """Feed current tick, return Holt-Winters (or EWMA) forecast per region+tier."""
        result: PredictionResult = {}
        for region in REGIONS:
            f = features.get(region, {})
            result[region] = {}
            for tier in TIERS:
                current = f.get(f"{tier}_rps", 0.0)
                buf = self._history[region][tier]
                buf.append(current)
                tick = self._tick[region][tier]
                self._tick[region][tier] = tick + 1

                predicted = self._next_forecast(region, tier, buf, tick)
                is_spike = predicted > 0 and current > 2 * predicted

                result[region][tier] = Prediction(
                    rps=round(predicted, 2),
                    is_spike=is_spike,
                )
        return result

    def _next_forecast(
        self, region: str, tier: str, buf: deque[float], tick: int
    ) -> float:
        if len(buf) < self._min_fit:
            return self._ewma_step(region, tier, buf[-1] if buf else 0.0)

        cache = self._hw_cache[region][tier]
        if tick % self._retrain_every == 0 or not cache:
            self._refit_hw(region, tier, buf)
            cache = self._hw_cache[region][tier]

        if cache:
            return cache.popleft()
        return self._ewma_step(region, tier, buf[-1])

    def _refit_hw(self, region: str, tier: str, buf: deque[float]) -> None:
        try:
            series = np.array(list(buf), dtype=float)
            fit = ExponentialSmoothing(
                series,
                trend="add",
                seasonal="add",
                seasonal_periods=self._sp,
                initialization_method="estimated",
            ).fit(optimized=True, disp=False)
            forecasts = fit.forecast(self._retrain_every)
            cache = self._hw_cache[region][tier]
            cache.clear()
            for v in forecasts:
                cache.append(max(0.0, float(v)))
        except Exception:
            pass  # leave cache empty — _next_forecast falls back to EWMA

    def _ewma_step(self, region: str, tier: str, current: float) -> float:
        prev = self._ewma[region][tier]
        new = self._alpha * current + (1 - self._alpha) * prev if prev > 0 else current
        self._ewma[region][tier] = new
        return new
