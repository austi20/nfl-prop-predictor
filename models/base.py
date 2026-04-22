"""Shared data classes for position models."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats


@dataclass
class StatDistribution:
    mean: float
    std: float
    dist_type: str  # 'gamma', 'tweedie', 'poisson', 'normal'

    def prob_over(self, line: float) -> float:
        """P(stat > line) using the fitted distribution."""
        if self.mean <= 0 or self.std <= 0:
            return 0.0

        if self.dist_type == "gamma":
            # Gamma: shape = (mean/std)^2, scale = std^2/mean
            shape = (self.mean / self.std) ** 2
            scale = self.std ** 2 / self.mean
            return float(stats.gamma.sf(line, a=shape, scale=scale))

        elif self.dist_type == "poisson":
            # Poisson: lambda = mean; sf(k) = P(X > k) = P(X >= k+1)
            # Use floor so P(> 0.5) makes sense for integer r.v.
            return float(stats.poisson.sf(int(np.floor(line)), mu=self.mean))

        elif self.dist_type == "tweedie":
            # Approximate as Gamma for sf purposes (reasonable for p in (1,2))
            shape = (self.mean / self.std) ** 2
            scale = self.std ** 2 / self.mean
            return float(stats.gamma.sf(line, a=shape, scale=scale))

        else:  # normal fallback
            return float(stats.norm.sf(line, loc=self.mean, scale=self.std))
