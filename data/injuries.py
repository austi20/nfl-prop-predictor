"""Who is hurt this week, and what it does to his output.

Two sources, because neither is enough alone:

- nflverse's weekly injury file has every practice report but lags a day or
  more, and often has no game designation yet when the app is used.
- ESPN's public injuries feed is live (coach statements, Friday designations,
  IR) but only describes the upcoming game.

For the week in progress the more severe game designation from either source
wins; practice-only rows count only when nobody has designated the player.
Past weeks use nflverse alone.

What a status is worth was measured on regulars (8+ touches a game) over
2022-2025 by `scripts/diag/injury_impact.py`. Doubtful is out: not one of 88
regulars listed doubtful played.
"""
from __future__ import annotations

import time
from functools import lru_cache

import pandas as pd
import requests

from data.game_context import week_in_progress
from data.nflverse_loader import load_ids, load_injuries, load_schedules

_ESPN_INJURIES = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
_TTL_SECONDS = 15 * 60  # designations land through the day; refetch often

# status -> (P(plays), output when he plays as a share of normal). n per row.
_IMPACT: dict[str, tuple[float, float]] = {
    "out": (0.0, 0.0),                  # n=448, plus IR / PUP / suspended
    "doubtful": (0.0, 0.0),             # n=88, none played
    "questionable": (0.692, 0.835),     # n=671
    "dnp_injured": (0.449, 0.793),      # n=49, no game status filed
    "dnp_resting": (0.967, 0.829),      # n=90, veteran rest day
    "limited": (0.966, 0.943),          # n=264, no game status filed
    "full": (0.958, 0.935),             # n=1348, on the report, full practice
    "not_reported": (1.0, 1.0),
}

_LABELS = {
    "out": "Out",
    "doubtful": "Doubtful",
    "questionable": "Questionable",
    "dnp_injured": "Did not practice",
    "dnp_resting": "Rest day",
    "limited": "Limited in practice",
    "full": "Full practice",
    "not_reported": "Not on the report",
}

# Game designations, most severe first. Practice rows rank below all of them.
_DESIGNATIONS = ("out", "doubtful", "questionable")

# An Out row still multiplies the stat means; exact zero breaks the families.
_OUT_FLOOR = 0.05

# Above this, the depth chart steps over the player. Questionable (0.31) stays
# ahead of his backup: he plays more often than not.
ABSENCE_THRESHOLD = 0.5

_OUT_WORDS = ("out", "injured reserve", "reserve", "pup", "physically unable",
              "suspen", "non-football")


def _norm(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip().lower()


def classify(report_status: object, practice_status: object = None, practice_injury: object = None) -> str:
    """One report row -> a key of `_IMPACT`."""
    status = _norm(report_status)
    if any(status.startswith(w) for w in _OUT_WORDS):
        return "out"
    if status.startswith("doubtful"):
        return "doubtful"
    if status.startswith("questionable"):
        return "questionable"

    practice = _norm(practice_status)
    if "did not participate" in practice:
        return "dnp_resting" if "resting" in _norm(practice_injury) else "dnp_injured"
    if "limited" in practice:
        return "limited"
    if "full" in practice:
        return "full"
    return "not_reported"


def absence_probability(report_status: object, practice_status: object = None, practice_injury: object = None) -> float:
    """P(this player misses the game), from one injury report row."""
    return 1.0 - _IMPACT[classify(report_status, practice_status, practice_injury)][0]


def output_multiplier(status: str) -> float:
    """Expected share of a player's normal output for this status."""
    p_play, workload = _IMPACT[status]
    return max(p_play * workload, _OUT_FLOOR)


def label(status: str) -> str:
    return _LABELS[status]


def _bucket() -> int:
    return int(time.time() // _TTL_SECONDS)


@lru_cache(maxsize=8)
def _season_report(season: int, _bucket: int) -> pd.DataFrame:
    try:
        frame = load_injuries([int(season)])
    except Exception:  # noqa: BLE001 - an unpublished season 404s
        return pd.DataFrame()
    return frame if frame is not None else pd.DataFrame()


@lru_cache(maxsize=4)
def _live_week(season: int, _bucket: int) -> int | None:
    try:
        return week_in_progress(load_schedules([int(season)]))
    except Exception:  # noqa: BLE001
        return None


@lru_cache(maxsize=1)
def _espn_to_gsis() -> dict[str, str]:
    ids = load_ids()
    ids = ids.dropna(subset=["espn_id", "gsis_id"])
    return {str(int(e)): str(g) for e, g in zip(ids["espn_id"], ids["gsis_id"])}


def _espn_athlete_id(entry: dict) -> str:
    # The feed carries the id only inside the player card link: .../id/4431611/name
    for link in entry.get("athlete", {}).get("links", []) or []:
        parts = str(link.get("href", "")).split("/id/")
        if len(parts) == 2:
            return parts[1].split("/")[0]
    return ""


@lru_cache(maxsize=2)
def _espn_report(_bucket: int) -> dict[str, tuple[str, str]]:
    """{gsis_id: (status key, ESPN short comment)} for the upcoming games."""
    try:
        resp = requests.get(_ESPN_INJURIES, timeout=15)
        resp.raise_for_status()
        teams = resp.json().get("injuries", []) or []
        crosswalk = _espn_to_gsis()
    except Exception:  # noqa: BLE001 - no live feed means nflverse alone
        return {}

    out: dict[str, tuple[str, str]] = {}
    for team in teams:
        for entry in team.get("injuries", []) or []:
            status = classify(entry.get("status"))
            if status not in _DESIGNATIONS:
                continue  # "Active": cleared, nothing to apply
            gsis = crosswalk.get(_espn_athlete_id(entry))
            if gsis:
                out[gsis] = (status, str(entry.get("shortComment", "") or ""))
    return out


def _more_severe(a: str, b: str) -> str:
    rank = {s: i for i, s in enumerate(_DESIGNATIONS)}
    return a if rank.get(a, 99) <= rank.get(b, 99) else b


def player_statuses(season: int, week: int) -> dict[str, tuple[str, str]]:
    """{gsis_id: (status key, source note)} for everyone reported this week.

    Never raises: no data means an empty map, and every caller treats the
    league as healthy.
    """
    bucket = _bucket()
    out: dict[str, tuple[str, str]] = {}

    frame = _season_report(int(season), bucket)
    if not frame.empty and "gsis_id" in frame.columns and "week" in frame.columns:
        rows = frame[pd.to_numeric(frame["week"], errors="coerce") == int(week)]
        for row in rows.itertuples(index=False):
            gsis = str(getattr(row, "gsis_id", "") or "")
            if not gsis:
                continue
            status = classify(
                getattr(row, "report_status", None),
                getattr(row, "practice_status", None),
                getattr(row, "practice_primary_injury", None),
            )
            if status != "not_reported":
                out[gsis] = (status, "NFL injury report")

    if _live_week(int(season), bucket) != int(week):
        return out

    for gsis, (espn_status, comment) in _espn_report(bucket).items():
        current = out.get(gsis, ("not_reported", ""))[0]
        if current in _DESIGNATIONS and _more_severe(current, espn_status) == current:
            continue
        note = f"ESPN: {comment}" if comment else "ESPN injury feed"
        out[gsis] = (espn_status, note)
    return out


def absence_probabilities(season: int, week: int) -> dict[str, float]:
    """{gsis_id: P(misses this week's game)} for everyone on the report."""
    return {
        gsis: 1.0 - _IMPACT[status][0]
        for gsis, (status, _note) in player_statuses(season, week).items()
    }


def unavailable(season: int, week: int, *, threshold: float = ABSENCE_THRESHOLD) -> frozenset[str]:
    """Players likely enough to miss that the depth chart should step over them."""
    return frozenset(
        gsis for gsis, p in absence_probabilities(season, week).items() if p >= threshold
    )
