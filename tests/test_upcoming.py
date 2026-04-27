"""Tests for data/upcoming.py — Phase G.5 future-row builder."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from data.upcoming import build_upcoming_row


def _qb_fixture() -> pd.DataFrame:
    """Synthetic weekly QB data: 4 weeks, 6 QBs, opponent-defense gradient.

    BUF defense allows ~400 passing yards/week (weak); MIA allows ~150 (strong).
    QB-X (target) plays SF and faces neutral opponents in weeks 1-3 so we can
    build_upcoming_row at week 4 against either BUF or MIA.
    """
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

    # BUF defense (weak): allows ~400 yds/wk
    for week in (1, 2, 3):
        emit("QB-A", "KC", 2023, week, "BUF", 410, 3, 0, 28, 38)
    # MIA defense (strong): allows ~150 yds/wk
    for week in (1, 2, 3):
        emit("QB-B", "GB", 2023, week, "MIA", 150, 1, 1, 14, 28)
    # Filler so other teams' rolling contexts exist
    for week in (1, 2, 3):
        emit("QB-C", "DEN", 2023, week, "LAC", 250, 2, 1, 22, 33)
        emit("QB-D", "DAL", 2023, week, "NYJ", 270, 2, 1, 23, 34)
    # Target player QB-X on SF, playing easy-ish weeks 1-3
    for week, opp, py in ((1, "DEN", 280), (2, "DAL", 290), (3, "LAC", 270)):
        emit("QB-X", "SF", 2023, week, opp, py, 2, 1, 24, 35)

    return pd.DataFrame(rows)


def test_build_upcoming_row_returns_dict_with_feature_columns():
    weekly = _qb_fixture()
    row = build_upcoming_row(
        "QB-X",
        season=2023,
        week=4,
        position="QB",
        opponent_team="BUF",
        recent_team="SF",
        weekly=weekly,
    )
    assert isinstance(row, dict)
    # Strict-superset check: must include core rolling player features
    for col in (
        "roll_passing_yards",
        "roll_passing_tds",
        "roll_interceptions",
        "roll_completions",
        "roll_attempts",
    ):
        assert col in row, f"missing player rolling column {col!r}"
    # Must include opponent context columns
    assert any(c.startswith("opp_pass_allowed_") for c in row), "no opp context columns"
    # And team context columns
    assert any(c.startswith("team_pass_") for c in row), "no team context columns"


def test_opponent_change_shifts_opp_context_features():
    """Same player + week, swapping BUF (weak D) for MIA (strong D) must change
    the opp_pass_allowed_* features. This is the bug Phase G.5 fixes."""
    weekly = _qb_fixture()
    row_buf = build_upcoming_row(
        "QB-X", season=2023, week=4, position="QB",
        opponent_team="BUF", recent_team="SF", weekly=weekly,
    )
    row_mia = build_upcoming_row(
        "QB-X", season=2023, week=4, position="QB",
        opponent_team="MIA", recent_team="SF", weekly=weekly,
    )

    buf_allowed = row_buf["opp_pass_allowed_passing_yards"]
    mia_allowed = row_mia["opp_pass_allowed_passing_yards"]
    assert buf_allowed > mia_allowed + 100, (
        f"expected BUF allowed >> MIA allowed; got BUF={buf_allowed} MIA={mia_allowed}"
    )


def test_player_rolling_features_match_history():
    """Player-level rolling features for QB-X should reflect QB-X's prior weeks
    (280, 290, 270 → mean 280), independent of upcoming opponent."""
    weekly = _qb_fixture()
    row_buf = build_upcoming_row(
        "QB-X", season=2023, week=4, position="QB",
        opponent_team="BUF", recent_team="SF", weekly=weekly,
    )
    row_mia = build_upcoming_row(
        "QB-X", season=2023, week=4, position="QB",
        opponent_team="MIA", recent_team="SF", weekly=weekly,
    )

    expected = (280 + 290 + 270) / 3.0
    assert row_buf["roll_passing_yards"] == pytest.approx(expected, abs=1.0)
    # Identical regardless of upcoming opponent
    assert row_buf["roll_passing_yards"] == pytest.approx(row_mia["roll_passing_yards"])


def test_weather_passes_through():
    """Optional weather dict should propagate into the row."""
    weekly = _qb_fixture()
    weather = {"temp_f": 22.0, "wind_mph": 18.0, "precip_in": 0.4, "indoor": False}
    row = build_upcoming_row(
        "QB-X", season=2023, week=4, position="QB",
        opponent_team="BUF", recent_team="SF",
        weather=weather, weekly=weekly,
    )
    # weather columns may not be in _feature_cols yet (Phase H1) but should
    # be carried in the dict for downstream consumption.
    assert row.get("temp_f") == 22.0
    assert row.get("wind_mph") == 18.0
    assert row.get("indoor") is False


def test_is_home_override():
    weekly = _qb_fixture()
    row_home = build_upcoming_row(
        "QB-X", season=2023, week=4, position="QB",
        opponent_team="BUF", recent_team="SF", is_home=True, weekly=weekly,
    )
    row_away = build_upcoming_row(
        "QB-X", season=2023, week=4, position="QB",
        opponent_team="BUF", recent_team="SF", is_home=False, weekly=weekly,
    )
    assert row_home["is_home"] == 1.0
    assert row_away["is_home"] == 0.0


def test_unsupported_position_raises():
    weekly = _qb_fixture()
    with pytest.raises(ValueError, match="Unsupported position"):
        build_upcoming_row(
            "QB-X", season=2023, week=4, position="K",
            opponent_team="BUF", recent_team="SF", weekly=weekly,
        )


def test_rb_position_supported():
    """Smoke test that RB position resolves and returns rb-specific features."""
    rng = np.random.default_rng(7)
    rows = []
    for player, team, opp_seq in (
        ("RB-1", "SF", ["BUF", "BUF", "BUF"]),
        ("RB-2", "GB", ["MIA", "MIA", "MIA"]),
    ):
        for week, opp in enumerate(opp_seq, start=1):
            rows.append({
                "player_id": player, "player_name": player,
                "position": "RB", "season": 2023, "week": week,
                "recent_team": team, "opponent_team": opp,
                "rushing_yards": float(rng.integers(60, 140)),
                "carries": float(rng.integers(12, 25)),
                "rushing_tds": float(rng.integers(0, 2)),
                "rushing_epa": 0.0,
            })
    weekly = pd.DataFrame(rows)
    row = build_upcoming_row(
        "RB-1", season=2023, week=4, position="RB",
        opponent_team="MIA", recent_team="SF", weekly=weekly,
    )
    assert "roll_rushing_yards" in row
    assert "roll_carries" in row
    assert any(c.startswith("opp_rush_allowed_") for c in row)


def test_wr_te_position_supported():
    rng = np.random.default_rng(11)
    rows = []
    for player, pos, team, opp in (
        ("WR-1", "WR", "SF", "BUF"),
        ("TE-1", "TE", "GB", "MIA"),
    ):
        for week in range(1, 4):
            rows.append({
                "player_id": player, "player_name": player,
                "position": pos, "season": 2023, "week": week,
                "recent_team": team, "opponent_team": opp,
                "receptions": float(rng.integers(3, 9)),
                "receiving_yards": float(rng.integers(40, 110)),
                "receiving_tds": 0.0,
                "targets": float(rng.integers(5, 12)),
                "target_share": 0.2,
                "air_yards_share": 0.25,
                "wopr": 0.5,
                "receiving_epa": 0.0,
            })
    weekly = pd.DataFrame(rows)
    row = build_upcoming_row(
        "WR-1", season=2023, week=4, position="WR",
        opponent_team="MIA", recent_team="SF", weekly=weekly,
    )
    assert "roll_receptions" in row
    assert "roll_receiving_yards" in row
    assert any(c.startswith("opp_rec_allowed_") for c in row)
