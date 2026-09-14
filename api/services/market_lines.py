"""Market-implied player stat lines from Kalshi, for anchoring projections.

Kalshi lists each player stat as a ladder of "K+" yes/no markets rather than a
posted line. The rung trading nearest a coin flip is the de-facto line: at 50c
the market is saying the outcome is even money.

What this module returns is the traded strike *and the price on it* — a
probability statement, "P(stat >= K) = p". That is strictly more information
than a bare line, and it lets a caller fit its own distribution to the market's
own claim rather than guess at a median.

Such a quote is the single best forward-looking estimate available, because a
priced market has already absorbed the depth chart, the injury report and the
beat news. Where one exists it should outrank anything the model infers from
history. Coverage is thin and uneven, so this is strictly best-effort: absent a
tradeable book the caller falls back to its own priors.

Results are cached to disk with a short TTL because the fantasy slate fans out
across spawned worker processes, and a per-worker fetch would both duplicate
work and run into Kalshi's rate limit.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from api.settings import AppSettings
from data.nflverse_loader import app_root

_log = logging.getLogger(__name__)

# Kalshi per-game player series -> model stat key.
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

# Lines move, but not minute to minute, and a stale line beats no line.
_TTL_SECONDS = 15 * 60


# Bumped whenever the cached payload shape changes, so an old file on disk is
# simply ignored rather than deserialized into the wrong shape.
_CACHE_SCHEMA = 2


def _cache_file(season: int, week: int) -> Path:
    return (
        app_root()
        / "cache"
        / f"market_lines_v{_CACHE_SCHEMA}_{season}_{week:02d}.json"
    )


def _read_cache(season: int, week: int) -> dict[str, list[float]] | None:
    path = _cache_file(season, week)
    try:
        if not path.exists() or time.time() - path.stat().st_mtime > _TTL_SECONDS:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a bad cache must not brick projections
        return None


def _write_cache(season: int, week: int, payload: dict[str, list[float]]) -> None:
    path = _cache_file(season, week)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    except Exception:  # noqa: BLE001
        _log.debug("market lines: cache write failed", exc_info=True)


def _key(player_id: str, stat: str) -> str:
    return f"{player_id}|{stat}"


def _fetch(season: int, week: int) -> dict[str, list[float]]:
    """Scrape the coin-flip rung of every player ladder for the week."""
    from api.services.prop_board_service import (
        _client,
        _coinflip_rung,
        _iter_events,
        _match_game,
        _player_key,
        _resolve_player,
        _rung_mid_prices,
        _roster_index,
        _week_context,
    )
    from data.nflverse_loader import load_schedules

    context = _week_context(season, week)
    if not context:
        return {}
    sched = load_schedules([season])
    wk = sched[sched["week"] == week]
    games = [
        (str(getattr(r, "gameday", "")), str(r.away_team), str(r.home_team), str(r.game_id))
        for r in wk.itertuples(index=False)
    ]
    roster = _roster_index(season, set(context))

    lines: dict[str, list[float]] = {}
    with _client() as client:
        for series, stat in _SERIES_STAT.items():
            try:
                events = list(_iter_events(client, series))
            except Exception as exc:  # noqa: BLE001
                _log.warning("market lines: %s unavailable (%s)", series, exc)
                continue
            for event in events:
                event_ticker = str(event.get("event_ticker", ""))
                if not _match_game(event_ticker, games):
                    continue
                by_player: dict[str, list[dict]] = {}
                for market in event.get("markets") or []:
                    pkey = _player_key(str(market.get("ticker", "")), event_ticker)
                    if pkey:
                        by_player.setdefault(pkey, []).append(market)
                for pkey, rungs in by_player.items():
                    rung = _coinflip_rung(rungs)
                    if rung is None or rung.get("floor_strike") is None:
                        continue
                    sub_title = str(
                        rung.get("yes_sub_title") or rung.get("no_sub_title") or ""
                    )
                    player = _resolve_player(sub_title, pkey, roster)
                    if player is None:
                        continue
                    mids = _rung_mid_prices(rung)
                    if mids is None:
                        continue
                    # Keep the traded strike and the price the market puts on it.
                    # The pair is a probability statement — "P(stat >= K) = p" —
                    # which is far more information than a bare line.
                    lines[_key(player.player_id, stat)] = [
                        float(rung["floor_strike"]),
                        float(mids[0]),
                    ]
    return lines


def player_stat_lines(
    settings: AppSettings | None, season: int, week: int
) -> dict[str, list[float]]:
    """{"<player_id>|<stat>": [traded strike, market P(stat >= strike)]}, or {}.

    Never raises: a market outage degrades to an empty map and the caller keeps
    its own priors.
    """
    cached = _read_cache(season, week)
    if cached is not None:
        return cached
    try:
        lines = _fetch(season, week)
    except Exception:  # noqa: BLE001 - market data is an enhancement, never a gate
        _log.warning("market lines: fetch failed for %s wk %s", season, week, exc_info=True)
        return {}
    _write_cache(season, week, lines)
    return lines


def market_quote(
    lines: dict[str, list[float]], player_id: str, stat: str
) -> tuple[float, float] | None:
    """(strike, market probability the stat clears it) or None."""
    value = lines.get(_key(player_id, stat))
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        return float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
