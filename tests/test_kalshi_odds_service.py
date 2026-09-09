from __future__ import annotations

import pandas as pd
import pytest

from api.services import kalshi_odds_service as kos


def test_event_ticker_parses_to_date_and_team_blob():
    assert kos._event_game_key("KXNFLTOTAL-26SEP13ATLPIT") == ("2026-09-13", "ATLPIT")
    assert kos._event_game_key("KXNFLSPREAD-26SEP10SFLAR") == ("2026-09-10", "SFLAR")
    assert kos._event_game_key("garbage") is None


def test_blob_team_match_handles_aliases():
    assert kos._blob_has_team("SFLAR", "SF") and kos._blob_has_team("SFLAR", "LA")  # LA<->LAR
    assert kos._blob_has_team("ATLPIT", "ATL") and kos._blob_has_team("ATLPIT", "PIT")
    assert not kos._blob_has_team("ATLPIT", "SEA")


def test_invert_ladder_finds_the_fifty_percent_strike():
    # P(total > K): 20 -> .82, 24 -> .58, 28 -> .40  => crosses 0.5 between 24 and 28
    markets = [
        {"floor_strike": 20, "yes_bid": 80, "yes_ask": 84},
        {"floor_strike": 24, "yes_bid": 56, "yes_ask": 60},
        {"floor_strike": 28, "yes_bid": 38, "yes_ask": 42},
    ]
    val = kos._invert_ladder(markets)
    assert 24.0 < val < 28.0


def test_invert_ladder_none_when_unpriced():
    assert kos._invert_ladder([{"floor_strike": 24, "yes_bid": None, "yes_ask": None}]) is None


def test_invert_ladder_uses_single_nearest_coinflip_market():
    # far strikes are lopsided (~+/-2000 odds); one market sits ~50c -> that's the line
    markets = [
        {"floor_strike": 30, "yes_bid": 95, "yes_ask": 97},
        {"floor_strike": 44, "yes_bid": 49, "yes_ask": 51},   # ~coin flip -> the line
        {"floor_strike": 60, "yes_bid": 3, "yes_ask": 5},
    ]
    val = kos._invert_ladder(markets)
    assert 43.5 <= val <= 44.5


def test_invert_ladder_no_straddle_takes_nearest_strike_plus_half():
    # nothing crosses 0.5; nearest coin-flip market is strike 40 at 0.62
    markets = [
        {"floor_strike": 36, "yes_bid": 78, "yes_ask": 82},
        {"floor_strike": 40, "yes_bid": 60, "yes_ask": 64},
    ]
    assert kos._invert_ladder(markets) == 40.5


@pytest.fixture
def _wire(monkeypatch):
    sched = pd.DataFrame([
        dict(game_id="2026_02_ATL_PIT", season=2026, week=2,
             gameday="2026-09-13", away_team="ATL", home_team="PIT"),
    ])
    monkeypatch.setattr(kos, "load_schedules", lambda years: sched)

    class _FakeClient:
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def get_events(self, *, series_ticker, status, limit):
            if series_ticker == "KXNFLTOTAL":
                return {"events": [{
                    "event_ticker": "KXNFLTOTAL-26SEP13ATLPIT",
                    "markets": [
                        {"floor_strike": 40, "yes_bid": 70, "yes_ask": 74},
                        {"floor_strike": 44, "yes_bid": 46, "yes_ask": 50},
                        {"floor_strike": 48, "yes_bid": 24, "yes_ask": 28},
                    ],
                }]}
            return {"events": []}

    monkeypatch.setattr(kos, "_client", lambda: _FakeClient())
    kos.nfl_game_lines.cache_clear()


def test_nfl_game_lines_returns_implied_total(_wire):
    lines = kos.nfl_game_lines(2026, 2)
    assert "2026_02_ATL_PIT" in lines
    entry = lines["2026_02_ATL_PIT"]
    assert 40.0 < entry["total"] < 48.0 and entry["source"] == "kalshi"


def test_nfl_game_lines_empty_on_unpriced(monkeypatch):
    monkeypatch.setattr(kos, "load_schedules", lambda years: pd.DataFrame(
        [dict(game_id="g1", season=2026, week=3, gameday="2026-09-20",
              away_team="NE", home_team="SEA")]
    ))

    class _Empty:
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def get_events(self, **_k): return {"events": [{
            "event_ticker": "KXNFLTOTAL-26SEP20NESEA",
            "markets": [{"floor_strike": 44, "yes_bid": None, "yes_ask": None}],
        }]}

    monkeypatch.setattr(kos, "_client", lambda: _Empty())
    kos.nfl_game_lines.cache_clear()
    assert kos.nfl_game_lines(2026, 3) == {}
