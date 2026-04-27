"""Tests for predict(future_row=...) — Phase G.5 end-to-end.

Confirms that swapping the upcoming opponent via build_upcoming_row produces
visibly different distributions, and that the legacy `opp_team=...` path still
works for back-compat (with a DeprecationWarning).
"""

from __future__ import annotations

import warnings
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from data.upcoming import build_upcoming_row
from models.qb import QBModel


def _qb_training_fixture(seed: int = 17) -> pd.DataFrame:
    """8 weeks × 6 QBs with a strong opp-defense gradient.

    BUF defense: weak (allows ~410 yds/wk).
    MIA defense: strong (allows ~150 yds/wk).
    The GLM should learn opp_pass_allowed_passing_yards as a positive driver.
    """
    rng = np.random.default_rng(seed)
    rows: list[dict] = []

    def emit(player_id, team, season, week, opp, py, pt, intc, comp, att):
        rows.append({
            "player_id": player_id,
            "player_name": player_id,
            "position": "QB",
            "season": season,
            "week": week,
            "recent_team": team,
            "opponent_team": opp,
            "passing_yards": float(py),
            "passing_tds": float(pt),
            "interceptions": float(intc),
            "completions": float(comp),
            "attempts": float(att),
            "sacks": 2.0,
            "passing_air_yards": float(py) * 0.7,
            "passing_epa": 0.1,
            "dakota": 0.0,
        })

    # Strong gradient: weeks 1..8, two QBs hammer BUF (weak D), two starve at MIA (strong D)
    for week in range(1, 9):
        emit("QB-A", "KC", 2023, week, "BUF", 400 + rng.normal(0, 15), 3, 0, 28, 38)
        emit("QB-E", "PIT", 2023, week, "BUF", 410 + rng.normal(0, 15), 3, 0, 28, 38)
        emit("QB-B", "GB", 2023, week, "MIA", 150 + rng.normal(0, 10), 1, 1, 14, 28)
        emit("QB-F", "TEN", 2023, week, "MIA", 145 + rng.normal(0, 10), 1, 1, 14, 28)
        # Filler so all teams have offensive context
        emit("QB-C", "DEN", 2023, week, "LAC", 250 + rng.normal(0, 20), 2, 1, 22, 33)
        emit("QB-D", "DAL", 2023, week, "NYJ", 260 + rng.normal(0, 20), 2, 1, 22, 33)
        # Target QB-X on SF, plays neutral opps
        emit("QB-X", "SF", 2023, week, "DEN", 280 + rng.normal(0, 20), 2, 1, 24, 35)

    return pd.DataFrame(rows)


def test_future_row_with_different_opponent_changes_distribution():
    weekly = _qb_training_fixture()

    with patch("data.nflverse_loader.load_weekly", return_value=weekly):
        model = QBModel()
        model.fit([2023])

    row_buf = build_upcoming_row(
        "QB-X", season=2023, week=10, position="QB",
        opponent_team="BUF", recent_team="SF", weekly=weekly,
    )
    row_mia = build_upcoming_row(
        "QB-X", season=2023, week=10, position="QB",
        opponent_team="MIA", recent_team="SF", weekly=weekly,
    )

    pred_buf = model.predict("QB-X", week=10, season=2023, future_row=row_buf)
    pred_mia = model.predict("QB-X", week=10, season=2023, future_row=row_mia)

    buf_mean = pred_buf["passing_yards"].mean
    mia_mean = pred_mia["passing_yards"].mean

    # Distributions must differ noticeably with this strong synthetic gradient.
    assert abs(buf_mean - mia_mean) > 5.0, (
        f"BUF vs MIA passing_yards predictions look identical: "
        f"BUF={buf_mean:.2f} MIA={mia_mean:.2f}"
    )


def test_future_row_with_same_opponent_is_stable():
    """Calling predict twice with the same future_row yields identical means."""
    weekly = _qb_training_fixture()
    with patch("data.nflverse_loader.load_weekly", return_value=weekly):
        model = QBModel()
        model.fit([2023])

    row = build_upcoming_row(
        "QB-X", season=2023, week=10, position="QB",
        opponent_team="BUF", recent_team="SF", weekly=weekly,
    )
    p1 = model.predict("QB-X", week=10, season=2023, future_row=row)
    p2 = model.predict("QB-X", week=10, season=2023, future_row=row)

    for stat in ("passing_yards", "passing_tds", "interceptions", "completions"):
        assert p1[stat].mean == pytest.approx(p2[stat].mean)


def test_legacy_opp_team_path_still_works_with_deprecation_warning():
    weekly = _qb_training_fixture()
    with patch("data.nflverse_loader.load_weekly", return_value=weekly):
        model = QBModel()
        model.fit([2023])

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = model.predict("QB-X", week=10, season=2023, opp_team="BUF")

    assert "passing_yards" in result
    assert result["passing_yards"].mean > 0

    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deprecations, "expected DeprecationWarning when using opp_team without future_row"
    assert "future_row" in str(deprecations[0].message)


def test_no_args_no_deprecation_warning():
    """Calling predict with neither opp_team nor future_row (e.g. cold model)
    should not emit DeprecationWarning."""
    model = QBModel()  # not fitted — cold path
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = model.predict("QB-X", week=10, season=2023)

    assert "passing_yards" in result
    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert not deprecations, (
        "DeprecationWarning should not fire when neither opp_team nor future_row is set"
    )


def test_future_row_overrides_legacy_opp_team():
    """When both opp_team and future_row are passed, future_row wins and no
    DeprecationWarning fires."""
    weekly = _qb_training_fixture()
    with patch("data.nflverse_loader.load_weekly", return_value=weekly):
        model = QBModel()
        model.fit([2023])

    row = build_upcoming_row(
        "QB-X", season=2023, week=10, position="QB",
        opponent_team="MIA", recent_team="SF", weekly=weekly,
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # opp_team value here is intentionally inconsistent — future_row should win
        result = model.predict(
            "QB-X", week=10, season=2023, opp_team="BUF", future_row=row,
        )

    assert "passing_yards" in result
    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert not deprecations
