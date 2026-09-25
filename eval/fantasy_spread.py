"""How far a player's week can land from his projection.

The simulation used to give every player the same coefficient of variation, so
boom and bust were a function of the projection alone. Measured on 2018-2023
(`scripts/diag/boom_bust_drivers.py`), the spread grows with roughly the square
root of the projection, is wider for players who have been volatile, and moves
with how much of a player's scoring comes from touchdowns. Game total, spread
and dome showed no effect on the spread; they move the projection instead.

    log sd = const + a * log(mean) + b * log(shrunk CV) + c * TD share
"""
from __future__ import annotations

import json
import math
from functools import lru_cache

import numpy as np
import pandas as pd

from data.nflverse_loader import bundle_root

_SPREAD_FILE = bundle_root() / "models" / "fantasy_spread.json"
_TRAIL = 8  # games of history, same window as the trailing projection
_TD_POINTS = {"passing_tds": 4.0, "rushing_tds": 6.0, "receiving_tds": 6.0}


@lru_cache(maxsize=1)
def _load() -> dict:
    try:
        return json.loads(_SPREAD_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def player_volatility(history: pd.DataFrame) -> tuple[int, float, float]:
    """(games, own CV, TD share of points) over the player's last 8 games."""
    if history.empty or "fantasy_points_ppr" not in history.columns:
        return 0, 0.0, 0.0
    recent = history.tail(_TRAIL)
    fp = recent["fantasy_points_ppr"].fillna(0.0).to_numpy(dtype=float)
    total = float(fp.sum())
    if len(fp) < 2 or total <= 0:
        return len(fp), 0.0, 0.0
    cv = float(fp.std(ddof=1) / fp.mean())
    td_points = 0.0
    for stat, points in _TD_POINTS.items():
        if stat in recent.columns:
            td_points += float(recent[stat].fillna(0.0).sum()) * points
    return len(fp), cv, td_points / total


def target_sd(position: str, mean: float, games: int, own_cv: float, td_share: float) -> float | None:
    """Standard deviation of this week's fantasy points, or None if unknown."""
    config = _load()
    coef = config.get("positions", {}).get(position.upper())
    pos_cv = config.get("position_cv", {}).get(position.upper())
    if coef is None or pos_cv is None or mean <= 0:
        return None
    k = float(config.get("k_shrink", 8.0))
    own = min(max(own_cv, 0.05), 3.0) if games >= 2 else pos_cv
    cv = (games * own + k * pos_cv) / (games + k)
    log_sd = (
        coef["const"]
        + coef["log_mean"] * math.log(mean)
        + coef["log_cv"] * math.log(cv)
        + coef["td_share"] * min(max(td_share, 0.0), 1.0)
    )
    return float(math.exp(log_sd))


def rescale(samples: np.ndarray, mean: float, sd: float) -> np.ndarray:
    """Stretch simulated totals to `sd` around `mean`, keeping their shape."""
    current = float(samples.std())
    if current <= 1e-9:
        return samples
    return mean + (samples - float(samples.mean())) * (sd / current)
