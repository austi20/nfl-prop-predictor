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

POSITION_CUTOFFS: dict[str, tuple[float, float]] = {
    "QB": (24.0, 14.0),
    "RB": (20.0, 8.0),
    "WR": (20.0, 7.0),
    "TE": (14.0, 5.0),
}


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


def position_cutoffs(position: str) -> tuple[float, float]:
    normalized = position.upper().strip()
    if normalized not in POSITION_CUTOFFS:
        raise ValueError(f"Unsupported fantasy position: {position}")
    return POSITION_CUTOFFS[normalized]


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
    position: str,
    scoring_mode: ScoringMode = "full_ppr",
    stat_multipliers: dict[str, float] | None = None,
    seed: int | None = None,
    simulations: int = 5000,
) -> FantasyProjection:
    weights = scoring_weights(scoring_mode)
    boom_cutoff, bust_cutoff = position_cutoffs(position)
    multipliers = stat_multipliers or {}
    rng = np.random.default_rng(seed)

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
        adjusted = StatDistribution(
            mean=float(distribution.mean) * multiplier,
            std=float(distribution.std) * multiplier,
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
    if simulations <= 0:
        median = projected_points
        p10 = projected_points
        p90 = projected_points
        boom = 1.0 if projected_points >= boom_cutoff else 0.0
        bust = 1.0 if projected_points <= bust_cutoff else 0.0
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
