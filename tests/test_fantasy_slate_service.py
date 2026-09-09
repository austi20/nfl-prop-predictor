from __future__ import annotations

import pandas as pd
import pytest

from api.schemas import FantasySlateResponse, FantasySummary, GameRow, RosterPlayer
from api.services import fantasy_slate_service as svc
from api.settings import AppSettings


def _weekly_fixture() -> pd.DataFrame:
    """Thin history so the prescore has something to weight. ``buzz`` has no rows
    and ``rb-thin`` has only two games -> both drop below _MIN_TRAILING_GAMES."""
    rows = []
    for season in (2024, 2025):
        for week in range(1, 6):
            rows.append(
                dict(
                    player_id="rb-star",
                    player_name="R.Star",
                    position="RB",
                    season=season,
                    week=week,
                    recent_team="ATL",
                    opponent_team="TB",
                    rushing_yards=95.0,
                    rushing_tds=0.8,
                    receptions=4.0,
                    receiving_yards=32.0,
                    receiving_tds=0.2,
                )
            )
            rows.append(
                dict(
                    player_id="wr-mid",
                    player_name="W.Mid",
                    position="WR",
                    season=season,
                    week=week,
                    recent_team="TB",
                    opponent_team="ATL",
                    receptions=5.0,
                    receiving_yards=60.0,
                    receiving_tds=0.4,
                    rushing_yards=1.0,
                    rushing_tds=0.0,
                )
            )
    for week in (1, 2):
        rows.append(
            dict(
                player_id="rb-thin",
                player_name="T.Hin",
                position="RB",
                season=2025,
                week=week,
                recent_team="ATL",
                opponent_team="TB",
                rushing_yards=40.0,
                rushing_tds=0.0,
                receptions=1.0,
                receiving_yards=8.0,
                receiving_tds=0.0,
            )
        )
    return pd.DataFrame(rows)


_SUMMARY_POINTS = {"rb-star": 18.4, "wr-mid": 12.1}


def _fake_summary(_settings, *, player_id, **_kwargs) -> FantasySummary:
    pts = _SUMMARY_POINTS.get(player_id, 1.0)
    return FantasySummary(
        projected_points=pts,
        median_points=pts,
        p10_points=pts * 0.5,
        p90_points=pts * 1.6,
        boom_probability=0.3,
        bust_probability=0.2,
        boom_cutoff=20.0,
        bust_cutoff=8.0,
    )


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    svc._SLATE_CACHE.clear()
    monkeypatch.setattr(svc, "_SLATE_LOCK", __import__("threading").Lock())  # per-test isolation
    games = [
        GameRow(
            game_id="2026_01_TB_ATL",
            week=1,
            gameday="2026-09-13",
            gametime="13:00",
            away_team="TB",
            home_team="ATL",
        )
    ]
    rosters = {
        "ATL": [
            RosterPlayer(player_id="rb-star", player_name="R.Star", team="ATL", position="RB"),
            RosterPlayer(player_id="rb-thin", player_name="T.Hin", team="ATL", position="RB"),
            RosterPlayer(player_id="buzz", player_name="B.Uzz", team="ATL", position="RB"),
        ],
        "TB": [
            RosterPlayer(player_id="wr-mid", player_name="W.Mid", team="TB", position="WR"),
        ],
    }
    monkeypatch.setattr(svc, "get_schedule", lambda season, week: list(games))
    monkeypatch.setattr(
        svc, "get_roster", lambda season, *, team, position: (rosters.get(team, []), 1)
    )
    monkeypatch.setattr(svc, "scoring_weekly", lambda settings, season: _weekly_fixture())
    monkeypatch.setattr(svc, "build_fantasy_summary", _fake_summary)


def test_slate_ranks_by_projection_and_drops_thin_or_absent_history():
    out = svc.build_fantasy_slate(AppSettings(), season=2026, week=1, limit=25)

    assert out.season == 2026 and out.week == 1
    assert out.games == 1
    ids = [e.player_id for e in out.entries]
    assert ids == ["rb-star", "wr-mid"]  # sorted by projected_points desc
    assert "buzz" not in ids  # no trailing history -> prescore 0 -> excluded
    assert "rb-thin" not in ids  # only 2 games -> below _MIN_TRAILING_GAMES
    top = out.entries[0]
    assert top.opponent_team == "TB"
    assert top.floor_points < top.projected_points < top.ceiling_points


def test_slate_limit_sizes_the_per_position_budget():
    # Floor of 4 per position means a 2-real-player fixture still returns both
    # even at limit=1; limit scales the take, it is not a hard output cap.
    out = svc.build_fantasy_slate(AppSettings(), season=2026, week=1, limit=1)
    assert [e.player_id for e in out.entries] == ["rb-star", "wr-mid"]


def test_slate_response_is_cached_per_key():
    first = svc.build_fantasy_slate(AppSettings(), season=2026, week=1, limit=25)
    second = svc.build_fantasy_slate(AppSettings(), season=2026, week=1, limit=25)
    assert first is second


def test_slate_rejects_unknown_scoring_mode():
    with pytest.raises(ValueError):
        svc.build_fantasy_slate(AppSettings(), season=2026, week=1, scoring_mode="ppr")  # type: ignore[arg-type]


def test_concurrent_builds_compute_once(monkeypatch):
    """The lock must collapse N concurrent callers of the same key into one
    _compute_slate; a wait=True caller blocks and gets the cached result, a
    wait=False caller raises SlateBuilding rather than pile a second build."""
    import threading

    calls = {"n": 0}
    inside_compute = threading.Event()
    may_finish = threading.Event()
    real_response = FantasySlateResponse(season=2026, week=1, games=1)

    def _gated_compute(*_args, **_kwargs):
        calls["n"] += 1
        inside_compute.set()
        assert may_finish.wait(timeout=5)
        return real_response

    monkeypatch.setattr(svc, "_compute_slate", _gated_compute)

    waiter_result: list[object] = []
    nonwaiter_error: list[BaseException] = []

    def _waiter():
        waiter_result.append(
            svc.build_fantasy_slate(AppSettings(), season=2026, week=1, limit=25, wait=True)
        )

    t1 = threading.Thread(target=_waiter)
    t1.start()
    assert inside_compute.wait(timeout=5)  # t1 now holds the lock, parked in _compute_slate

    try:
        svc.build_fantasy_slate(AppSettings(), season=2026, week=1, limit=25)
    except BaseException as exc:  # noqa: BLE001
        nonwaiter_error.append(exc)

    may_finish.set()
    t1.join(timeout=5)

    assert calls["n"] == 1  # only one build ran
    assert waiter_result == [real_response]
    assert len(nonwaiter_error) == 1 and isinstance(nonwaiter_error[0], svc.SlateBuilding)
