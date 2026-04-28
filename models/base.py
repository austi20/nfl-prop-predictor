"""Shared data classes for position models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import stats


@dataclass
class StatDistribution:
    mean: float
    std: float
    dist_type: str  # 'gamma', 'tweedie', 'poisson', 'normal', ...
    quantiles: dict[float, float] | None = None
    samples: tuple[float, ...] | None = None
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_samples(
        cls,
        samples: np.ndarray | list[float],
        *,
        dist_type: str = "empirical",
    ) -> "StatDistribution":
        arr = np.clip(np.asarray(samples, dtype=float).ravel(), 0.0, None)
        if arr.size == 0:
            return cls(mean=0.0, std=0.0, dist_type=dist_type)

        quantile_levels = (0.1, 0.25, 0.5, 0.75, 0.9)
        quantiles = {q: float(np.quantile(arr, q)) for q in quantile_levels}
        return cls(
            mean=float(arr.mean()),
            std=float(arr.std(ddof=0)),
            dist_type=dist_type,
            quantiles=quantiles,
            samples=tuple(float(x) for x in arr.tolist()),
        )

    def _non_negative_support(self) -> bool:
        return self.dist_type in {
            "gamma",
            "tweedie",
            "poisson",
            "negative_binomial",
            "zero_inflated_poisson",
            "zero_inflated_negative_binomial",
            "quantile",
            "empirical",
        }

    def _nbinom_shape_prob(self, mean: float) -> tuple[float, float]:
        alpha = max(float(self.params.get("alpha", 0.0)), 1e-9)
        shape = max(1.0 / alpha, 1e-9)
        prob = shape / (shape + max(mean, 1e-9))
        return shape, prob

    def _quantile_knots(self) -> tuple[np.ndarray, np.ndarray]:
        raw = self.quantiles or {}
        if not raw:
            return np.array([0.0, 1.0], dtype=float), np.array([0.0, max(self.mean, 0.0)], dtype=float)

        probs = np.array(sorted(float(q) for q in raw), dtype=float)
        values = np.array([max(float(raw[q]), 0.0) for q in probs], dtype=float)
        values = np.maximum.accumulate(values)

        if len(values) >= 2:
            left_slope = (values[1] - values[0]) / max(probs[1] - probs[0], 1e-6)
            right_slope = (values[-1] - values[-2]) / max(probs[-1] - probs[-2], 1e-6)
            right_tail = max(values[-1] + right_slope * (1.0 - probs[-1]), values[-1])
        else:
            left_slope = max(values[0] / max(probs[0], 1e-6), 0.0)
            right_tail = max(values[0] + left_slope * (1.0 - probs[0]), values[0])

        left_value = max(values[0] - left_slope * probs[0], 0.0)
        probs = np.concatenate(([0.0], probs, [1.0]))
        values = np.concatenate(([left_value], values, [right_tail]))
        values = np.maximum.accumulate(values)
        return probs, values

    def _quantile_cdf(self, line: float) -> float:
        probs, values = self._quantile_knots()
        if line <= values[0]:
            return 0.0
        if line >= values[-1]:
            return 1.0
        return float(np.interp(line, values, probs))

    def prob_over(self, line: float) -> float:
        """P(stat > line) using the fitted distribution."""
        if self.samples:
            arr = np.asarray(self.samples, dtype=float)
            if arr.size == 0:
                return 0.0
            return float(np.mean(arr > line))

        if self.quantiles and self.dist_type == "quantile":
            return float(np.clip(1.0 - self._quantile_cdf(line), 0.0, 1.0))

        if self._non_negative_support() and line < 0:
            return 1.0

        if self.mean <= 0:
            return 0.0

        std = max(self.std, 0.0)

        if self.dist_type == "gamma":
            if std <= 0:
                return 0.0
            shape = (self.mean / std) ** 2
            scale = std**2 / self.mean
            return float(stats.gamma.sf(line, a=shape, scale=scale))

        if self.dist_type == "poisson":
            return float(stats.poisson.sf(int(np.floor(line)), mu=self.mean))

        if self.dist_type == "negative_binomial":
            shape, prob = self._nbinom_shape_prob(self.mean)
            return float(stats.nbinom.sf(int(np.floor(line)), shape, prob))

        if self.dist_type == "zero_inflated_poisson":
            zero_inflation = float(np.clip(self.params.get("zero_inflation", 0.0), 0.0, 0.999))
            component_mean = max(float(self.params.get("component_mean", self.mean)), 1e-9)
            return float((1.0 - zero_inflation) * stats.poisson.sf(int(np.floor(line)), mu=component_mean))

        if self.dist_type == "zero_inflated_negative_binomial":
            zero_inflation = float(np.clip(self.params.get("zero_inflation", 0.0), 0.0, 0.999))
            component_mean = max(float(self.params.get("component_mean", self.mean)), 1e-9)
            shape, prob = self._nbinom_shape_prob(component_mean)
            return float((1.0 - zero_inflation) * stats.nbinom.sf(int(np.floor(line)), shape, prob))

        if self.dist_type == "tweedie":
            if std <= 0:
                return 0.0
            shape = (self.mean / std) ** 2
            scale = std**2 / self.mean
            return float(stats.gamma.sf(line, a=shape, scale=scale))

        if std <= 0:
            return 0.0
        return float(stats.norm.sf(line, loc=self.mean, scale=std))

    def sample(self, rng: np.random.Generator, size: int) -> np.ndarray:
        if size <= 0:
            return np.zeros(0, dtype=float)

        if self.samples:
            arr = np.asarray(self.samples, dtype=float)
            if arr.size == 0:
                return np.zeros(size, dtype=float)
            idx = rng.integers(0, arr.size, size=size)
            return arr[idx].astype(float)

        if self.quantiles and self.dist_type == "quantile":
            probs, values = self._quantile_knots()
            draws = rng.uniform(0.0, 1.0, size=size)
            return np.interp(draws, probs, values).astype(float)

        mean = max(float(self.mean), 0.0)
        std = max(float(self.std), 0.0)
        if mean <= 0.0:
            return np.zeros(size, dtype=float)

        if self.dist_type == "poisson":
            return rng.poisson(lam=mean, size=size).astype(float)

        if self.dist_type == "negative_binomial":
            shape, prob = self._nbinom_shape_prob(mean)
            return rng.negative_binomial(shape, prob, size=size).astype(float)

        if self.dist_type == "zero_inflated_poisson":
            zero_inflation = float(np.clip(self.params.get("zero_inflation", 0.0), 0.0, 0.999))
            component_mean = max(float(self.params.get("component_mean", mean)), 1e-9)
            mask = rng.uniform(0.0, 1.0, size=size) < zero_inflation
            draws = rng.poisson(lam=component_mean, size=size).astype(float)
            draws[mask] = 0.0
            return draws

        if self.dist_type == "zero_inflated_negative_binomial":
            zero_inflation = float(np.clip(self.params.get("zero_inflation", 0.0), 0.0, 0.999))
            component_mean = max(float(self.params.get("component_mean", mean)), 1e-9)
            shape, prob = self._nbinom_shape_prob(component_mean)
            mask = rng.uniform(0.0, 1.0, size=size) < zero_inflation
            draws = rng.negative_binomial(shape, prob, size=size).astype(float)
            draws[mask] = 0.0
            return draws

        if self.dist_type in {"gamma", "tweedie"}:
            if std <= 0.0:
                return np.full(size, mean, dtype=float)
            shape = max((mean / std) ** 2, 1e-6)
            scale = max((std**2) / max(mean, 1e-6), 1e-6)
            return rng.gamma(shape=shape, scale=scale, size=size).astype(float)

        return np.clip(rng.normal(loc=mean, scale=max(std, 1e-6), size=size), 0.0, None).astype(float)
