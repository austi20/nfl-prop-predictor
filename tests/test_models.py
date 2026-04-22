from __future__ import annotations
from unittest.mock import patch
import numpy as np
import pytest
from models.base import StatDistribution
from models.qb import QBModel
from models.rb import RBModel
from models.wr_te import WRTEModel
from models.game_sim import simulate_game, GameSimResult


def test_stat_distribution_prob_over_gamma():
    dist = StatDistribution(mean=100.0, std=30.0, dist_type="gamma")
    assert 0.3 < dist.prob_over(100.0) < 0.7
    assert dist.prob_over(200.0) < 0.05
    assert dist.prob_over(0.0) > 0.95


def test_stat_distribution_prob_over_poisson():
    dist = StatDistribution(mean=5.0, std=5.0, dist_type="poisson")
    assert 0.3 < dist.prob_over(5.0) < 0.7
    assert dist.prob_over(20.0) < 0.01
    assert dist.prob_over(-1.0) > 0.99


def test_stat_distribution_prob_over_zero_mean():
    dist = StatDistribution(mean=0.0, std=1.0, dist_type="gamma")
    assert dist.prob_over(1.0) == 0.0


def test_qb_model_predict_no_fit():
    model = QBModel()
    result = model.predict("player_1", week=5, season=2023, opp_team="KC")
    assert isinstance(result, dict)
    for key in ["passing_yards", "passing_tds", "interceptions", "completions"]:
        assert key in result
        assert isinstance(result[key], StatDistribution)


def test_rb_model_predict_no_fit():
    model = RBModel()
    result = model.predict("player_1", week=5, season=2023, opp_team="KC")
    assert isinstance(result, dict)
    for key in ["rushing_yards", "carries", "rushing_tds"]:
        assert key in result
        assert isinstance(result[key], StatDistribution)


def test_wr_te_model_predict_no_fit():
    model = WRTEModel()
    result = model.predict("player_1", week=5, season=2023, opp_team="KC")
    assert isinstance(result, dict)
    for key in ["receptions", "receiving_yards", "receiving_tds"]:
        assert key in result
        assert isinstance(result[key], StatDistribution)


def test_qb_model_fit_and_predict():
    import pandas as pd

    n = 50
    rng = np.random.default_rng(42)
    fake_weekly = pd.DataFrame({
        "player_id": ["p1"] * n,
        "player_name": ["Test QB"] * n,
        "position": ["QB"] * n,
        "season": [2023] * n,
        "week": list(range(1, n + 1)),
        "recent_team": ["KC"] * n,
        "passing_yards": rng.integers(150, 400, n).astype(float),
        "passing_tds": rng.integers(0, 5, n).astype(float),
        "interceptions": rng.integers(0, 3, n).astype(float),
        "completions": rng.integers(15, 35, n).astype(float),
        "attempts": rng.integers(25, 45, n).astype(float),
        "sacks": rng.integers(0, 4, n).astype(float),
        "air_yards_completed": rng.uniform(100, 300, n),
    })

    with patch("data.nflverse_loader.load_weekly", return_value=fake_weekly):
        model = QBModel()
        model.fit([2023])
        result = model.predict("p1", week=10, season=2023, opp_team="LAC")

    assert "passing_yards" in result
    assert result["passing_yards"].mean > 0
    assert result["passing_yards"].prob_over(100.0) > 0


def test_simulate_game_basic():
    rng = np.random.default_rng(42)
    result = simulate_game("KC", "LAC", spread=7.0, total=48.0, n_sims=10_000, rng=rng)

    assert 0 < result.home_win_prob < 1
    assert 0 < result.over_prob < 1
    assert result.home_win_prob > 0.55
    assert len(result.home_scores) == 10_000
    assert len(result.away_scores) == 10_000
    assert abs(result.home_scores.mean() - 27.5) < 2.0
    assert abs(result.away_scores.mean() - 20.5) < 2.0


def test_simulate_game_even_matchup():
    rng = np.random.default_rng(0)
    result = simulate_game("KC", "LAC", spread=0.0, total=44.0, n_sims=50_000, rng=rng)

    assert abs(result.home_win_prob - 0.5) < 0.05
