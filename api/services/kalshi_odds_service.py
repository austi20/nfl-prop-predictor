"""Kalshi NFL game lines -> implied team points, as a fresher overlay on the
nflverse schedule's closing line.

Kalshi lists laddered per-game markets: ``KXNFLTOTAL`` ("Over 26.5 points
scored") and ``KXNFLSPREAD`` ("Seattle wins by over 3.5 points"). We read the
open events unauthenticated, invert each ladder to the point where P(Yes) ~ 0.5,
and return one implied total + spread per nflverse ``game_id``.

Markets for a game are usually unpriced until close to kickoff, so this is
strictly best-effort — an empty result means "use the schedule line".
"""
from __future__ import annotations

import os
import re
from functools import lru_cache

from data.nflverse_loader import load_schedules

_KALSHI_BASE = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2")
_EVENT_RE = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})([A-Z]{4,6})$")
_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
# Kalshi abbreviations that differ from nflverse (checked as substrings of the
# ticker team-blob, so both spellings are tried).
_TEAM_ALIASES = {"LA": ("LA", "LAR"), "JAX": ("JAX", "JAC"), "WAS": ("WAS", "WSH")}


def _client():
    from api.trading.kalshi.client import KalshiClient

    return KalshiClient(
        access_key=os.getenv("KALSHI_API_KEY_ID", ""),
        private_key_pem=os.getenv("KALSHI_PRIVATE_KEY_PATH", ""),
        base_url=_KALSHI_BASE,
    )


def _mid_yes_prob(market: dict) -> float | None:
    bid, ask = market.get("yes_bid"), market.get("yes_ask")
    if bid is not None and ask is not None and (bid or ask):
        return (float(bid) + float(ask)) / 200.0
    last = market.get("last_price")
    return float(last) / 100.0 if last else None


def _invert_ladder(markets: list[dict]) -> float | None:
    """Each market is P(value > floor_strike). Find the strike where P crosses
    0.5 and linearly interpolate."""
    pts = []
    for m in markets:
        strike = m.get("floor_strike")
        prob = _mid_yes_prob(m)
        if strike is None or prob is None:
            continue
        pts.append((float(strike), prob))
    if len(pts) < 2:
        return None
    pts.sort()
    for (k0, p0), (k1, p1) in zip(pts, pts[1:]):
        if (p0 - 0.5) * (p1 - 0.5) <= 0 and p0 != p1:
            return k0 + (k1 - k0) * (p0 - 0.5) / (p0 - p1)
    # no crossing — extrapolate from the nearest point
    k, p = min(pts, key=lambda kp: abs(kp[1] - 0.5))
    return k + (p - 0.5) * 14.0  # ~14 pts per unit of probability near the middle


def _event_game_key(event_ticker: str) -> tuple[str, str] | None:
    """'KXNFLTOTAL-26SEP13ATLPIT' -> ('2026-09-13', 'ATLPIT'). The team blob is
    matched against the schedule by substring, so the ambiguous 2/3-char split
    (SFLAR = SF+LAR or SFL+AR) never has to be resolved here."""
    m = _EVENT_RE.search(event_ticker)
    if not m:
        return None
    yy, mon, dd, blob = m.groups()
    if mon not in _MONTHS:
        return None
    return (f"20{yy}-{_MONTHS[mon]:02d}-{int(dd):02d}", blob)


def _blob_has_team(blob: str, team: str) -> bool:
    return any(alias in blob for alias in _TEAM_ALIASES.get(team.upper(), (team.upper(),)))


@lru_cache(maxsize=8)
def nfl_game_lines(season: int, week: int) -> dict[str, dict]:
    """{game_id: {"total": float|None, "spread": float|None, "source": "kalshi"}}
    for games in (season, week) that have a priced Kalshi market. {} on any
    failure or when nothing is priced."""
    try:
        sched = load_schedules([season])
        wk = sched[sched["week"] == week]
        games = [
            (str(getattr(r, "gameday", "")), str(r.away_team), str(r.home_team), str(r.game_id))
            for r in wk.itertuples(index=False)
        ]

        out: dict[str, dict] = {}
        with _client() as client:
            for series, field in (("KXNFLTOTAL", "total"), ("KXNFLSPREAD", "spread")):
                try:
                    events = client.get_events(series_ticker=series, status="open", limit=100)
                except Exception:  # noqa: BLE001
                    continue
                for ev in events.get("events", []):
                    key = _event_game_key(str(ev.get("event_ticker", "")))
                    if not key:
                        continue
                    gd, blob = key
                    gid = next(
                        (g for (d, a, h, g) in games
                         if d == gd and _blob_has_team(blob, a) and _blob_has_team(blob, h)),
                        "",
                    )
                    if not gid:
                        continue
                    value = _invert_ladder(ev.get("markets") or [])
                    if value is None:
                        continue
                    out.setdefault(gid, {"total": None, "spread": None, "source": "kalshi"})
                    out[gid][field] = value
        # keep only games where we actually got a total
        return {g: v for g, v in out.items() if v.get("total") is not None}
    except Exception:  # noqa: BLE001
        return {}
