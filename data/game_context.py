"""Per-(season, week, team) situational context derived from the nflverse
schedule table.

The schedule already carries the closing Vegas line, both head coaches, rest
days, roof and venue for every game — including upcoming ones once the market
posts. This module reshapes it into one team-perspective row so the fantasy
projection can factor in home/away, game script (implied team points), coaching
and rest without a second data source.

`spread_line` in nflverse is from the home team's perspective: a positive value
means the home team is favored by that many points, so
    home_implied = total_line / 2 + spread_line / 2
    away_implied = total_line / 2 - spread_line / 2
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from data.nflverse_loader import load_schedules

# League-average implied points per team-game (2018-2025 closing lines): ~22.6.
LEAGUE_IMPLIED_POINTS = 22.6
# League-average points/game used as the coaching baseline.
LEAGUE_POINTS_PER_GAME = 22.9

_CONTEXT_COLUMNS = (
    "season",
    "week",
    "team",
    "opponent",
    "is_home",
    "implied_total",
    "team_implied",
    "opp_implied",
    "team_spread",  # team perspective: negative = favored
    "coach",
    "opp_coach",
    "rest",
    "opp_rest",
    "roof",
    "stadium",
    "div_game",
)


def _team_rows(sched: pd.DataFrame) -> pd.DataFrame:
    """Melt each game into two team-perspective rows."""
    sched = sched.copy()
    sched["home_implied"] = sched["total_line"] / 2.0 + sched["spread_line"] / 2.0
    sched["away_implied"] = sched["total_line"] / 2.0 - sched["spread_line"] / 2.0

    home = pd.DataFrame(
        {
            "season": sched["season"],
            "week": sched["week"],
            "team": sched["home_team"],
            "opponent": sched["away_team"],
            "is_home": 1,
            "implied_total": sched["total_line"],
            "team_implied": sched["home_implied"],
            "opp_implied": sched["away_implied"],
            "team_spread": -sched["spread_line"],  # home favored -> negative
            "coach": sched.get("home_coach"),
            "opp_coach": sched.get("away_coach"),
            "rest": sched.get("home_rest"),
            "opp_rest": sched.get("away_rest"),
            "roof": sched.get("roof"),
            "stadium": sched.get("stadium"),
            "div_game": sched.get("div_game"),
        }
    )
    away = pd.DataFrame(
        {
            "season": sched["season"],
            "week": sched["week"],
            "team": sched["away_team"],
            "opponent": sched["home_team"],
            "is_home": 0,
            "implied_total": sched["total_line"],
            "team_implied": sched["away_implied"],
            "opp_implied": sched["home_implied"],
            "team_spread": sched["spread_line"],  # away favored -> negative
            "coach": sched.get("away_coach"),
            "opp_coach": sched.get("home_coach"),
            "rest": sched.get("away_rest"),
            "opp_rest": sched.get("home_rest"),
            "roof": sched.get("roof"),
            "stadium": sched.get("stadium"),
            "div_game": sched.get("div_game"),
        }
    )
    return pd.concat([home, away], ignore_index=True)


@lru_cache(maxsize=8)
def game_context_frame(seasons: tuple[int, ...]) -> pd.DataFrame:
    """One row per (season, week, team) with situational context. Cached per
    season span; safe to call from the slate loop."""
    if not seasons:
        return pd.DataFrame(columns=_CONTEXT_COLUMNS)
    sched = load_schedules(list(seasons))
    if sched.empty:
        return pd.DataFrame(columns=_CONTEXT_COLUMNS)
    if "game_type" in sched.columns:
        sched = sched[sched["game_type"].astype(str).str.upper().isin({"REG", "POST"})]
    rows = _team_rows(sched)
    for col in ("season", "week", "is_home"):
        rows[col] = pd.to_numeric(rows[col], errors="coerce").astype("Int64")
    rows["team"] = rows["team"].astype(str)
    rows["opponent"] = rows["opponent"].astype(str)
    return rows.reset_index(drop=True)


def is_home_map(seasons: tuple[int, ...]) -> dict[tuple[int, int, str], int]:
    """(season, week, team) -> 1 home / 0 away. For backfilling the weekly frame."""
    frame = game_context_frame(seasons)
    out: dict[tuple[int, int, str], int] = {}
    for row in frame.itertuples(index=False):
        if pd.isna(row.season) or pd.isna(row.week):
            continue
        out[(int(row.season), int(row.week), str(row.team))] = int(row.is_home or 0)
    return out


def attach_is_home(df: pd.DataFrame) -> pd.Series:
    """0.0/1.0 home flag per row. Precedence: an explicit non-null ``is_home``
    already on the row (an upcoming-row override) wins; otherwise join from the
    schedule on (season, week, recent_team); otherwise the neutral 0.5 baseline
    (mid-season trades, team-abbrev drift, seasons the schedule lacks)."""
    n = len(df)
    if n == 0 or not {"season", "week", "recent_team"}.issubset(df.columns):
        base = df["is_home"] if "is_home" in df.columns else pd.Series(0.5, index=df.index)
        return pd.to_numeric(base, errors="coerce").fillna(0.5)

    seasons = tuple(sorted({int(s) for s in pd.to_numeric(df["season"], errors="coerce").dropna().unique()}))
    hmap = is_home_map(seasons)

    def _lookup(row: tuple) -> float:
        try:
            key = (int(row[0]), int(row[1]), str(row[2]))
        except (TypeError, ValueError):
            return np.nan
        val = hmap.get(key)
        return float(val) if val is not None else np.nan

    joined = pd.Series(
        [_lookup(r) for r in zip(df["season"], df["week"], df["recent_team"])],
        index=df.index,
    )
    existing = (
        pd.to_numeric(df["is_home"], errors="coerce") if "is_home" in df.columns
        else pd.Series(np.nan, index=df.index)
    )
    # Explicit override wins, then the schedule join, then neutral.
    return existing.fillna(joined).fillna(0.5)


def context_for(
    seasons: tuple[int, ...], *, season: int, week: int, team: str
) -> dict | None:
    """The context row for one team-game, or None if the schedule has no match."""
    frame = game_context_frame(seasons)
    hit = frame[
        (frame["season"] == season)
        & (frame["week"] == week)
        & (frame["team"].str.upper() == team.upper())
    ]
    if hit.empty:
        return None
    row = hit.iloc[0].to_dict()

    def _num(value: object) -> float | None:
        try:
            if value is None or (isinstance(value, float) and np.isnan(value)):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    return {
        "is_home": None if pd.isna(row.get("is_home")) else int(row["is_home"]),
        "implied_total": _num(row.get("implied_total")),
        "team_implied": _num(row.get("team_implied")),
        "opp_implied": _num(row.get("opp_implied")),
        "team_spread": _num(row.get("team_spread")),
        "coach": (str(row["coach"]) if row.get("coach") not in (None, "") and not pd.isna(row.get("coach")) else ""),
        "opp_coach": (str(row["opp_coach"]) if row.get("opp_coach") not in (None, "") and not pd.isna(row.get("opp_coach")) else ""),
        "rest": _num(row.get("rest")),
        "opp_rest": _num(row.get("opp_rest")),
        "roof": (str(row["roof"]) if row.get("roof") not in (None, "") and not pd.isna(row.get("roof")) else ""),
        "stadium": (str(row["stadium"]) if row.get("stadium") not in (None, "") and not pd.isna(row.get("stadium")) else ""),
        "div_game": None if pd.isna(row.get("div_game")) else int(row["div_game"]),
    }


@lru_cache(maxsize=16)
def _game_id_index(seasons: tuple[int, ...]) -> dict[tuple[int, int, str], str]:
    sched = load_schedules(list(seasons)) if seasons else pd.DataFrame()
    out: dict[tuple[int, int, str], str] = {}
    if sched.empty or "game_id" not in sched.columns:
        return out
    for row in sched.itertuples(index=False):
        gid = str(getattr(row, "game_id", "") or "")
        if not gid:
            continue
        try:
            key_season, key_week = int(row.season), int(row.week)
        except (TypeError, ValueError):
            continue
        out[(key_season, key_week, str(row.home_team))] = gid
        out[(key_season, key_week, str(row.away_team))] = gid
    return out


def game_id_for(seasons: tuple[int, ...], *, season: int, week: int, team: str) -> str:
    """The nflverse game_id for a team's game that week, or "" if unknown."""
    return _game_id_index(seasons).get((season, week, str(team).upper()), "")


@lru_cache(maxsize=8)
def coach_points_per_game(seasons: tuple[int, ...]) -> dict[str, tuple[float, int]]:
    """coach name -> (points/game, games) over completed games in the window.

    Only games with a recorded score count, so an upcoming slate does not
    dilute the mean. Used as a coaching-quality prior for offenses.
    """
    sched = load_schedules(list(seasons))
    if sched.empty or "home_score" not in sched.columns:
        return {}
    if "game_type" in sched.columns:
        sched = sched[sched["game_type"].astype(str).str.upper().isin({"REG", "POST"})]
    home = sched[["home_coach", "home_score"]].rename(
        columns={"home_coach": "coach", "home_score": "pts"}
    )
    away = sched[["away_coach", "away_score"]].rename(
        columns={"away_coach": "coach", "away_score": "pts"}
    )
    tg = pd.concat([home, away], ignore_index=True).dropna(subset=["pts", "coach"])
    tg = tg[tg["coach"].astype(str) != ""]
    grouped = tg.groupby("coach")["pts"].agg(["mean", "size"])
    return {str(idx): (float(r["mean"]), int(r["size"])) for idx, r in grouped.iterrows()}
