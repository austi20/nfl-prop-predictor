from __future__ import annotations

import pandas as pd
import pytest

from data import game_context as gc


@pytest.fixture
def _fake_schedule(monkeypatch):
    """Two games: DET home favourite in a dome, ATL road dog outdoors."""
    sched = pd.DataFrame(
        [
            dict(
                game_id="2026_01_ATL_PIT", season=2026, week=1, game_type="REG",
                home_team="PIT", away_team="ATL", home_score=None, away_score=None,
                total_line=42.5, spread_line=3.0,  # positive -> home (PIT) favoured by 3
                home_coach="Mike Tomlin", away_coach="Raheem Morris",
                home_rest=7, away_rest=7, roof="outdoors", stadium="Acrisure",
                div_game=0,
            ),
            dict(
                game_id="2026_01_NO_DET", season=2026, week=1, game_type="REG",
                home_team="DET", away_team="NO", home_score=None, away_score=None,
                total_line=49.5, spread_line=7.0,  # DET favoured by 7
                home_coach="Dan Campbell", away_coach="Kellen Moore",
                home_rest=7, away_rest=4, roof="dome", stadium="Ford Field",
                div_game=0,
            ),
            dict(
                game_id="2025_05_KC_LV", season=2025, week=5, game_type="REG",
                home_team="LV", away_team="KC", home_score=17, away_score=31,
                total_line=45.0, spread_line=6.5,
                home_coach="Antonio Pierce", away_coach="Andy Reid",
                home_rest=7, away_rest=7, roof="outdoors", stadium="Allegiant",
                div_game=1,
            ),
        ]
    )
    monkeypatch.setattr(gc, "load_schedules", lambda years: sched[sched.season.isin(years)])
    gc.game_context_frame.cache_clear()
    gc.coach_points_per_game.cache_clear()
    return sched


def test_implied_points_from_total_and_spread(_fake_schedule):
    det = gc.context_for((2026,), season=2026, week=1, team="DET")
    assert det["is_home"] == 1
    # total 49.5, spread +7 (home) -> DET 28.25, NO 21.25
    assert det["team_implied"] == pytest.approx(28.25)
    assert det["opp_implied"] == pytest.approx(21.25)
    assert det["team_spread"] == pytest.approx(-7.0)  # favourite -> negative
    assert det["roof"] == "dome"

    no = gc.context_for((2026,), season=2026, week=1, team="NO")
    assert no["is_home"] == 0
    assert no["team_implied"] == pytest.approx(21.25)
    assert no["team_spread"] == pytest.approx(7.0)  # dog -> positive
    assert no["rest"] == 4.0  # short week


def test_road_dog_context(_fake_schedule):
    atl = gc.context_for((2026,), season=2026, week=1, team="ATL")
    assert atl["is_home"] == 0
    assert atl["team_spread"] == pytest.approx(3.0)  # PIT favoured by 3 -> ATL +3
    assert atl["team_implied"] == pytest.approx(42.5 / 2 - 3.0 / 2)
    assert atl["coach"] == "Raheem Morris"


def test_is_home_map_and_missing_game(_fake_schedule):
    hm = gc.is_home_map((2026,))
    assert hm[(2026, 1, "DET")] == 1
    assert hm[(2026, 1, "ATL")] == 0
    assert gc.context_for((2026,), season=2026, week=9, team="DET") is None


def test_coach_ppg_only_counts_completed_games(_fake_schedule):
    ppg = gc.coach_points_per_game((2025, 2026))
    # only the 2025 game has a score; Andy Reid scored 31 there
    assert ppg["Andy Reid"] == (31.0, 1)
    assert "Dan Campbell" not in ppg  # 2026 game has no score yet
