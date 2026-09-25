from __future__ import annotations

import numpy as np
import pandas as pd

from eval import fantasy_spread


def _history(fp: list[float], tds: list[float] | None = None) -> pd.DataFrame:
    return pd.DataFrame({
        "fantasy_points_ppr": fp,
        "receiving_tds": tds or [0.0] * len(fp),
    })


def test_spread_grows_slower_than_the_projection():
    """Measured exponent is ~0.45 for WR: doubling the mean must not double the sd."""
    low = fantasy_spread.target_sd("WR", 8.0, 8, 0.8, 0.2)
    high = fantasy_spread.target_sd("WR", 16.0, 8, 0.8, 0.2)
    assert low < high < 2 * low


def test_a_volatile_player_gets_a_wider_spread_at_the_same_projection():
    steady = fantasy_spread.target_sd("WR", 14.0, 8, 0.3, 0.2)
    boom_or_bust = fantasy_spread.target_sd("WR", 14.0, 8, 1.2, 0.2)
    assert boom_or_bust > steady


def test_a_thin_history_falls_back_to_the_position_cv():
    none = fantasy_spread.target_sd("RB", 12.0, 0, 0.0, 0.0)
    pos_cv = fantasy_spread._load()["position_cv"]["RB"]
    exact = fantasy_spread.target_sd("RB", 12.0, 8, pos_cv, 0.0)
    assert none is not None and abs(none - exact) < 1e-9


def test_unknown_position_or_empty_mean_gives_none():
    assert fantasy_spread.target_sd("K", 8.0, 8, 0.5, 0.0) is None
    assert fantasy_spread.target_sd("WR", 0.0, 8, 0.5, 0.0) is None


def test_player_volatility_reads_the_last_eight_games():
    games, cv, td_share = fantasy_spread.player_volatility(
        _history([10.0] * 4 + [20.0, 0.0, 20.0, 0.0, 20.0, 0.0, 20.0, 0.0], [0.0] * 11 + [1.0])
    )
    assert games == 8
    assert cv > 0.9  # alternating 20 / 0 over the last eight
    assert 0.0 < td_share < 0.1


def test_rescale_keeps_the_mean_and_hits_the_target_sd():
    samples = np.random.default_rng(0).gamma(2.0, 5.0, 5000)
    out = fantasy_spread.rescale(samples, 10.0, 3.0)
    assert abs(out.mean() - 10.0) < 1e-9
    assert abs(out.std() - 3.0) < 1e-9
