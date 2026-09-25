"""How likely a player is to miss the game, from the weekly injury report.

The prop board's worst edges sat on backup quarterbacks: Kalshi prices Drew Lock
for a starter's volume because Sam Darnold did not practise, while the model
projects him on his backup usage and calls a huge "under". The depth chart does
not help -- it is republished daily but still lists the injured starter at rank
1, because it tracks the roster's pecking order, not who is available on Sunday.

What the report gives is a designation, and the designations mean very different
things. The rates below are measured, not assumed: `scripts/diag/availability_model.py`
joins every skill-position injury row from 2022-2025 to whether that player
actually recorded a snap that week.

The important split is inside "did not practise": a real injury misses 59% of
the time, while "not injury related - resting player" -- a veteran's day off --
misses only 13%. Treating every DNP as an absence would bench half the league's
starters every Wednesday.
"""
from __future__ import annotations

from functools import lru_cache

import pandas as pd

from data.nflverse_loader import load_injuries

# P(misses the game), measured over 2022-2025 skill-position rows. Sample sizes
# are in the comments; see scripts/diag/availability_model.py to regenerate.
_OUT = 1.000          # n=1325, no exceptions in four seasons
_DOUBTFUL = 0.995     # n=201
_QUESTIONABLE = 0.458  # n=1764

# No game status filed yet -- normal before Friday, so practice is all we have.
_NO_STATUS_DNP_INJURED = 0.591  # n=127
_NO_STATUS_DNP_RESTING = 0.132  # n=159
_NO_STATUS_LIMITED = 0.123      # n=488
_NO_STATUS_FULL = 0.187         # n=2909

# A player who appears nowhere on the report. Not zero -- people are ruled out
# after it is published -- but low enough never to trigger a promotion.
_NOT_REPORTED = 0.02

# Above this, treat the player as absent when ranking his position group. A
# "Questionable" starter (0.458) stays ahead of his backup, which is right: he
# plays more often than not.
ABSENCE_THRESHOLD = 0.5


def _norm(value: object) -> str:
    return "" if value is None else str(value).strip().lower()


def absence_probability(
    report_status: object, practice_status: object, practice_injury: object = None
) -> float:
    """P(this player misses the game), from one injury-report row."""
    status = _norm(report_status)
    if status.startswith("out"):
        return _OUT
    if status.startswith("doubtful"):
        return _DOUBTFUL
    if status.startswith("questionable"):
        return _QUESTIONABLE

    practice = _norm(practice_status)
    if "did not participate" in practice:
        # "Not injury related - resting player" is a scheduled day off, not a
        # knock, and those players nearly always play.
        return _NO_STATUS_DNP_RESTING if "resting" in _norm(practice_injury) else _NO_STATUS_DNP_INJURED
    if "limited" in practice:
        return _NO_STATUS_LIMITED
    if "full" in practice:
        return _NO_STATUS_FULL
    return _NOT_REPORTED


@lru_cache(maxsize=8)
def _season_report(season: int) -> pd.DataFrame:
    try:
        frame = load_injuries([int(season)])
    except Exception:  # noqa: BLE001 - an unpublished season 404s
        return pd.DataFrame()
    return frame if frame is not None else pd.DataFrame()


@lru_cache(maxsize=64)
def absence_probabilities(season: int, week: int) -> dict[str, float]:
    """{gsis_id: P(misses this week's game)} for everyone on the report.

    Never raises: no report means an empty map and every caller treats the whole
    league as available, which is the behaviour before this module existed.
    """
    frame = _season_report(season)
    if frame.empty or "gsis_id" not in frame.columns:
        return {}
    rows = frame
    if "week" in rows.columns:
        rows = rows[pd.to_numeric(rows["week"], errors="coerce") == int(week)]
    if rows.empty:
        return {}

    out: dict[str, float] = {}
    for row in rows.itertuples(index=False):
        gsis = str(getattr(row, "gsis_id", "") or "")
        if not gsis:
            continue
        out[gsis] = absence_probability(
            getattr(row, "report_status", None),
            getattr(row, "practice_status", None),
            getattr(row, "practice_primary_injury", None),
        )
    return out


def unavailable(season: int, week: int, *, threshold: float = ABSENCE_THRESHOLD) -> frozenset[str]:
    """Players likely enough to miss that the depth chart should step over them."""
    return frozenset(
        gsis for gsis, p in absence_probabilities(season, week).items() if p >= threshold
    )
