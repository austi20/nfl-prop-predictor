from __future__ import annotations

import pandas as pd
import pytest

from data import usage as u


@pytest.fixture(autouse=True)
def _clear_caches():
    for fn in (u._pfr_to_gsis, u.snap_share_frame, u.air_yards_share_frame, u.usage_trend):
        fn.cache_clear()
    yield
    for fn in (u._pfr_to_gsis, u.snap_share_frame, u.air_yards_share_frame, u.usage_trend):
        fn.cache_clear()


def _snap_rows(gsis: str, pcts: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            dict(pfr_player_id="X00", position="RB", season=2025, week=w + 1, offense_pct=p)
            for w, p in enumerate(pcts)
        ]
    ).assign(_gsis=gsis)


def test_usage_trend_detects_rising_snap_share(monkeypatch):
    # weeks 1-5 at ~30%, weeks 6-10 at ~80% -> recent(8,9,10) >> base(3..7)
    pcts = [0.30, 0.32, 0.28, 0.35, 0.33, 0.80, 0.82, 0.85, 0.83, 0.86]
    snaps = pd.DataFrame(
        [dict(pfr_player_id="X00", position="RB", season=2025, week=w + 1, offense_pct=p)
         for w, p in enumerate(pcts)]
    )
    monkeypatch.setattr(u, "load_snap_counts", lambda years: snaps)
    monkeypatch.setattr(u, "load_ids", lambda: pd.DataFrame([dict(pfr_id="X00", gsis_id="rb-1")]))
    monkeypatch.setattr(u, "load_ngs", lambda *_a: pd.DataFrame())

    trend = u.usage_trend("rb-1", 2026, 1, (2025,))
    assert trend is not None
    # recent = last 3 games (~0.85); base = games 4-8 back (straddles the change)
    assert trend["snap_recent"] > 0.8
    assert trend["snap_recent"] / trend["snap_base"] > 1.4


def test_usage_trend_none_without_enough_history(monkeypatch):
    snaps = pd.DataFrame(
        [dict(pfr_player_id="X00", position="WR", season=2025, week=w + 1, offense_pct=0.6)
         for w in range(3)]
    )
    monkeypatch.setattr(u, "load_snap_counts", lambda years: snaps)
    monkeypatch.setattr(u, "load_ids", lambda: pd.DataFrame([dict(pfr_id="X00", gsis_id="wr-1")]))
    monkeypatch.setattr(u, "load_ngs", lambda *_a: pd.DataFrame())
    assert u.usage_trend("wr-1", 2026, 1, (2025,)) is None


def test_usage_factor_boosts_on_rising_role(monkeypatch):
    from api.services.fantasy_service import _usage_factor

    monkeypatch.setattr(
        "data.usage.usage_trend",
        lambda *_a, **_k: {"snap_recent": 0.85, "snap_base": 0.45},
    )
    fac = _usage_factor(
        player_id="rb-1", season=2026, week=1, position="RB", seasons=(2025,)
    )
    assert fac.applied and fac.multiplier > 1.0 and "trending up" in fac.reason


def test_usage_factor_neutral_when_stable(monkeypatch):
    from api.services.fantasy_service import _usage_factor

    monkeypatch.setattr(
        "data.usage.usage_trend",
        lambda *_a, **_k: {"snap_recent": 0.62, "snap_base": 0.60},
    )
    fac = _usage_factor(
        player_id="rb-1", season=2026, week=1, position="RB", seasons=(2025,)
    )
    assert not fac.applied
