from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from eval.prop_pricer import (
    PropCalibrator,
    build_paper_trade_picks,
    edge,
    fair_price_to_american,
    implied_prob,
    price_prop,
    reliability_diagram,
)
from models.base import StatDistribution


# ---------------------------------------------------------------------------
# implied_prob
# ---------------------------------------------------------------------------

def test_implied_prob_negative_odds():
    # -110 -> 110/210 = 0.52381
    p = implied_prob(-110)
    assert abs(p - 110 / 210) < 1e-4


def test_implied_prob_positive_odds():
    # +150 -> 100/250 = 0.40
    p = implied_prob(150)
    assert abs(p - 100 / 250) < 1e-4


def test_implied_prob_even():
    # -100 or +100 -> 0.50
    assert abs(implied_prob(-100) - 0.5) < 1e-4
    assert abs(implied_prob(100) - 0.5) < 1e-4


# ---------------------------------------------------------------------------
# fair_price_to_american
# ---------------------------------------------------------------------------

def test_fair_price_to_american_favorite():
    # prob > 0.5 should give negative American odds
    odds = fair_price_to_american(0.6)
    assert odds < 0


def test_fair_price_to_american_underdog():
    # prob < 0.5 should give positive American odds
    odds = fair_price_to_american(0.4)
    assert odds > 0


def test_fair_price_to_american_roundtrip():
    # implied_prob(fair_price_to_american(p)) should recover p (<= ~0.5e-3; integer
    # American lines cannot match arbitrary probabilities to 1e-4)
    for p in [0.35, 0.5, 0.65, 0.72]:
        recovered = implied_prob(fair_price_to_american(p))
        assert abs(recovered - p) < 0.0005


# ---------------------------------------------------------------------------
# edge
# ---------------------------------------------------------------------------

def test_edge_positive():
    # calibrated 60%, book 52.38% (-110) -> positive edge
    e = edge(calibrated_prob=0.60, book_implied_prob=implied_prob(-110))
    assert e > 0


def test_edge_negative():
    # calibrated 45%, book 52.38% -> negative edge
    e = edge(calibrated_prob=0.45, book_implied_prob=implied_prob(-110))
    assert e < 0


def test_edge_zero():
    e = edge(calibrated_prob=0.50, book_implied_prob=0.50)
    assert abs(e) < 1e-9


# ---------------------------------------------------------------------------
# PropCalibrator - fit + calibrate
# ---------------------------------------------------------------------------

def _fake_calibration_data(n: int = 200, seed: int = 42):
    rng = np.random.default_rng(seed)
    raw = rng.uniform(0.2, 0.8, n)
    # Outcomes biased toward raw (makes calibration meaningful)
    outcomes = (rng.uniform(size=n) < raw).astype(float)
    return raw, outcomes


def test_calibrator_isotonic_fit_and_calibrate():
    raw, outcomes = _fake_calibration_data()
    cal = PropCalibrator(method="isotonic")
    cal.fit(raw, outcomes)
    result = cal.calibrate(np.array([0.3, 0.5, 0.7]))
    assert result.shape == (3,)
    assert (result >= 0).all() and (result <= 1).all()


def test_calibrator_platt_fit_and_calibrate():
    raw, outcomes = _fake_calibration_data()
    cal = PropCalibrator(method="platt")
    cal.fit(raw, outcomes)
    result = cal.calibrate(np.array([0.3, 0.5, 0.7]))
    assert result.shape == (3,)
    assert (result >= 0).all() and (result <= 1).all()


def test_calibrator_scalar_input():
    raw, outcomes = _fake_calibration_data()
    cal = PropCalibrator(method="isotonic").fit(raw, outcomes)
    result = cal.calibrate(0.55)
    assert isinstance(result, float)
    assert 0.0 <= result <= 1.0


def test_calibrator_save_load(tmp_path):
    raw, outcomes = _fake_calibration_data()
    cal = PropCalibrator(method="isotonic").fit(raw, outcomes)

    path = tmp_path / "calibrator.joblib"
    cal.save(path)
    loaded = PropCalibrator.load(path)

    inp = np.array([0.3, 0.5, 0.7])
    np.testing.assert_allclose(cal.calibrate(inp), loaded.calibrate(inp), rtol=1e-6)


def test_calibrator_not_fitted_raises():
    cal = PropCalibrator()
    with pytest.raises(RuntimeError):
        cal.calibrate(0.5)


# ---------------------------------------------------------------------------
# reliability_diagram
# ---------------------------------------------------------------------------

def test_reliability_diagram_returns_stats():
    raw, outcomes = _fake_calibration_data(n=500)
    stats = reliability_diagram(raw, outcomes, n_bins=10, save_path=None)
    assert "bin_means" in stats
    assert "bin_fracs" in stats
    assert "ece" in stats  # Expected Calibration Error
    assert len(stats["bin_means"]) == len(stats["bin_fracs"])
    assert stats["ece"] >= 0.0


def test_reliability_diagram_saves_file(tmp_path):
    raw, outcomes = _fake_calibration_data(n=300)
    path = tmp_path / "reliability.png"
    reliability_diagram(raw, outcomes, n_bins=10, save_path=path)
    assert path.exists()


# ---------------------------------------------------------------------------
# price_prop - end-to-end
# ---------------------------------------------------------------------------

def test_price_prop_basic():
    dist = StatDistribution(mean=280.0, std=60.0, dist_type="gamma")
    cal = PropCalibrator(method="isotonic").fit(*_fake_calibration_data())

    result = price_prop(
        dist=dist,
        line=250.0,
        book_odds=-110,
        calibrator=cal,
    )

    assert "raw_prob" in result
    assert "calibrated_prob" in result
    assert "book_implied_prob" in result
    assert "edge" in result
    assert "fair_american" in result
    assert 0.0 <= result["raw_prob"] <= 1.0
    assert 0.0 <= result["calibrated_prob"] <= 1.0
    assert isinstance(result["edge"], float)


def test_price_prop_no_calibrator():
    # calibrator=None -> calibrated_prob == raw_prob
    dist = StatDistribution(mean=100.0, std=20.0, dist_type="gamma")
    result = price_prop(dist=dist, line=90.0, book_odds=-110, calibrator=None)
    assert abs(result["calibrated_prob"] - result["raw_prob"]) < 1e-9


def test_build_paper_trade_picks_applies_caps_and_reports_skips():
    priced_rows = pd.DataFrame([
        {
            "player_id": "qb1",
            "season": 2024,
            "week": 1,
            "stat": "passing_yards",
            "line": 250.5,
            "raw_prob": 0.65,
            "actual_value": 275.0,
            "book": "book_a",
            "over_odds": -110,
            "under_odds": -110,
            "game_id": "g1",
            "recent_team": "KC",
            "opponent_team": "LAC",
        },
        {
            "player_id": "qb1",
            "season": 2024,
            "week": 1,
            "stat": "completions",
            "line": 24.5,
            "raw_prob": 0.64,
            "actual_value": 28.0,
            "book": "book_a",
            "over_odds": -110,
            "under_odds": -110,
            "game_id": "g1",
            "recent_team": "KC",
            "opponent_team": "LAC",
        },
        {
            "player_id": "rb1",
            "season": 2024,
            "week": 1,
            "stat": "rushing_yards",
            "line": 68.5,
            "raw_prob": 0.62,
            "actual_value": 55.0,
            "book": "book_b",
            "over_odds": -110,
            "under_odds": -110,
            "game_id": "g1",
            "recent_team": "KC",
            "opponent_team": "LAC",
        },
        {
            "player_id": "wr1",
            "season": 2024,
            "week": 1,
            "stat": "receiving_yards",
            "line": 70.5,
            "raw_prob": 0.60,
            "actual_value": 73.0,
            "book": "book_c",
            "over_odds": -110,
            "under_odds": -110,
            "game_id": "g2",
            "recent_team": "KC",
            "opponent_team": "DEN",
        },
        {
            "player_id": "te1",
            "season": 2024,
            "week": 1,
            "stat": "receiving_tds",
            "line": 0.5,
            "raw_prob": 0.53,
            "actual_value": 1.0,
            "book": "book_d",
            "over_odds": -110,
            "under_odds": -110,
            "game_id": "g3",
            "recent_team": "KC",
            "opponent_team": "DEN",
        },
    ])

    picks, metadata = build_paper_trade_picks(
        priced_rows,
        min_edge=0.05,
        stake=1.0,
        max_picks_per_week=2,
        max_picks_per_player=1,
        max_picks_per_game=1,
        return_metadata=True,
    )

    assert len(picks) == 2
    assert metadata["skipped_rows"]["max_picks_per_player"] == 1
    assert metadata["skipped_rows"]["max_picks_per_game"] == 1
    assert metadata["skipped_rows"]["edge_threshold"] == 1
