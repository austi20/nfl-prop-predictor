"""Week-level fantasy board: project every rostered skill player for a slate.

`build_fantasy_summary` is per-player (~0.8s: model predict + 5000-sim Monte
Carlo + four context passes), so a whole week serially is a minute-plus. We
keep it fast by:
  1. enumerating only skill players on the rosters of teams that play the week;
  2. ranking them with a cheap trailing fantasy-points/game estimate (no MC),
     dropping thin-sample players and capping per team+position;
  3. projecting the survivors across a process pool (see _run_projection_tasks) —
     ~2.4x over serial, output byte-identical (each player's MC seed is fixed);
  4. caching the response per (season, week, scoring, limit), behind a lock so
     only one build runs at a time.

The sidecar prewarms the current week's board at startup so the first GUI open
is a cache hit; a mid-session week/scoring switch is a ~30s build with a polling
"building" state in the UI.
"""
from __future__ import annotations

import logging
import multiprocessing
import os
import threading
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from api.schemas import FantasySlateEntry, FantasySlateResponse
from api.services.evaluation_service import scoring_weekly
from api.services.fantasy_service import (
    _TRAILING_REGRESS_GAMES,
    _TRAILING_STATS_BY_POSITION,
    _TRAILING_WINDOW,
    _baseline,
    _baselines_for,
    build_fantasy_summary,
)
from api.services.nflverse_service import current_week, get_roster, get_schedule
from api.settings import AppSettings
from data import injuries
from data.depth_chart import bucket, effective_rank
from data.draft import capital_multiplier as _draft_capital_multiplier
from data.draft import draft_capital
from eval.fantasy_points import SCORING_PROFILES, ScoringMode
from eval.fantasy_tiers import TIER_KEYS, TIER_LABELS, assign_tiers, starter_demand

_log = logging.getLogger(__name__)

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

_SLATE_CACHE: dict[tuple[int, int, str, int, tuple[str, ...]], tuple[float, FantasySlateResponse]] = {}
# Injury designations land through the day; a board older than this rebuilds.
_SLATE_MAX_AGE_SECONDS = 30 * 60


def _cached_slate(key: tuple) -> FantasySlateResponse | None:
    entry = _SLATE_CACHE.get(key)
    if entry is None or time.time() - entry[0] > _SLATE_MAX_AGE_SECONDS:
        return None
    return entry[1]

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
    baselines: dict[tuple[str, int | None, str], float],
    *,
    season: int,
    week: int,
    position: str,
    weights: dict[str, float],
    depth_rank: int | None = None,
    capital_multiplier: float = 1.0,
) -> float:
    """Recency-weighted trailing fantasy points/game — the same shape as the real
    trailing projector, minus the Monte Carlo. Used only to rank."""
    stats = _TRAILING_STATS_BY_POSITION.get(position, ())
    if not stats:
        return 0.0
    rank_bucket = bucket(depth_rank, position)

    def _slot_score() -> float:
        """What the depth slot alone implies, scaled by draft capital."""
        if rank_bucket is None:
            return 0.0
        return capital_multiplier * sum(
            weight * _baseline(baselines, position, rank_bucket, stat)
            for stat, weight in weights.items()
            if weight and stat in stats
        )

    if hist is None or hist.empty:
        return _slot_score()
    past = hist[
        (hist["season"] < season) | ((hist["season"] == season) & (hist["week"] < week))
    ].sort_values(["season", "week"]).tail(_TRAILING_WINDOW)
    n = len(past)
    if n < _MIN_TRAILING_GAMES:
        # Too little history to average. A player listed high on the depth chart
        # is still a real candidate — rank him off his slot so he survives the
        # team cap instead of being cut. No slot listed, no score.
        return _slot_score()
    recency = np.linspace(0.5, 1.0, n)
    form_weight = n / (n + _TRAILING_REGRESS_GAMES)
    points = 0.0
    for stat in stats:
        weight = weights.get(stat, 0.0)
        if weight == 0.0 or stat not in past.columns:
            continue
        recent = float(np.average(past[stat].fillna(0.0).to_numpy(dtype=float), weights=recency))
        base = _baseline(baselines, position, rank_bucket, stat)
        points += weight * (form_weight * recent + (1.0 - form_weight) * base)
    return points


# ---------------------------------------------------------------------------
# Parallel projection
#
# Each player's `build_fantasy_summary` is ~0.8s of GIL-bound NumPy/statsmodels
# work; ~65 of them serially is a minute. Fan out across processes (spawn), each
# lazily fitting its own model bundle once via the existing lru_cache. BLAS is
# pinned to one thread per worker in api/sidecar.py so the pool does not
# oversubscribe. Any pool failure (pickle, frozen-exe spawn quirk) falls back to
# the serial loop — slower, never broken.
# ---------------------------------------------------------------------------

# (settings, season, week, scoring_mode, pid, name, position, team, opp, gid, kickoff)
_ProjTask = tuple


def _worker_count(settings: AppSettings, n_tasks: int) -> int:
    configured = int(getattr(settings, "fantasy_slate_workers", 0) or 0)
    if configured < 0:
        configured = 0
    auto = max(1, round(0.7 * (os.cpu_count() or 4)))
    workers = configured or auto
    return max(1, min(workers, n_tasks))


def _project_player(task: _ProjTask) -> dict | None:
    (settings, season, week, scoring_mode, pid, name, position, team, opp, gid, kickoff) = task
    try:
        summary = build_fantasy_summary(
            settings,
            player_id=pid,
            season=season,
            week=week,
            position=position,
            recent_team=team,
            opponent_team=opp,
            game_id=gid,
            scoring_mode=scoring_mode,
        )
    except Exception:  # noqa: BLE001
        return None
    status, _note = injuries.player_statuses(season, week).get(pid, ("not_reported", ""))
    return {
        "player_id": pid,
        "player_name": name,
        "position": position,
        "recent_team": team,
        "opponent_team": opp,
        "game_id": gid,
        "kickoff": kickoff,
        "projected_points": summary.projected_points,
        "floor_points": summary.p10_points,
        "ceiling_points": summary.p90_points,
        "boom_probability": summary.boom_probability,
        "bust_probability": summary.bust_probability,
        "injury_status": "" if status == "not_reported" else injuries.label(status),
    }


def _run_projection_tasks(settings: AppSettings, tasks: list[_ProjTask]) -> list[dict]:
    if not tasks:
        return []
    workers = _worker_count(settings, len(tasks))
    if workers <= 1 or len(tasks) <= 4:
        return [r for r in map(_project_player, tasks) if r is not None]
    try:
        ctx = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as pool:
            results = list(pool.map(_project_player, tasks, chunksize=1))
    except Exception as exc:  # noqa: BLE001
        _log.warning("fantasy slate: process pool unavailable (%s); running serially", exc)
        results = list(map(_project_player, tasks))
    return [r for r in results if r is not None]


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

    cached = _cached_slate(cache_key)
    if cached is not None:
        return cached
    stale = _SLATE_CACHE.get(cache_key)
    if stale is not None and not wait:
        # Serve the old board and rebuild behind it, so an expiry never blanks it.
        if _SLATE_LOCK.acquire(blocking=False):
            threading.Thread(
                target=_rebuild_slate,
                args=(settings, cache_key),
                daemon=True,
            ).start()
        return stale[1]

    if not _SLATE_LOCK.acquire(blocking=wait):
        raise SlateBuilding
    try:
        cached = _cached_slate(cache_key)  # the prior holder may have built this key
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
        _SLATE_CACHE[cache_key] = (time.time(), response)
        return response
    finally:
        _SLATE_LOCK.release()



def _rebuild_slate(settings: AppSettings, cache_key: tuple) -> None:
    """Background refresh. The caller already holds _SLATE_LOCK."""
    season, week, scoring_mode, limit, positions = cache_key
    try:
        response = _compute_slate(
            settings,
            season=season,
            week=week,
            scoring_mode=scoring_mode,
            limit=limit,
            positions=positions,
        )
        _SLATE_CACHE[cache_key] = (time.time(), response)
    except Exception:  # noqa: BLE001 - the stale board keeps serving
        _log.warning("fantasy slate background rebuild failed", exc_info=True)
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
    rank_seasons = (
        tuple(sorted({int(s) for s in weekly["season"].unique()} | {int(season)}))
        if "season" in weekly.columns and len(weekly)
        else (int(season),)
    )

    Candidate = tuple[float, str, str, str, str, str, str, str]
    by_group: dict[tuple[str, str], list[Candidate]] = {}
    # Out / doubtful players: shown flagged, but never hold a starter's slot.
    sidelined: list[tuple[float, Candidate]] = []
    statuses = injuries.player_statuses(season, week)
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
            try:
                rank = effective_rank(pid, season, week, rank_seasons)
                capital = _draft_capital_multiplier(draft_capital(pid, rank_seasons))
            except Exception:  # noqa: BLE001 - depth/draft data is an enhancement
                rank, capital = None, 1.0
            score = _prescore(
                history.get(pid),
                baselines,
                season=season,
                week=week,
                position=position,
                weights=weights,
                depth_rank=rank,
                capital_multiplier=capital,
            )
            if score <= 0.0:
                continue
            status = statuses.get(pid, ("not_reported", ""))[0]
            row = (
                score * injuries.output_multiplier(status),
                pid, player.player_name, position, team, opponent, game_id, kickoff,
            )
            if status in ("out", "doubtful"):
                sidelined.append((score, row))
                continue
            by_group.setdefault((team, position), []).append(row)

    # Keep only the projectable depth at each team+position...
    depth_capped: dict[str, list[Candidate]] = {}
    for (_, position), group in by_group.items():
        group.sort(key=lambda row: row[0], reverse=True)
        depth_capped.setdefault(position, []).extend(group[: _DEPTH_BY_POSITION.get(position, 3)])

    # A sidelined player is listed when he would have made his team's cap
    # healthy, so the board shows Williams as out rather than just missing.
    for healthy_score, row in sidelined:
        group = by_group.get((row[4], row[3]), [])
        cap = _DEPTH_BY_POSITION.get(row[3], 3)
        if len(group) < cap or healthy_score >= group[min(cap, len(group)) - 1][0]:
            depth_capped.setdefault(row[3], []).append(row)

    # ...then take a per-position slice of the budget so RB/WR depth survives a
    # wall of interchangeable QB1 lines. Unused headroom (e.g. only 2 TEs on a
    # short slate) is redistributed by the final global sort + limit.
    candidates: list[Candidate] = []
    for position, group in depth_capped.items():
        group.sort(key=lambda row: row[0], reverse=True)
        if limit <= 0:
            candidates.extend(group)  # whole board: every projectable starter
            continue
        take = max(4, round(limit * _BUDGET_SHARE.get(position, 0.25)) + 4)
        candidates.extend(group[:take])
    candidates.sort(key=lambda row: row[0], reverse=True)

    # `candidates` is already the position-budgeted union (~limit + slack); the
    # per-position takes above are what `limit` actually sizes. Project them in
    # parallel — this is the whole cost of a cold slate.
    tasks: list[_ProjTask] = [
        (settings, season, week, scoring_mode, pid, name, position, team, opponent, game_id, kickoff)
        for _, pid, name, position, team, opponent, game_id, kickoff in candidates
    ]
    entries = [FantasySlateEntry(**row) for row in _run_projection_tasks(settings, tasks)]
    entries.sort(key=lambda entry: entry.projected_points, reverse=True)
    _apply_tiers(entries)
    return FantasySlateResponse(
        season=season,
        week=week,
        scoring_mode=scoring_mode,
        games=len(games),
        players_considered=len(candidates),
        entries=entries,
        tier_order=list(TIER_KEYS),
        tier_labels=dict(TIER_LABELS),
    )


_FLEX_POSITIONS = ("RB", "WR", "TE")


def _apply_tiers(entries: list[FantasySlateEntry]) -> None:
    """Rank and tier the board in place: once cumulatively, once per position,
    and once over the RB/WR/TE flex pool. ``entries`` must already be sorted
    best-first, which makes every sub-list sorted too."""
    if not entries:
        return

    def tier_list(rows: list[FantasySlateEntry], list_key: str, field: str) -> None:
        tiers = assign_tiers([row.projected_points for row in rows], starter_demand(list_key))
        for i, (row, tier) in enumerate(zip(rows, tiers), start=1):
            setattr(row, f"{field}_rank", i)
            setattr(row, f"{field}_tier", tier)

    tier_list(entries, "ALL", "overall")

    by_position: dict[str, list[FantasySlateEntry]] = {}
    for entry in entries:
        by_position.setdefault(entry.position, []).append(entry)
    for position, rows in by_position.items():
        tier_list(rows, position, "position")

    tier_list([e for e in entries if e.position in _FLEX_POSITIONS], "FLEX", "flex")


# The live slate the desktop app opens on. Bump at the season rollover (the GUI
# has the matching SEASON constant in this-week-page.tsx). The week follows the
# schedule, so the prewarmed key stays the one the GUI actually asks for.
_PREWARM_SEASON = 2026
_PREWARM_LIMIT = 0  # whole board - the GUI asks for the same key


def prewarm_current_slate(settings: AppSettings) -> None:
    """Best-effort: build and cache the default slate so the first GUI open is
    instant instead of a multi-minute simulation. Safe to call off-thread."""
    try:
        build_fantasy_slate(
            settings,
            season=_PREWARM_SEASON,
            week=current_week(_PREWARM_SEASON),
            scoring_mode="full_ppr",
            limit=_PREWARM_LIMIT,
            wait=True,
        )
    except Exception:  # noqa: BLE001
        pass
