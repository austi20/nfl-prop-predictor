from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from api.services import nflverse_service as svc


@pytest.fixture
def weekly_roster(monkeypatch):
    """A roster frame the way nflverse ships one: a row per player per week."""
    rows = []
    for week in (1, 2):
        rows += [
            {
                "week": week,
                "player_id": "00-0001",
                "player_name": "Jared Goff",
                "team": "DET",
                "position": "QB",
                "depth_chart_position": "QB",
                "jersey_number": 16,
                "status": "ACT",
                "years_exp": 10,
                "headshot_url": "",
            },
            {
                "week": week,
                "player_id": "00-0002",
                "player_name": "Sam LaPorta",
                "team": "DET",
                "position": "TE",
                "depth_chart_position": "TE",
                "jersey_number": 87,
                "status": "ACT",
                "years_exp": 3,
                "headshot_url": "",
            },
        ]
    monkeypatch.setattr(svc, "_roster_frame", lambda season: pd.DataFrame(rows))


def test_get_roster_returns_each_player_once_mid_season(weekly_roster):
    players, week = svc.get_roster(2026, team="DET")

    assert week == 2
    assert [p.player_id for p in players] == ["00-0001", "00-0002"]


def test_get_roster_reads_the_newest_week_not_the_first(monkeypatch):
    """A player who changed team since Week 1 reads with the current team."""
    rows = [
        {"week": 1, "player_id": "00-0003", "player_name": "Moved Player", "team": "NYJ",
         "position": "WR", "depth_chart_position": "WR", "jersey_number": 5,
         "status": "ACT", "years_exp": 4, "headshot_url": ""},
        {"week": 2, "player_id": "00-0003", "player_name": "Moved Player", "team": "SEA",
         "position": "WR", "depth_chart_position": "WR", "jersey_number": 5,
         "status": "ACT", "years_exp": 4, "headshot_url": ""},
    ]
    monkeypatch.setattr(svc, "_roster_frame", lambda season: pd.DataFrame(rows))

    players, _ = svc.get_roster(2026)

    assert [p.team for p in players] == ["SEA"]


@pytest.fixture
def two_week_schedule(monkeypatch):
    rows = [
        {"week": 1, "gameday": "2026-09-10", "game_id": "g1"},
        {"week": 1, "gameday": "2026-09-14", "game_id": "g2"},
        {"week": 2, "gameday": "2026-09-17", "game_id": "g3"},
        {"week": 2, "gameday": "2026-09-21", "game_id": "g4"},
    ]
    monkeypatch.setattr(svc, "_schedule_frame", lambda season: pd.DataFrame(rows))


@pytest.mark.parametrize(
    "today, expected",
    [
        ("2026-09-08", 1),   # before kickoff
        ("2026-09-14", 1),   # a week holds through its own Monday night
        ("2026-09-15", 2),   # and rolls over the morning after
        ("2026-09-21", 2),
        ("2027-03-01", 2),   # past the last game the final week sticks
    ],
)
def test_current_week_tracks_the_schedule(two_week_schedule, today, expected):
    assert svc.current_week(2026, date.fromisoformat(today)) == expected


def test_current_week_falls_back_to_one_without_a_schedule(monkeypatch):
    monkeypatch.setattr(svc, "_schedule_frame", lambda season: pd.DataFrame())

    assert svc.current_week(2026, date(2026, 9, 17)) == 1
