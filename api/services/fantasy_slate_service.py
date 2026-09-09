"""Week-level fantasy board: project every rostered skill player for a slate.

`build_fantasy_summary` is per-player and runs a 5000-sim Monte Carlo plus four
context-factor passes, so projecting a whole week naively is minutes of work. We
keep it tractable by (1) enumerating only skill players on the rosters of teams
that actually play the requested week, (2) ranking them with a cheap trailing
fantasy-points/game estimate (no MC), and (3) running the full projection for the
top ``limit`` only. The response is cached per (season, week, scoring, limit) so
the ~30s first hit is paid once per process.
"""
from __future__ import annotations

import threading

import numpy as np
import pandas as pd

from api.schemas import FantasySlateEntry, FantasySlateResponse
from api.services.evaluation_service import scoring_weekly
from api.services.fantasy_service import (
    _TRAILING_REGRESS_GAMES,
    _TRAILING_STATS_BY_POSITION,
    _TRAILING_WINDOW,
    _baselines_for,
    build_fantasy_summary,
)
from api.services.nflverse_service import get_roster, get_schedule
from api.settings import AppSettings
from eval.fantasy_points import SCORING_PROFILES, ScoringMode

_SKILL_POSITIONS = ("QB", "RB", "WR", "TE")

# How many players per team+position are worth projecting. A fantasy manager
# starts one QB and never a team's third receiver, and a rostered backup with a
# few garbage-time games otherwise regresses to the positional baseline (~18 PPR
# for a QB) and floods the board. The prescore ranks within the group first.
_DEPTH_BY_POSITION: dict[str, int] = {"QB": 1, "RB": 3, "WR": 4, "TE": 2}

# Share of the projection budget per position. 32 near-identical QB1 lines would
# otherwise eat a "top N" list; a fantasy board wants RB/WR depth.
_BUDGET_SHARE: dict[str, float] = {"QB": 0.18, "RB": 0.33, "WR": 0.37, "TE": 0.12}

# Below this many trailing games the projection is just the positional baseline
# (rookies, deep backups). Better to omit them than show a fabricated number.
_MIN_TRAILING_GAMES = 3

_SLATE_CACHE: dict[tuple[int, int, str, int, tuple[str, ...]], FantasySlateResponse] = {}

# One slate build at a time per process. Each build is minutes of GIL-bound
# NumPy/statsmodels work; letting N requests (the startup prewarm + every GUI
# refetch/StrictMode remount) each recompute the same key in the threadpool
# thrashes all of them and blows up memory. A request that finds a build already
# running gets SlateBuilding (-> HTTP 202) instead of parking a threadpool
# thread; only the prewarm waits.
_SLATE_LOCK = threading.Lock()


class SlateBuilding(Exception):
    """Raised when a slate build is already in progress for another caller."""


def _player_history_index(weekly: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """One pass to bucket the weekly frame by player_id (the pre-score reads it
    once per candidate, and a full-frame scan per player is seconds of work)."""
    if "player_id" not in weekly.columns or not len(weekly):
        return {}
    keyed = weekly.assign(_pid=weekly["player_id"].astype(str))
    return {str(pid): grp for pid, grp in keyed.groupby("_pid", sort=False)}


def _prescore(
    hist: pd.DataFrame | None,
    baselines: dict[tuple[str, str], float],
    *,
    season: int,
    week: int,
    position: str,
    weights: dict[str, float],
) -> float:
    """Recency-weighted trailing fantasy points/game — the same shape as the real
    trailing projector, minus the Monte Carlo. Used only to rank."""
    stats = _TRAILING_STATS_BY_POSITION.get(position, ())
    if hist is None or hist.empty or not stats:
        return 0.0
    past = hist[
        (hist["season"] < season) | ((hist["season"] == season) & (hist["week"] < week))
    ].sort_values(["season", "week"]).tail(_TRAILING_WINDOW)
    n = len(past)
    if n < _MIN_TRAILING_GAMES:
        return 0.0
    recency = np.linspace(0.5, 1.0, n)
    form_weight = n / (n + _TRAILING_REGRESS_GAMES)
    points = 0.0
    for stat in stats:
        weight = weights.get(stat, 0.0)
        if weight == 0.0 or stat not in past.columns:
            continue
        recent = float(np.average(past[stat].fillna(0.0).to_numpy(dtype=float), weights=recency))
        base = float(baselines.get((position, stat), 0.0))
        points += weight * (form_weight * recent + (1.0 - form_weight) * base)
    return points


def build_fantasy_slate(
    settings: AppSettings,
    *,
    season: int,
    week: int,
    scoring_mode: ScoringMode = "full_ppr",
    limit: int = 80,
    positions: tuple[str, ...] = _SKILL_POSITIONS,
    wait: bool = False,
) -> FantasySlateResponse:
    if scoring_mode not in SCORING_PROFILES:
        raise ValueError(f"Unsupported fantasy scoring mode: {scoring_mode}")
    positions = tuple(p.upper().strip() for p in positions if p.strip())
    cache_key = (season, week, scoring_mode, limit, positions)

    cached = _SLATE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if not _SLATE_LOCK.acquire(blocking=wait):
        raise SlateBuilding
    try:
        cached = _SLATE_CACHE.get(cache_key)  # the prior holder may have built this key
        if cached is not None:
            return cached
        response = _compute_slate(
            settings,
            season=season,
            week=week,
            scoring_mode=scoring_mode,
            limit=limit,
            positions=positions,
        )
        _SLATE_CACHE[cache_key] = response
        return response
    finally:
        _SLATE_LOCK.release()


def _compute_slate(
    settings: AppSettings,
    *,
    season: int,
    week: int,
    scoring_mode: ScoringMode,
    limit: int,
    positions: tuple[str, ...],
) -> FantasySlateResponse:
    games = get_schedule(season, week)
    if not games:
        raise ValueError(f"No schedule rows for {season} week {week}")

    matchup: dict[str, tuple[str, str, str]] = {}  # team -> (opponent, game_id, kickoff)
    for game in games:
        kickoff = " ".join(x for x in (game.gameday, game.gametime) if x).strip()
        if game.home_team:
            matchup[game.home_team] = (game.away_team, game.game_id, kickoff)
        if game.away_team:
            matchup[game.away_team] = (game.home_team, game.game_id, kickoff)

    weekly = scoring_weekly(settings, season)
    baselines = _baselines_for(weekly)
    history = _player_history_index(weekly)
    weights = SCORING_PROFILES[scoring_mode]

    Candidate = tuple[float, str, str, str, str, str, str, str]
    by_group: dict[tuple[str, str], list[Candidate]] = {}
    seen: set[str] = set()
    for team in matchup:
        try:
            players, _ = get_roster(season, team=team, position=",".join(positions))
        except Exception:  # noqa: BLE001
            continue
        opponent, game_id, kickoff = matchup[team]
        for player in players:
            pid = player.player_id
            position = player.position.upper().strip()
            if not pid or pid in seen or position not in positions:
                continue
            seen.add(pid)
            score = _prescore(
                history.get(pid),
                baselines,
                season=season,
                week=week,
                position=position,
                weights=weights,
            )
            if score <= 0.0:
                continue
            by_group.setdefault((team, position), []).append(
                (score, pid, player.player_name, position, team, opponent, game_id, kickoff)
            )

    # Keep only the projectable depth at each team+position...
    depth_capped: dict[str, list[Candidate]] = {}
    for (_, position), group in by_group.items():
        group.sort(key=lambda row: row[0], reverse=True)
        depth_capped.setdefault(position, []).extend(group[: _DEPTH_BY_POSITION.get(position, 3)])

    # ...then take a per-position slice of the budget so RB/WR depth survives a
    # wall of interchangeable QB1 lines. Unused headroom (e.g. only 2 TEs on a
    # short slate) is redistributed by the final global sort + limit.
    candidates: list[Candidate] = []
    for position, group in depth_capped.items():
        group.sort(key=lambda row: row[0], reverse=True)
        take = max(4, round(limit * _BUDGET_SHARE.get(position, 0.25)) + 4)
        candidates.extend(group[:take])
    candidates.sort(key=lambda row: row[0], reverse=True)

    # `candidates` is already the position-budgeted union (~limit + slack); the
    # per-position takes above are what `limit` actually sizes.
    entries: list[FantasySlateEntry] = []
    for _, pid, name, position, team, opponent, game_id, kickoff in candidates:
        try:
            summary = build_fantasy_summary(
                settings,
                player_id=pid,
                season=season,
                week=week,
                position=position,
                recent_team=team,
                opponent_team=opponent,
                game_id=game_id,
                scoring_mode=scoring_mode,
            )
        except Exception:  # noqa: BLE001
            continue
        entries.append(
            FantasySlateEntry(
                player_id=pid,
                player_name=name,
                position=position,
                recent_team=team,
                opponent_team=opponent,
                game_id=game_id,
                kickoff=kickoff,
                projected_points=summary.projected_points,
                floor_points=summary.p10_points,
                ceiling_points=summary.p90_points,
                boom_probability=summary.boom_probability,
                bust_probability=summary.bust_probability,
            )
        )

    entries.sort(key=lambda entry: entry.projected_points, reverse=True)
    return FantasySlateResponse(
        season=season,
        week=week,
        scoring_mode=scoring_mode,
        games=len(games),
        players_considered=len(candidates),
        entries=entries,
    )


# The live slate the desktop app opens on. Bump at the season rollover (the GUI
# has the matching SEASON constant in this-week-page.tsx).
_PREWARM_SEASON = 2026
_PREWARM_WEEK = 1
_PREWARM_LIMIT = 48


def prewarm_current_slate(settings: AppSettings) -> None:
    """Best-effort: build and cache the default slate so the first GUI open is
    instant instead of a multi-minute simulation. Safe to call off-thread."""
    try:
        build_fantasy_slate(
            settings,
            season=_PREWARM_SEASON,
            week=_PREWARM_WEEK,
            scoring_mode="full_ppr",
            limit=_PREWARM_LIMIT,
            wait=True,
        )
    except Exception:  # noqa: BLE001
        pass
