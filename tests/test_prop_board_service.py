from __future__ import annotations

import pandas as pd
import pytest

from api.schemas import (
    GameRow,
    NormalizedPick,
    PropEvaluationResponse,
    ReplayPolicy,
    RosterPlayer,
    SidePrice,
)
from api.services import prop_board_service as svc
from api.settings import AppSettings


def _side(side: str, prob: float, odds: int) -> SidePrice:
    return SidePrice(
        side=side,  # type: ignore[arg-type]
        raw_prob=prob,
        calibrated_prob=prob,
        book_odds=odds,
        book_implied_prob=0.5,
        market_no_vig_prob=0.5,
        edge=prob - 0.5,
        ev=0.1,
        fair_american=odds,
    )


def _fake_evaluate_prop(settings, request):
    """Deterministic PropEvaluationResponse keyed on the requested line, so
    tests can assert which candidate rung produced which pick."""
    edge = 0.05 + (request.line % 10) / 100.0
    pick = NormalizedPick(
        player_id=request.player_id,
        player_name="",
        position="",
        season=request.season,
        week=request.week,
        stat=request.stat,
        line=request.line,
        book=request.book,
        selected_side="over",
        selected_odds=request.over_odds,
        selected_book_implied_prob=0.5,
        selected_fair_american=request.over_odds,
        selected_raw_prob=0.5 + edge,
        selected_prob=0.5 + edge,
        selected_edge=edge,
        game_id=request.game_id,
        recent_team=request.recent_team,
        opponent_team=request.opponent_team,
        over=_side("over", 0.5 + edge, request.over_odds),
        under=_side("under", 0.5 - edge, request.under_odds),
    )
    return PropEvaluationResponse(
        pick=pick,
        selected_side="over",
        selected_edge=edge,
        policy=ReplayPolicy(
            min_edge=0.0, stake=1.0, singles_evaluated_separately_from_parlays=True,
            same_game_penalty=1.0, same_team_penalty=1.0,
        ),
    )


class _FakeClient:
    def __init__(self, events_by_series: dict[str, list[dict]]):
        self._events_by_series = events_by_series

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def get_events(self, *, series_ticker, status, limit, cursor):
        if cursor:
            return {"events": [], "cursor": ""}
        return {"events": self._events_by_series.get(series_ticker, []), "cursor": ""}


def _market(ticker: str, floor_strike: float, *, yes_bid=None, yes_ask=None, no_ask=None, sub=""):
    m = {"ticker": ticker, "floor_strike": floor_strike}
    if yes_bid is not None:
        m["yes_bid_dollars"] = str(yes_bid)
    if yes_ask is not None:
        m["yes_ask_dollars"] = str(yes_ask)
    if no_ask is not None:
        m["no_ask_dollars"] = str(no_ask)
    if sub:
        m["yes_sub_title"] = sub
    return m


@pytest.fixture(autouse=True)
def _clear_board_cache():
    svc._BOARD_CACHE.clear()
    yield
    svc._BOARD_CACHE.clear()


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def test_norm_name_strips_accents_punctuation_and_suffix():
    assert svc._norm_name("A.J. Brown") == "a j brown"
    assert svc._norm_name("Marvin Harrison Jr.") == "marvin harrison"
    assert svc._norm_name("Amon-Ra St. Brown") == "amon ra st brown"


def test_price_dollars_prefers_dollars_field_over_cents():
    assert svc._price_dollars({"yes_ask_dollars": "0.6600", "yes_ask": 70}, "yes_ask") == 0.66
    assert svc._price_dollars({"yes_ask": 70}, "yes_ask") == 0.70
    assert svc._price_dollars({}, "yes_ask", "last_price") is None


def test_two_sided_odds_from_book_mid():
    odds = svc._two_sided_odds(_market("T-50", 49.5, yes_bid=0.56, yes_ask=0.60, no_ask=0.42))
    assert odds is not None
    over_odds, under_odds = odds
    assert over_odds < 0  # favorite priced above 50c
    assert under_odds > 0


def test_two_sided_odds_none_without_a_two_sided_book():
    assert svc._two_sided_odds(_market("T-50", 49.5, yes_ask=0.55)) is None  # no bid
    assert svc._two_sided_odds(_market("T-50", 49.5)) is None  # no price at all


def test_two_sided_odds_none_when_book_is_too_wide_to_trust():
    # bid 0.12 / ask 0.88 mids to a coin flip but there is no real market there.
    assert svc._two_sided_odds(_market("T-50", 49.5, yes_bid=0.12, yes_ask=0.88)) is None


def test_coinflip_rung_picks_the_nearest_to_50c_within_band():
    rungs = [
        _market("T-100", 99.5, yes_bid=0.85, yes_ask=0.90),  # far ITM, out of band
        _market("T-125", 124.5, yes_bid=0.48, yes_ask=0.52),  # coin flip
        _market("T-150", 149.5, yes_bid=0.20, yes_ask=0.25),  # far OTM, out of band
    ]
    rung = svc._coinflip_rung(rungs)
    assert rung is not None and rung["floor_strike"] == 124.5


def test_coinflip_rung_none_when_nothing_trades_near_even():
    rungs = [_market("T-100", 99.5, yes_bid=0.90, yes_ask=0.92)]
    assert svc._coinflip_rung(rungs) is None


def test_coinflip_rung_skips_a_near_even_mid_backed_by_a_wide_book():
    # mid is a coin flip (0.50) but the 0.76-wide spread means no real book.
    rungs = [_market("T-100", 99.5, yes_bid=0.12, yes_ask=0.88)]
    assert svc._coinflip_rung(rungs) is None


def test_player_key_extracts_middle_ticker_segment():
    assert svc._player_key("KXNFLRECYDS-26SEP10SFLAR-LARPNACUA12-50", "KXNFLRECYDS-26SEP10SFLAR") == "LARPNACUA12"


def test_resolve_player_disambiguates_by_team_then_jersey():
    roster = {
        "matt jones": [
            RosterPlayer(player_id="p1", player_name="Matt Jones", team="LAR", jersey_number=12),
            RosterPlayer(player_id="p2", player_name="Matt Jones", team="SF", jersey_number=44),
        ]
    }
    by_team = svc._resolve_player("Matt Jones: 50+", "LARMJONES12", roster)
    assert by_team is not None and by_team.player_id == "p1"

    roster_no_team_hint = {
        "matt jones": [
            RosterPlayer(player_id="p1", player_name="Matt Jones", team="LAR", jersey_number=12),
            RosterPlayer(player_id="p2", player_name="Matt Jones", team="SF", jersey_number=44),
        ]
    }
    by_jersey = svc._resolve_player("Matt Jones: 50+", "XXMJONES44", roster_no_team_hint)
    assert by_jersey is not None and by_jersey.player_id == "p2"


def test_resolve_player_none_when_unresolvable():
    roster = {"someone else": [RosterPlayer(player_id="p9", player_name="Someone Else", team="KC")]}
    assert svc._resolve_player("Nobody Here: 50+", "KCNOBODY1", roster) is None


def test_match_game_by_event_ticker_and_schedule():
    games = [("2026-09-10", "SF", "LAR", "g1")]
    assert svc._match_game("KXNFLPASSYDS-26SEP10SFLAR", games) == "g1"
    assert svc._match_game("KXNFLPASSYDS-26SEP10NOTAGAME", games) == ""


# ---------------------------------------------------------------------------
# _compute_board / build_prop_board
# ---------------------------------------------------------------------------


@pytest.fixture
def board_env(monkeypatch):
    games = [
        GameRow(game_id="g1", week=1, gameday="2026-09-10", away_team="SF", home_team="LAR"),
    ]
    monkeypatch.setattr(svc, "get_schedule", lambda season, week: list(games))

    schedule_df = pd.DataFrame(
        [{"season": 2026, "week": 1, "gameday": "2026-09-10", "away_team": "SF", "home_team": "LAR", "game_id": "g1"}]
    )
    monkeypatch.setattr(svc, "load_schedules", lambda seasons: schedule_df)

    rosters = {
        "LAR": [RosterPlayer(player_id="stafford", player_name="Matthew Stafford", team="LAR", position="QB", jersey_number=9)],
        "SF": [],
    }
    monkeypatch.setattr(
        svc, "get_roster", lambda season, *, team, skill_only=True, status=None: (rosters.get(team, []), 1)
    )
    monkeypatch.setattr(svc, "evaluate_prop", _fake_evaluate_prop)
    return games


def test_compute_board_resolves_prices_and_evaluates(monkeypatch, board_env):
    events = {
        "KXNFLPASSYDS": [
            {
                "event_ticker": "KXNFLPASSYDS-26SEP10SFLAR",
                "markets": [
                    _market("KXNFLPASSYDS-26SEP10SFLAR-LARMSTAFFORD9-200", 199.5, yes_bid=0.80, yes_ask=0.84),  # ITM, skipped
                    _market(
                        "KXNFLPASSYDS-26SEP10SFLAR-LARMSTAFFORD9-225", 224.5,
                        yes_bid=0.48, yes_ask=0.52, no_ask=0.55, sub="Matthew Stafford: 225+",
                    ),
                ],
            }
        ]
    }
    monkeypatch.setattr(svc, "_client", lambda: _FakeClient(events))

    board = svc.build_prop_board(AppSettings(), season=2026, week=1, limit=50)
    assert board.season == 2026 and board.week == 1
    assert board.markets_considered == 1
    assert len(board.picks) == 1
    pick = board.picks[0]
    assert pick.player_id == "stafford"
    assert pick.player_name == "Matthew Stafford"  # backfilled from roster
    assert pick.position == "QB"
    assert pick.line == 224.5
    assert pick.stat == "passing_yards"
    assert pick.game_id == "g1"


def test_compute_board_skips_events_outside_the_week_schedule(monkeypatch, board_env):
    events = {
        "KXNFLPASSYDS": [
            {
                "event_ticker": "KXNFLPASSYDS-26SEP10KCXXX",  # no matching schedule row
                "markets": [_market("KXNFLPASSYDS-26SEP10KCXXX-KCSOMEQB1-225", 224.5, yes_bid=0.5, yes_ask=0.5)],
            }
        ]
    }
    monkeypatch.setattr(svc, "_client", lambda: _FakeClient(events))

    board = svc.build_prop_board(AppSettings(), season=2026, week=1, limit=50)
    assert board.picks == []
    assert board.markets_considered == 0


def test_compute_board_sorts_by_edge_and_respects_limit(monkeypatch, board_env):
    rosters = {
        "LAR": [
            RosterPlayer(player_id="stafford", player_name="Matthew Stafford", team="LAR", position="QB", jersey_number=9),
            RosterPlayer(player_id="nacua", player_name="Puka Nacua", team="LAR", position="WR", jersey_number=12),
        ],
        "SF": [],
    }
    monkeypatch.setattr(
        svc, "get_roster", lambda season, *, team, skill_only=True, status=None: (rosters.get(team, []), 1)
    )
    events = {
        "KXNFLPASSYDS": [
            {
                "event_ticker": "KXNFLPASSYDS-26SEP10SFLAR",
                "markets": [
                    _market(
                        "KXNFLPASSYDS-26SEP10SFLAR-LARMSTAFFORD9-221", 220.5,
                        yes_bid=0.48, yes_ask=0.52, sub="Matthew Stafford: 221+",
                    ),
                ],
            }
        ],
        "KXNFLRECYDS": [
            {
                "event_ticker": "KXNFLRECYDS-26SEP10SFLAR",
                "markets": [
                    _market(
                        "KXNFLRECYDS-26SEP10SFLAR-LARPNACUA12-59", 58.5,
                        yes_bid=0.48, yes_ask=0.52, sub="Puka Nacua: 59+",
                    ),
                ],
            }
        ],
    }
    monkeypatch.setattr(svc, "_client", lambda: _FakeClient(events))

    board = svc.build_prop_board(AppSettings(), season=2026, week=1, limit=1)
    assert len(board.picks) == 1  # limit enforced
    full = svc.build_prop_board(AppSettings(), season=2026, week=1, limit=50)
    assert [p.selected_edge for p in full.picks] == sorted((p.selected_edge for p in full.picks), reverse=True)
    assert set(full.stats) == {"passing_yards", "receiving_yards"}


def test_build_prop_board_raises_for_missing_schedule(monkeypatch):
    monkeypatch.setattr(svc, "get_schedule", lambda season, week: [])
    with pytest.raises(ValueError):
        svc.build_prop_board(AppSettings(), season=2026, week=1, limit=50, wait=True)


def test_build_prop_board_caches_per_key(monkeypatch, board_env):
    monkeypatch.setattr(svc, "_client", lambda: _FakeClient({}))
    first = svc.build_prop_board(AppSettings(), season=2026, week=1, limit=50)
    second = svc.build_prop_board(AppSettings(), season=2026, week=1, limit=50)
    assert first is second


def test_build_prop_board_raises_boardbuilding_when_locked(monkeypatch, board_env):
    import threading

    inside = threading.Event()
    release = threading.Event()

    def _slow_compute(*_args, **_kwargs):
        inside.set()
        assert release.wait(timeout=5)
        return svc.PropBoardResponse(season=2026, week=1, games=0)

    monkeypatch.setattr(svc, "_compute_board", _slow_compute)

    t = threading.Thread(target=lambda: svc.build_prop_board(AppSettings(), season=2026, week=1, limit=50, wait=True))
    t.start()
    assert inside.wait(timeout=5)

    with pytest.raises(svc.BoardBuilding):
        svc.build_prop_board(AppSettings(), season=2026, week=1, limit=50)

    release.set()
    t.join(timeout=5)
