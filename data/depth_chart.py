"""Depth-chart rank - which slot a player actually occupies right now.

The trailing-form projector averages a player's last 8 games, so it encodes the
role he *had*. An offseason promotion (the RB2 who is now RB1 because the starter
left) produces no in-season usage trend, so `data/usage.py` cannot see it. Depth
rank can, and nflverse refreshes it daily.

nflverse publishes two incompatible schemas. Through 2024 it is one row per
player per week with a string `depth_team`; from 2025 it is dated ESPN snapshots
with an integer `pos_rank`. Both normalize to
`(gsis_id, season, week, team, position, rank)`.
"""
from __future__ import annotations

from functools import lru_cache

import pandas as pd

from data import injuries
from data.nflverse_loader import load_depth_charts, load_schedules

_SKILL_POSITIONS = ("QB", "RB", "WR", "TE")
_MODERN_OFFENSE_GROUP = "3WR 1TE"

_COLUMNS = ["gsis_id", "season", "week", "team", "position", "rank", "asof"]

# Legacy `depth_team` never exceeds 3, so every bucket caps at 3+ to keep the
# two eras comparable.
_MAX_RANK = 3

_TRAILING_WINDOW = 8  # mirrors fantasy_service._TRAILING_WINDOW


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=_COLUMNS)


def _normalize_legacy(df: pd.DataFrame) -> pd.DataFrame:
    """2015-2024: weekly rows, string `depth_team`, offense/defense in one frame."""
    if df.empty or "depth_team" not in df.columns:
        return _empty()
    rows = df[
        (df["formation"].astype(str) == "Offense")
        & (df["game_type"].astype(str) == "REG")
        & (df["position"].astype(str).str.upper().isin(_SKILL_POSITIONS))
    ].copy()
    if rows.empty:
        return _empty()
    out = pd.DataFrame(
        {
            "gsis_id": rows["gsis_id"].astype(str),
            "season": pd.to_numeric(rows["season"], errors="coerce"),
            "week": pd.to_numeric(rows["week"], errors="coerce"),
            "team": rows["club_code"].astype(str),
            "position": rows["position"].astype(str).str.upper(),
            "rank": pd.to_numeric(rows["depth_team"], errors="coerce"),
        }
    )
    out = out.dropna().astype({"season": int, "week": int, "rank": int})
    out["asof"] = pd.NaT
    return out.reset_index(drop=True)


@lru_cache(maxsize=16)
def _week_starts(season: int) -> tuple[tuple[int, pd.Timestamp], ...]:
    """(week, first kickoff) for the season's regular season, ascending.

    The modern depth-chart feed has no week column, only a snapshot timestamp,
    so the schedule is what turns a date into an NFL week.
    """
    try:
        sched = load_schedules([int(season)])
    except Exception:  # noqa: BLE001 - an unpublished season 404s
        return ()
    if sched.empty or "gameday" not in sched.columns or "week" not in sched.columns:
        return ()
    rows = sched
    if "game_type" in rows.columns:
        rows = rows[rows["game_type"].astype(str) == "REG"]
    rows = rows.assign(_d=pd.to_datetime(rows["gameday"], errors="coerce", utc=True)).dropna(
        subset=["_d"]
    )
    if rows.empty:
        return ()
    starts = rows.groupby("week")["_d"].min().sort_index()
    return tuple((int(w), ts) for w, ts in starts.items())


def _assign_week(stamps: pd.Series, season: int) -> pd.Series:
    """Map snapshot timestamps onto NFL weeks. Preseason snapshots become 0."""
    edges = _week_starts(season)
    if not edges:
        return pd.Series(0, index=stamps.index, dtype="int64")
    weeks = [w for w, _ in edges]
    bounds = pd.DatetimeIndex([ts for _, ts in edges])
    # searchsorted gives the number of kickoffs at or before each stamp; 0 means
    # the snapshot predates week 1.
    idx = bounds.searchsorted(pd.DatetimeIndex(stamps), side="right")
    return pd.Series(
        [0 if i == 0 else weeks[i - 1] for i in idx], index=stamps.index, dtype="int64"
    )


def _normalize_modern(df: pd.DataFrame, *, season: int) -> pd.DataFrame:
    """2025+: dated ESPN snapshots, published daily.

    Every snapshot is kept, not just the newest one: the in-season progression is
    exactly what `prior_rank` needs to know which role a player's trailing games
    were played in. Snapshots are collapsed to the last one per (player, week),
    and `asof` preserves the true timestamp so `current_rank` can still pick the
    freshest chart.
    """
    if df.empty or "pos_rank" not in df.columns:
        return _empty()
    rows = df[
        (df["pos_grp"].astype(str) == _MODERN_OFFENSE_GROUP)
        & (df["pos_abb"].astype(str).str.upper().isin(_SKILL_POSITIONS))
    ].copy()
    if rows.empty:
        return _empty()
    rows["_dt"] = pd.to_datetime(rows["dt"], errors="coerce", utc=True)
    rows = rows.dropna(subset=["_dt"])
    if rows.empty:
        return _empty()
    out = pd.DataFrame(
        {
            "gsis_id": rows["gsis_id"].astype(str),
            "season": int(season),
            "week": _assign_week(rows["_dt"], int(season)),
            "team": rows["team"].astype(str),
            "position": rows["pos_abb"].astype(str).str.upper(),
            "rank": pd.to_numeric(rows["pos_rank"], errors="coerce"),
            "asof": rows["_dt"],
        }
    ).dropna(subset=["gsis_id", "rank"])
    if out.empty:
        return _empty()
    out = (
        out.sort_values("asof")
        .groupby(["gsis_id", "season", "week"], as_index=False)
        .last()
    )
    return out.astype({"season": int, "week": int, "rank": int}).reset_index(drop=True)


def bucket(rank: int | None, position: str) -> int | None:
    """Collapse a raw rank into the comparable bucket (1, 2, or 3+)."""
    if rank is None:
        return None
    r = int(rank)
    if r < 1:
        return None
    if position.upper().strip() in {"QB", "TE"}:
        return 1 if r == 1 else 2
    return min(r, _MAX_RANK)


@lru_cache(maxsize=8)
def rank_frame(seasons: tuple[int, ...]) -> pd.DataFrame:
    """Normalized depth ranks across `seasons`, both schemas merged."""
    if not seasons:
        return _empty()
    parts: list[pd.DataFrame] = []
    for season in seasons:
        try:
            raw = load_depth_charts([int(season)])
        except Exception:  # noqa: BLE001 - an unpublished season 404s
            continue
        if raw.empty:
            continue
        part = (
            _normalize_modern(raw, season=int(season))
            if "pos_rank" in raw.columns
            else _normalize_legacy(raw)
        )
        if not part.empty:
            parts.append(part)
    if not parts:
        return _empty()
    return pd.concat(parts, ignore_index=True)


def _player_rows(gsis_id: str, seasons: tuple[int, ...]) -> pd.DataFrame:
    frame = rank_frame(seasons)
    if frame.empty:
        return frame
    return frame[frame["gsis_id"] == gsis_id]


@lru_cache(maxsize=4096)
def current_rank(gsis_id: str, season: int, week: int, seasons: tuple[int, ...]) -> int | None:
    """The live depth rank: the most recent listing at or before (season, week)."""
    rows = _player_rows(gsis_id, seasons)
    if rows.empty:
        return None
    before = rows[
        (rows["season"] < season) | ((rows["season"] == season) & (rows["week"] <= week))
    ]
    if before.empty:
        return None
    ordered = before.sort_values(["season", "week", "asof"], na_position="first")
    return int(ordered.iloc[-1]["rank"])


# Not cached: the injury report it reads changes through the week.
def effective_rank(gsis_id: str, season: int, week: int, seasons: tuple[int, ...]) -> int | None:
    """`current_rank`, but stepping over teammates who are likely out this week.

    The depth chart is republished daily and still lists an injured starter at
    rank 1: it tracks the roster's pecking order, not who is available on Sunday.
    So a backup thrust into the job keeps his backup rank, the trailing blend
    regresses him toward the backup baseline, and the board prices a huge "under"
    against a line the market has already moved for the promotion.

    Re-ranking among the available players is enough to fix that, because the
    rank is what selects the baseline a projection regresses toward, and
    `role_change_retention` already discounts trailing form that was earned in a
    different job.
    """
    rows = _player_rows(gsis_id, seasons)
    if rows.empty:
        return None
    before = rows[
        (rows["season"] < season) | ((rows["season"] == season) & (rows["week"] <= week))
    ]
    if before.empty:
        return None
    listing = before.sort_values(["season", "week", "asof"], na_position="first").iloc[-1]
    own_rank = int(listing["rank"])

    team, position = str(listing["team"]), str(listing["position"])
    if not team or not position:
        return own_rank

    out = injuries.unavailable(int(season), int(week))
    if not out:
        return own_rank

    frame = rank_frame(seasons)
    group = frame[
        (frame["season"] == int(listing["season"]))
        & (frame["week"] == int(listing["week"]))
        & (frame["team"] == team)
        & (frame["position"] == position)
    ]
    if group.empty:
        return own_rank
    # One row per player, freshest listing, so a re-published chart does not
    # count the same team-mate twice.
    group = group.sort_values("asof", na_position="first").groupby("gsis_id", as_index=False).last()

    ahead_out = sum(
        1
        for r in group.itertuples(index=False)
        if int(r.rank) < own_rank and str(r.gsis_id) in out
    )
    if not ahead_out or str(gsis_id) in out:
        return own_rank
    return max(1, own_rank - ahead_out)


@lru_cache(maxsize=4096)
def game_ranks(gsis_id: str, seasons: tuple[int, ...]) -> dict[tuple[int, int], int]:
    """{(season, week): depth rank} for every week this player was listed.

    Lets a caller ask which role a particular trailing game was played in, rather
    than only the modal role `prior_rank` reports.
    """
    rows = _player_rows(gsis_id, seasons)
    if rows.empty:
        return {}
    played = rows[rows["week"] > 0]
    return {
        (int(r.season), int(r.week)): int(r.rank)
        for r in played.itertuples(index=False)
    }


@lru_cache(maxsize=4096)
def prior_rank(gsis_id: str, season: int, week: int, seasons: tuple[int, ...]) -> int | None:
    """The modal rank across the games the trailing window actually covers -
    i.e. the role the trailing stats encode. Excludes week-0 snapshot rows."""
    rows = _player_rows(gsis_id, seasons)
    if rows.empty:
        return None
    played = rows[rows["week"] > 0]
    before = played[
        (played["season"] < season) | ((played["season"] == season) & (played["week"] < week))
    ].sort_values(["season", "week"]).tail(_TRAILING_WINDOW)
    if before.empty:
        return None
    return int(before["rank"].mode().iloc[0])
