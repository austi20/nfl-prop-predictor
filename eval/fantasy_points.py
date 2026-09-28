"""Fantasy point scoring and probability helpers.

This module intentionally stays small and stateless: callers provide model
distributions plus context multipliers, and the helpers return deterministic
fantasy projections.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

import numpy as np

from eval.fantasy_spread import rescale
from models.base import StatDistribution

ScoringMode = Literal["full_ppr", "half_ppr"]

SCORING_PROFILES: dict[ScoringMode, dict[str, float]] = {
    "full_ppr": {
        "passing_yards": 0.04,
        "passing_tds": 4.0,
        "interceptions": -2.0,
        "rushing_yards": 0.1,
        "rushing_tds": 6.0,
        "receptions": 1.0,
        "receiving_yards": 0.1,
        "receiving_tds": 6.0,
    },
    "half_ppr": {
        "passing_yards": 0.04,
        "passing_tds": 4.0,
        "interceptions": -2.0,
        "rushing_yards": 0.1,
        "rushing_tds": 6.0,
        "receptions": 0.5,
        "receiving_yards": 0.1,
        "receiving_tds": 6.0,
    },
}

ZERO_WEIGHT_STATS = ("carries", "completions")

# Boom = beat the projection by half again; bust = score half of it or less.
BOOM_MULTIPLIER = 1.5
BUST_MULTIPLIER = 0.5


def relative_cutoffs(projected_points: float) -> tuple[float, float]:
    if projected_points <= 0:
        return 0.0, 0.0
    return projected_points * BOOM_MULTIPLIER, projected_points * BUST_MULTIPLIER


@dataclass(frozen=True)
class FantasyProjection:
    projected_points: float
    median_points: float
    p10_points: float
    p90_points: float
    boom_probability: float
    bust_probability: float
    boom_cutoff: float
    bust_cutoff: float
    scoring_mode: ScoringMode
    components: list[dict[str, float | str]]
    omitted_stats: list[str]


def scoring_weights(scoring_mode: ScoringMode) -> dict[str, float]:
    try:
        return SCORING_PROFILES[scoring_mode]
    except KeyError as exc:
        raise ValueError(f"Unsupported fantasy scoring mode: {scoring_mode}") from exc


def stable_simulation_seed(
    player_id: str,
    season: int,
    week: int,
    scoring_mode: ScoringMode,
) -> int:
    raw = f"{player_id}|{season}|{week}|{scoring_mode}".encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def _sample_distribution(
    distribution: StatDistribution,
    rng: np.random.Generator,
    size: int,
) -> np.ndarray:
    return distribution.sample(rng, size)


def project_fantasy_points(
    distributions: dict[str, StatDistribution],
    *,
    scoring_mode: ScoringMode = "full_ppr",
    stat_multipliers: dict[str, float] | None = None,
    seed: int | None = None,
    simulations: int = 5000,
    calib=None,
    total_sd: float | None = None,
) -> FantasyProjection:
    weights = scoring_weights(scoring_mode)
    multipliers = stat_multipliers or {}
    rng = np.random.default_rng(seed)

    cv_floor_frac = float(getattr(calib, "cv_floor_frac", 0.0)) if calib is not None else 0.0
    yard_cv = float(getattr(calib, "yard_cv", 0.55)) if calib is not None else 0.55
    count_cv = float(getattr(calib, "count_cv", 0.85)) if calib is not None else 0.85

    total_samples = np.zeros(simulations, dtype=float)
    components: list[dict[str, float | str]] = []
    omitted_stats: list[str] = [
        f"{stat}: zero fantasy weight"
        for stat in ZERO_WEIGHT_STATS
    ]

    for stat, weight in weights.items():
        distribution = distributions.get(stat)
        if distribution is None:
            omitted_stats.append(f"{stat}: no model distribution available")
            continue

        multiplier = max(float(multipliers.get(stat, 1.0)), 0.0)
        adj_mean = float(distribution.mean) * multiplier
        adj_std = float(distribution.std) * multiplier
        if calib is not None and cv_floor_frac > 0 and adj_mean > 0:
            cv = yard_cv if stat in ("passing_yards", "rushing_yards", "receiving_yards") else count_cv
            adj_std = max(adj_std, cv * cv_floor_frac * adj_mean)
        adjusted = StatDistribution(
            mean=adj_mean,
            std=adj_std,
            dist_type=distribution.dist_type,
        )
        component_points = float(adjusted.mean) * weight
        components.append(
            {
                "stat": stat,
                "mean": float(adjusted.mean),
                "weight": float(weight),
                "projected_points": component_points,
                "adjustment_multiplier": float(multiplier),
                "dist_type": adjusted.dist_type,
            }
        )
        total_samples += _sample_distribution(adjusted, rng, simulations) * weight

    projected_points = float(sum(float(component["projected_points"]) for component in components))
    # Summing independent stat draws gives every player the same relative
    # spread; the measured per player spread replaces it when known.
    if total_sd is not None and simulations > 0:
        total_samples = rescale(total_samples, projected_points, total_sd)
    boom_cutoff, bust_cutoff = relative_cutoffs(projected_points)
    if projected_points <= 0:
        median = p10 = p90 = projected_points
        boom, bust = 0.0, 1.0
    elif simulations <= 0:
        median = p10 = p90 = projected_points
        boom, bust = 0.0, 0.0
    else:
        median = float(np.quantile(total_samples, 0.5))
        p10 = float(np.quantile(total_samples, 0.1))
        p90 = float(np.quantile(total_samples, 0.9))
        boom = float(np.mean(total_samples >= boom_cutoff))
        bust = float(np.mean(total_samples <= bust_cutoff))

    return FantasyProjection(
        projected_points=projected_points,
        median_points=median,
        p10_points=p10,
        p90_points=p90,
        boom_probability=boom,
        bust_probability=bust,
        boom_cutoff=boom_cutoff,
        bust_cutoff=bust_cutoff,
        scoring_mode=scoring_mode,
        components=components,
        omitted_stats=omitted_stats,
    )
