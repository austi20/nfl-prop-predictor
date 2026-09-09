"""Thin read-only exposure of the nflverse schedule + roster tables.

The GLM/replay endpoints only see player-week stats; the fantasy and
upcoming-slate views also need "who plays whom in week N" and "who is on the
roster". Both loaders already parquet-cache, so this just shapes the frame.
"""
from __future__ import annotations

import math
import warnings
from functools import lru_cache

import pandas as pd

from api.schemas import GameRow, RosterPlayer
from data.nflverse_loader import load_rosters, load_schedules


def _clean_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value)


def _clean_int(value: object) -> int | None:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_score(value: object) -> float | None:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=8)
def _schedule_frame(season: int) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return load_schedules([season])


@lru_cache(maxsize=8)
def _roster_frame(season: int) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return load_rosters([season])


def get_schedule(season: int, week: int | None = None) -> list[GameRow]:
    df = _schedule_frame(season)
    if "week" in df.columns and week is not None:
        df = df[df["week"] == week]
    games: list[GameRow] = []
    for row in df.sort_values(["week", "gameday", "game_id"], na_position="last").itertuples(index=False):
        gid = _clean_str(getattr(row, "game_id", ""))
        if not gid:
            continue
        games.append(
            GameRow(
                game_id=gid,
                week=int(getattr(row, "week", 0) or 0),
                gameday=_clean_str(getattr(row, "gameday", "")),
                weekday=_clean_str(getattr(row, "weekday", "")),
                gametime=_clean_str(getattr(row, "gametime", "")),
                away_team=_clean_str(getattr(row, "away_team", "")),
                home_team=_clean_str(getattr(row, "home_team", "")),
                roof=_clean_str(getattr(row, "roof", "")),
                surface=_clean_str(getattr(row, "surface", "")),
                stadium=_clean_str(getattr(row, "stadium", "")),
                away_score=_clean_score(getattr(row, "away_score", None)),
                home_score=_clean_score(getattr(row, "home_score", None)),
            )
        )
    return games


_SKILL_POSITIONS = {"QB", "RB", "FB", "WR", "TE"}


def get_roster(
    season: int,
    *,
    team: str | None = None,
    position: str | None = None,
    status: str | None = "ACT",
    skill_only: bool = False,
) -> tuple[list[RosterPlayer], int | None]:
    df = _roster_frame(season)
    week_val = _clean_int(df["week"].max()) if "week" in df.columns and len(df) else None

    if team and "team" in df.columns:
        df = df[df["team"].astype(str).str.upper() == team.upper()]
    if position and "position" in df.columns:
        wanted = {p.strip().upper() for p in position.split(",") if p.strip()}
        df = df[df["position"].astype(str).str.upper().isin(wanted)]
    elif skill_only and "position" in df.columns:
        df = df[df["position"].astype(str).str.upper().isin(_SKILL_POSITIONS)]
    if status and "status" in df.columns:
        df = df[df["status"].astype(str).str.upper() == status.upper()]

    players: list[RosterPlayer] = []
    sort_cols = [c for c in ("team", "position", "depth_chart_position", "player_name") if c in df.columns]
    for row in df.sort_values(sort_cols).itertuples(index=False) if sort_cols else df.itertuples(index=False):
        pid = _clean_str(getattr(row, "player_id", ""))
        if not pid:
            continue
        players.append(
            RosterPlayer(
                player_id=pid,
                player_name=_clean_str(getattr(row, "player_name", "")),
                team=_clean_str(getattr(row, "team", "")),
                position=_clean_str(getattr(row, "position", "")),
                depth_chart_position=_clean_str(getattr(row, "depth_chart_position", "")),
                jersey_number=_clean_int(getattr(row, "jersey_number", None)),
                status=_clean_str(getattr(row, "status", "")),
                years_exp=_clean_int(getattr(row, "years_exp", None)),
                headshot_url=_clean_str(getattr(row, "headshot_url", "")),
            )
        )
    return players, week_val
