from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class GameSimResult:
    home_scores: np.ndarray  # shape (n_sims,)
    away_scores: np.ndarray  # shape (n_sims,)
    home_win_prob: float
    over_prob: float          # P(home + away > total)


def simulate_game(
    home_team: str,
    away_team: str,
    spread: float,      # positive = home favored (home - away spread)
    total: float,       # over/under total points
    n_sims: int = 10_000,
    rng: np.random.Generator | None = None,
) -> GameSimResult:
    if rng is None:
        rng = np.random.default_rng()

    home_mean = (total + spread) / 2
    away_mean = (total - spread) / 2

    home_std = home_mean * 0.20
    away_std = away_mean * 0.20

    home_scores = np.clip(rng.normal(home_mean, home_std, n_sims), 0, None)
    away_scores = np.clip(rng.normal(away_mean, away_std, n_sims), 0, None)

    home_win_prob = float((home_scores > away_scores).mean())
    over_prob = float(((home_scores + away_scores) > total).mean())

    return GameSimResult(
        home_scores=home_scores,
        away_scores=away_scores,
        home_win_prob=home_win_prob,
        over_prob=over_prob,
    )
