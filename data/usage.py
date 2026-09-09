"""Player usage trends — snap share and air-yards share — from nflverse.

The trailing-form fantasy projector averages a player's last 8 games. That lags
a role change: a rookie who took over the backfield in Week 6, or a receiver
who lost targets after a trade, still carries five weeks of the old role in the
average. These frames expose recent snap % and intended-air-yards share so a
context factor can nudge the projection toward the *current* role.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from data.nflverse_loader import load_ids, load_ngs, load_snap_counts

_OFFENSE_SNAP_POSITIONS = {"QB", "RB", "FB", "WR", "TE"}
_RECENT_GAMES = 3
_BASE_GAMES = 5  # games 4..8 back form the comparison baseline


@lru_cache(maxsize=1)
def _pfr_to_gsis() -> dict[str, str]:
    ids = load_ids()
    if "pfr_id" not in ids.columns or "gsis_id" not in ids.columns:
        return {}
    pairs = ids[["pfr_id", "gsis_id"]].dropna()
    return {str(r.pfr_id): str(r.gsis_id) for r in pairs.itertuples(index=False)}


@lru_cache(maxsize=8)
def snap_share_frame(seasons: tuple[int, ...]) -> pd.DataFrame:
    """(gsis_id, season, week, snap_pct) for offensive players, 0..1."""
    if not seasons:
        return pd.DataFrame(columns=["gsis_id", "season", "week", "snap_pct"])
    snaps = load_snap_counts(list(seasons))
    if snaps.empty:
        return pd.DataFrame(columns=["gsis_id", "season", "week", "snap_pct"])
    snaps = snaps[snaps["position"].astype(str).str.upper().isin(_OFFENSE_SNAP_POSITIONS)].copy()
    mapping = _pfr_to_gsis()
    snaps["gsis_id"] = snaps["pfr_player_id"].astype(str).map(mapping)
    snaps = snaps.dropna(subset=["gsis_id"])
    out = snaps[["gsis_id", "season", "week"]].copy()
    out["snap_pct"] = pd.to_numeric(snaps["offense_pct"], errors="coerce")
    return out.dropna(subset=["snap_pct"]).reset_index(drop=True)


@lru_cache(maxsize=8)
def air_yards_share_frame(seasons: tuple[int, ...]) -> pd.DataFrame:
    """(gsis_id, season, week, ay_share) — intended air-yards share, 0..1."""
    empty = pd.DataFrame(columns=["gsis_id", "season", "week", "ay_share"])
    if not seasons:
        return empty
    try:
        ngs = load_ngs("receiving", list(seasons))
    except Exception:  # noqa: BLE001
        return empty
    if ngs.empty or "player_gsis_id" not in ngs.columns:
        return empty
    ngs = ngs[pd.to_numeric(ngs["week"], errors="coerce").fillna(0) > 0].copy()
    out = pd.DataFrame(
        {
            "gsis_id": ngs["player_gsis_id"].astype(str),
            "season": pd.to_numeric(ngs["season"], errors="coerce"),
            "week": pd.to_numeric(ngs["week"], errors="coerce"),
            "ay_share": pd.to_numeric(
                ngs.get("percent_share_of_intended_air_yards"), errors="coerce"
            ) / 100.0,
        }
    )
    return out.dropna().reset_index(drop=True)


def _recent_vs_base(series_frame: pd.DataFrame, col: str, season: int, week: int) -> tuple[float, float] | None:
    before = series_frame[
        (series_frame["season"] < season)
        | ((series_frame["season"] == season) & (series_frame["week"] < week))
    ].sort_values(["season", "week"])
    if len(before) < _RECENT_GAMES + 2:
        return None
    vals = before[col].to_numpy(dtype=float)
    recent = float(np.mean(vals[-_RECENT_GAMES:]))
    base_slice = vals[-(_RECENT_GAMES + _BASE_GAMES):-_RECENT_GAMES]
    if len(base_slice) < 2:
        return None
    return recent, float(np.mean(base_slice))


@lru_cache(maxsize=4096)
def usage_trend(gsis_id: str, season: int, week: int, seasons: tuple[int, ...]) -> dict | None:
    """Recent (last 3) vs baseline (games 4-8 back) snap % and air-yards share
    for a player before (season, week). None when there is not enough history."""
    if not gsis_id:
        return None
    snaps = snap_share_frame(seasons)
    ay = air_yards_share_frame(seasons)
    p_snap = snaps[snaps["gsis_id"] == gsis_id]
    p_ay = ay[ay["gsis_id"] == gsis_id]

    result: dict[str, float] = {}
    snap_rb = _recent_vs_base(p_snap, "snap_pct", season, week) if not p_snap.empty else None
    if snap_rb:
        result["snap_recent"], result["snap_base"] = snap_rb
    ay_rb = _recent_vs_base(p_ay, "ay_share", season, week) if not p_ay.empty else None
    if ay_rb:
        result["ay_recent"], result["ay_base"] = ay_rb
    return result or None
