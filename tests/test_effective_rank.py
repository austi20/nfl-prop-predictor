from __future__ import annotations

import pandas as pd
import pytest

from data import depth_chart, injuries


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=depth_chart._COLUMNS)


@pytest.fixture
def sea_qbs(monkeypatch):
    """SEA's week-2 room: Darnold 1, Lock 2, Milroe 3."""
    rows = [
        {"gsis_id": "darnold", "season": 2026, "week": 2, "team": "SEA",
         "position": "QB", "rank": 1, "asof": pd.Timestamp("2026-09-17", tz="UTC")},
        {"gsis_id": "lock", "season": 2026, "week": 2, "team": "SEA",
         "position": "QB", "rank": 2, "asof": pd.Timestamp("2026-09-17", tz="UTC")},
        {"gsis_id": "milroe", "season": 2026, "week": 2, "team": "SEA",
         "position": "QB", "rank": 3, "asof": pd.Timestamp("2026-09-17", tz="UTC")},
    ]
    monkeypatch.setattr(depth_chart, "rank_frame", lambda seasons: _frame(rows))
    depth_chart.effective_rank.cache_clear()
    yield
    depth_chart.effective_rank.cache_clear()


def _patch_out(monkeypatch, ids: set[str]):
    monkeypatch.setattr(injuries, "unavailable", lambda season, week, **kw: frozenset(ids))


def test_backup_is_promoted_when_the_starter_is_out(sea_qbs, monkeypatch):
    _patch_out(monkeypatch, {"darnold"})

    assert depth_chart.effective_rank("lock", 2026, 2, (2026,)) == 1
    # the promotion cascades down the room
    assert depth_chart.effective_rank("milroe", 2026, 2, (2026,)) == 2


def test_nobody_moves_when_the_room_is_healthy(sea_qbs, monkeypatch):
    _patch_out(monkeypatch, set())

    assert depth_chart.effective_rank("lock", 2026, 2, (2026,)) == 2
    assert depth_chart.effective_rank("milroe", 2026, 2, (2026,)) == 3


def test_an_absent_player_keeps_his_own_rank(sea_qbs, monkeypatch):
    """Darnold is the one who is out; promoting him would be nonsense."""
    _patch_out(monkeypatch, {"darnold"})

    assert depth_chart.effective_rank("darnold", 2026, 2, (2026,)) == 1


def test_a_player_behind_an_absence_is_unaffected(sea_qbs, monkeypatch):
    """Only team-mates ranked ahead matter."""
    _patch_out(monkeypatch, {"milroe"})

    assert depth_chart.effective_rank("lock", 2026, 2, (2026,)) == 2


def test_unknown_player_has_no_rank(sea_qbs, monkeypatch):
    _patch_out(monkeypatch, {"darnold"})

    assert depth_chart.effective_rank("nobody", 2026, 2, (2026,)) is None
