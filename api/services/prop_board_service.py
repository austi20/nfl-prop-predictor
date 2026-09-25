"""Live prop board from Kalshi NFL player markets.

Kalshi lists each player stat as a ladder of "K+" yes/no markets. There is no
posted line the way a sportsbook has one -- so we take the rung trading nearest
a coin flip (yes price closest to 50c, i.e. American odds closest to +/-0) as
the de-facto line. Per the project note, that rung's two-sided price tracks the
Vegas number closely enough to grade edge against the model.

Each surviving rung is run through ``evaluate_prop`` (the same GLM path the
single-prop endpoint uses) to get model probability, no-vig market probability,
edge and EV. The board is the ranked list of those picks.

Market reads are unauthenticated. The board is cached per (season, week, limit)
behind a one-build lock, mirroring the fantasy slate.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata

from api.schemas import NormalizedPick, PropBoardResponse, PropEvaluationRequest
from api.services.evaluation_service import evaluate_prop
from api.services.kalshi_odds_service import _blob_has_team, _client, _event_game_key
from api.services.nflverse_service import current_week, get_roster, get_schedule
from api.settings import AppSettings
from data.nflverse_loader import load_schedules
from eval.prop_pricer import fair_price_to_american

_log = logging.getLogger(__name__)

# Kalshi per-game player series -> the model stat key (see eval/calibration_pipeline
# STAT_SPECS). Only stats the GLMs actually predict are listed.
#
# Probed 2026-09-13 and currently listing no markets upstream, so deliberately
# absent: KXNFLINT, KXNFLRSHTDS, KXNFLRECTDS, KXNFLTGT, KXNFLANYTD. The models
# do predict interceptions, rushing_tds, receiving_tds and targets, so these can
# be enabled the moment Kalshi lists them.
_SERIES_STAT: dict[str, str] = {
    "KXNFLPASSYDS": "passing_yards",
    "KXNFLPASSTDS": "passing_tds",
    "KXNFLPASSCOMP": "completions",
    "KXNFLPASSATT": "attempts",
    "KXNFLRSHYDS": "rushing_yards",
    "KXNFLRSHATT": "carries",
    "KXNFLRECYDS": "receiving_yards",
    "KXNFLREC": "receptions",
}

_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

_BOARD_CACHE: dict[tuple[int, int, int], tuple[float, PropBoardResponse]] = {}
# Prices and injuries move through the day; a board older than this rebuilds.
_BOARD_MAX_AGE_SECONDS = 30 * 60


def _cached_board(key: tuple[int, int, int]) -> PropBoardResponse | None:
    entry = _BOARD_CACHE.get(key)
    if entry is None or time.time() - entry[0] > _BOARD_MAX_AGE_SECONDS:
        return None
    return entry[1]
_BOARD_LOCK = threading.Lock()


class BoardBuilding(Exception):
    """Raised when a board build is already in progress for another caller."""


def _norm_name(name: str) -> str:
    """Lowercase, drop accents, punctuation and a trailing generational suffix
    so 'A.J. Brown' and 'Marvin Harrison Jr.' match the roster spelling."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    tokens = re.sub(r"[^a-z ]", " ", ascii_name.lower()).split()
    if tokens and tokens[-1] in _NAME_SUFFIXES:
        tokens = tokens[:-1]
    return " ".join(tokens)


def _price_dollars(market: dict, *keys: str) -> float | None:
    """First present price among ``keys``, as a 0..1 fraction. Handles both the
    string ``*_dollars`` fields and the integer-cent fields."""
    for key in keys:
        raw = market.get(f"{key}_dollars")
        if raw not in (None, ""):
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass
        cents = market.get(key)
        if cents not in (None, ""):
            try:
                return float(cents) / 100.0
            except (TypeError, ValueError):
                pass
    return None


# A rung only counts as "the line" when its yes price is within this band of a
# coin flip (American odds roughly within +/-230). Outside it the model and the
# market are pricing different questions and the edge is meaningless.
_COINFLIP_BAND = (0.30, 0.70)

# Week-1 player markets are thin: a lone real bid against a wide, mostly
# decorative ask (or vice versa) prices at 50c on the mid while the ask alone
# implies -700 odds. Require the two-sided spread itself to be tradeable
# before trusting the mid as "the line" -- a wide book means there isn't one.
_MAX_SPREAD = 0.25


def _rung_mid_prices(market: dict) -> tuple[float, float] | None:
    """(yes_mid, no_mid) as 0..1 fractions from a genuine two-sided book. None
    when either side has no quote or the book is wider than ``_MAX_SPREAD``."""
    yes_bid = _price_dollars(market, "yes_bid")
    yes_ask = _price_dollars(market, "yes_ask")
    if yes_bid is None or yes_ask is None or yes_ask - yes_bid > _MAX_SPREAD:
        return None
    yes_mid = (yes_bid + yes_ask) / 2.0
    no_bid = _price_dollars(market, "no_bid")
    no_ask = _price_dollars(market, "no_ask")
    no_mid = (no_bid + no_ask) / 2.0 if no_bid is not None and no_ask is not None else 1.0 - yes_mid
    return yes_mid, no_mid


def _two_sided_odds(market: dict) -> tuple[int, int] | None:
    """(over_odds, under_odds) as American ints from the rung's book mid."""
    mids = _rung_mid_prices(market)
    if mids is None:
        return None
    yes_mid, no_mid = mids
    yes_mid = min(max(yes_mid, 0.02), 0.98)
    no_mid = min(max(no_mid, 0.02), 0.98)
    return fair_price_to_american(yes_mid), fair_price_to_american(no_mid)


def _coinflip_rung(markets: list[dict]) -> dict | None:
    """The priced rung nearest a coin flip -- the line the market is pricing.
    Returns None when no rung trades inside the near-even band on a tradeable
    book."""
    best, best_dist = None, 1.0
    for m in markets:
        if m.get("floor_strike") is None:
            continue
        mids = _rung_mid_prices(m)
        if mids is None:
            continue
        yes_mid, _ = mids
        if not (_COINFLIP_BAND[0] <= yes_mid <= _COINFLIP_BAND[1]):
            continue
        dist = abs(yes_mid - 0.5)
        if dist < best_dist:
            best, best_dist = m, dist
    return best


def _player_key(market_ticker: str, event_ticker: str) -> str:
    """The player segment of a market ticker: EVENT-<PLAYERKEY>-<STRIKE>."""
    tail = market_ticker[len(event_ticker) + 1 :] if market_ticker.startswith(event_ticker) else market_ticker
    parts = tail.split("-")
    return parts[0] if parts else ""


def _roster_index(season: int, teams: set[str]) -> dict[str, list]:
    """{normalized name: [RosterPlayer, ...]} across the given teams."""
    index: dict[str, list] = {}
    for team in teams:
        try:
            players, _ = get_roster(season, team=team, skill_only=True, status=None)
        except Exception:  # noqa: BLE001
            continue
        for player in players:
            index.setdefault(_norm_name(player.player_name), []).append(player)
    return index


def _resolve_player(sub_title: str, player_key: str, roster: dict[str, list]):
    """Map 'Matthew Stafford: 225+' + ticker key to a RosterPlayer, or None."""
    name = sub_title.split(":", 1)[0].strip()
    matches = roster.get(_norm_name(name), [])
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        key = player_key.upper()
        by_team = [p for p in matches if p.team and p.team.upper() in key]
        if len(by_team) == 1:
            return by_team[0]
        digits = re.sub(r"\D", "", player_key)
        by_jersey = [p for p in matches if digits and str(p.jersey_number or "") == digits]
        if len(by_jersey) == 1:
            return by_jersey[0]
    return None


def _week_context(season: int, week: int) -> dict[str, tuple[str, str]]:
    """{team: (opponent, game_id)} for the week."""
    context: dict[str, tuple[str, str]] = {}
    for game in get_schedule(season, week):
        if game.home_team:
            context[game.home_team] = (game.away_team, game.game_id)
        if game.away_team:
            context[game.away_team] = (game.home_team, game.game_id)
    return context


def _match_game(event_ticker: str, games: list[tuple[str, str, str, str]]) -> str:
    key = _event_game_key(event_ticker)
    if not key:
        return ""
    gday, blob = key
    for gd, away, home, gid in games:
        if gd == gday and _blob_has_team(blob, away) and _blob_has_team(blob, home):
            return gid
    return ""


def _iter_events(client, series: str):
    cursor = ""
    for _ in range(20):
        page = client.get_events(series_ticker=series, status="open", limit=200, cursor=cursor)
        yield from page.get("events", [])
        cursor = page.get("cursor", "")
        if not cursor:
            return


def _compute_board(settings: AppSettings, *, season: int, week: int, limit: int) -> PropBoardResponse:
    context = _week_context(season, week)
    if not context:
        raise ValueError(f"No schedule rows for {season} week {week}")

    sched = load_schedules([season])
    wk = sched[sched["week"] == week]
    games = [
        (str(getattr(r, "gameday", "")), str(r.away_team), str(r.home_team), str(r.game_id))
        for r in wk.itertuples(index=False)
    ]
    roster = _roster_index(season, set(context))

    picks: list[NormalizedPick] = []
    considered = 0
    with _client() as client:
        for series, stat in _SERIES_STAT.items():
            try:
                events = list(_iter_events(client, series))
            except Exception as exc:  # noqa: BLE001
                _log.warning("prop board: %s events unavailable (%s)", series, exc)
                continue
            for event in events:
                event_ticker = str(event.get("event_ticker", ""))
                game_id = _match_game(event_ticker, games)
                if not game_id:
                    continue
                by_player: dict[str, list[dict]] = {}
                for market in event.get("markets") or []:
                    pkey = _player_key(str(market.get("ticker", "")), event_ticker)
                    if pkey:
                        by_player.setdefault(pkey, []).append(market)
                for pkey, rungs in by_player.items():
                    rung = _coinflip_rung(rungs)
                    if rung is None:
                        continue
                    odds = _two_sided_odds(rung)
                    if odds is None:
                        continue
                    sub_title = str(rung.get("yes_sub_title") or rung.get("no_sub_title") or "")
                    player = _resolve_player(sub_title, pkey, roster)
                    if player is None:
                        continue
                    opponent, _ = context.get(player.team, ("", ""))
                    considered += 1
                    try:
                        result = evaluate_prop(
                            settings,
                            PropEvaluationRequest(
                                player_id=player.player_id,
                                season=season,
                                week=week,
                                stat=stat,
                                line=float(rung["floor_strike"]),
                                over_odds=odds[0],
                                under_odds=odds[1],
                                opponent_team=opponent,
                                recent_team=player.team,
                                game_id=game_id,
                                book="kalshi",
                            ),
                        )
                    except Exception:  # noqa: BLE001
                        continue
                    pick = result.pick
                    # evaluate_prop reads player_name/position off the weekly
                    # box-score frame, which is empty pre-kickoff for a future
                    # week -- the roster row is the only source before then.
                    if not pick.player_name or not pick.position:
                        pick = pick.model_copy(
                            update={
                                "player_name": pick.player_name or player.player_name,
                                "position": pick.position or player.position,
                            }
                        )
                    picks.append(pick)

    picks.sort(key=lambda p: p.selected_edge, reverse=True)
    if limit > 0:
        picks = picks[:limit]
    return PropBoardResponse(
        season=season,
        week=week,
        games=len(games),
        markets_considered=considered,
        stats=sorted({p.stat for p in picks}),
        picks=picks,
    )


def build_prop_board(
    settings: AppSettings,
    *,
    season: int,
    week: int,
    limit: int = 150,
    wait: bool = False,
) -> PropBoardResponse:
    cache_key = (season, week, limit)
    cached = _cached_board(cache_key)
    if cached is not None:
        return cached

    if not _BOARD_LOCK.acquire(blocking=wait):
        raise BoardBuilding
    try:
        cached = _cached_board(cache_key)
        if cached is not None:
            return cached
        response = _compute_board(settings, season=season, week=week, limit=limit)
        _BOARD_CACHE[cache_key] = (time.time(), response)
        return response
    finally:
        _BOARD_LOCK.release()


_PREWARM_SEASON = 2026
# The cache key is (season, week, limit), so this has to be the limit the GUI
# asks for or the prewarmed board is never read (dashboard-page.tsx).
_PREWARM_LIMIT = 200


def prewarm_current_board(settings: AppSettings) -> None:
    """Best-effort: build the default board off-thread so the first GUI open is
    a cache hit. Kalshi being unreachable just leaves the cache cold."""
    try:
        build_prop_board(
            settings,
            season=_PREWARM_SEASON,
            week=current_week(_PREWARM_SEASON),
            limit=_PREWARM_LIMIT,
            wait=True,
        )
    except Exception:  # noqa: BLE001
        pass
