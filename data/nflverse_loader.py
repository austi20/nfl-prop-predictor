# nflverse data ingestion + parquet cache
# See docs/plan.md Step 1

from __future__ import annotations

import time
from urllib.error import HTTPError
from pathlib import Path
from typing import Literal

import nfl_data_py as nfl
import pandas as pd

# ---------------------------------------------------------------------------
# Year constants
# ---------------------------------------------------------------------------

TRAIN_YEARS: list[int] = list(range(2015, 2025))
HOLDOUT_YEARS: list[int] = [2025]
ALL_YEARS: list[int] = list(range(1999, 2026))

# ---------------------------------------------------------------------------
# Dome / retractable-roof teams (as of 2025 season)
# ---------------------------------------------------------------------------

DOME_TEAMS: frozenset[str] = frozenset({
    "ARI",  # State Farm Stadium (retractable)
    "ATL",  # Mercedes-Benz Stadium (retractable)
    "DAL",  # AT&T Stadium (retractable)
    "DET",  # Ford Field (fixed dome)
    "HOU",  # NRG Stadium (retractable)
    "IND",  # Lucas Oil Stadium (retractable)
    "LV",   # Allegiant Stadium (fixed dome)
    "MIN",  # U.S. Bank Stadium (fixed dome)
    "NO",   # Caesars Superdome (fixed dome)
    # NYG and NYJ play at MetLife Stadium, which is open-air - not a dome
})


def is_dome(team_abbr: str) -> bool:
    return team_abbr in DOME_TEAMS


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_CACHE_DIR = Path(__file__).parent.parent / "cache"
_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60  # 24 hours
_NFLVERSE_STATS_PLAYER_RELEASE = (
    "https://github.com/nflverse/nflverse-data/releases/download/stats_player/"
    "stats_player_week_{year}.parquet"
)


def _year_tag(years: list[int]) -> str:
    return "-".join(str(y) for y in sorted(set(years)))


def _cache_path(data_type: str, years: list[int] | None = None) -> Path:
    if years is None:
        filename = f"{data_type}.parquet"
    else:
        filename = f"{data_type}_{_year_tag(years)}.parquet"
    return _CACHE_DIR / filename


def _is_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < _CACHE_MAX_AGE_SECONDS


def _load_or_fetch(
    cache_file: Path,
    fetch_fn,
    force_refresh: bool,
) -> pd.DataFrame:
    if not force_refresh and _is_fresh(cache_file):
        return pd.read_parquet(cache_file, engine="pyarrow")
    df = fetch_fn()
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache_file, engine="pyarrow", index=False)
    return df


def _fetch_weekly_direct(years: list[int]) -> pd.DataFrame:
    frames = [
        pd.read_parquet(
            _NFLVERSE_STATS_PLAYER_RELEASE.format(year=year),
            engine="pyarrow",
        )
        for year in years
    ]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _normalize_weekly_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map: dict[str, str] = {}
    if "passing_interceptions" in df.columns and "interceptions" not in df.columns:
        rename_map["passing_interceptions"] = "interceptions"
    if "sacks_suffered" in df.columns and "sacks" not in df.columns:
        rename_map["sacks_suffered"] = "sacks"
    if "sack_yards_lost" in df.columns and "sack_yards" not in df.columns:
        rename_map["sack_yards_lost"] = "sack_yards"
    if "team" in df.columns and "recent_team" not in df.columns:
        rename_map["team"] = "recent_team"
    return df.rename(columns=rename_map) if rename_map else df


# ---------------------------------------------------------------------------
# Public loaders
# ---------------------------------------------------------------------------


def load_weekly(years: list[int] = TRAIN_YEARS, force_refresh: bool = False) -> pd.DataFrame:
    path = _cache_path("weekly", years)

    def _fetch() -> pd.DataFrame:
        try:
            return nfl.import_weekly_data(years)
        except Exception as exc:
            if isinstance(exc, HTTPError) and exc.code != 404:
                raise
            return _fetch_weekly_direct(years)

    df = _load_or_fetch(path, _fetch, force_refresh)
    normalized = _normalize_weekly_columns(df)
    if set(normalized.columns) != set(df.columns):
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        normalized.to_parquet(path, engine="pyarrow", index=False)
    return normalized


def load_pbp(years: list[int] = TRAIN_YEARS, force_refresh: bool = False) -> pd.DataFrame:
    path = _cache_path("pbp", years)
    return _load_or_fetch(path, lambda: nfl.import_pbp_data(years), force_refresh)


def load_seasonal(years: list[int] = TRAIN_YEARS, force_refresh: bool = False) -> pd.DataFrame:
    path = _cache_path("seasonal", years)
    return _load_or_fetch(path, lambda: nfl.import_seasonal_data(years), force_refresh)


def load_rosters(years: list[int] = TRAIN_YEARS, force_refresh: bool = False) -> pd.DataFrame:
    path = _cache_path("rosters", years)
    return _load_or_fetch(path, lambda: nfl.import_weekly_rosters(years), force_refresh)


def load_schedules(years: list[int] = TRAIN_YEARS, force_refresh: bool = False) -> pd.DataFrame:
    path = _cache_path("schedules", years)
    return _load_or_fetch(path, lambda: nfl.import_schedules(years), force_refresh)


def load_team_desc(force_refresh: bool = False) -> pd.DataFrame:
    path = _cache_path("team_desc")
    return _load_or_fetch(path, lambda: nfl.import_team_desc(), force_refresh)


def load_ngs(
    stat_type: Literal["passing", "rushing", "receiving"] = "passing",
    years: list[int] = TRAIN_YEARS,
    force_refresh: bool = False,
) -> pd.DataFrame:
    path = _cache_path(f"ngs_{stat_type}", years)
    return _load_or_fetch(path, lambda: nfl.import_ngs_data(stat_type, years), force_refresh)


def load_injuries(years: list[int] = TRAIN_YEARS, force_refresh: bool = False) -> pd.DataFrame:
    path = _cache_path("injuries", years)
    return _load_or_fetch(path, lambda: nfl.import_injuries(years), force_refresh)


def load_snap_counts(years: list[int] = TRAIN_YEARS, force_refresh: bool = False) -> pd.DataFrame:
    path = _cache_path("snap_counts", years)
    return _load_or_fetch(path, lambda: nfl.import_snap_counts(years), force_refresh)


def load_qbr(years: list[int] = TRAIN_YEARS, force_refresh: bool = False) -> pd.DataFrame:
    path = _cache_path("qbr", years)
    return _load_or_fetch(path, lambda: nfl.import_qbr(years), force_refresh)


def load_weekly_with_weather(
    years: list[int] = TRAIN_YEARS,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Weekly player stats left-joined with weather archive by game_id.

    Non-outdoor games have indoor=True and null numeric weather columns.
    Models' existing fillna(0.0) in _build_features handles the nulls.
    """
    # Deferred import to avoid circular imports at module level.
    from data.weather import load_archive

    stats = load_weekly(years, force_refresh).copy()
    weather = load_archive(years)
    weather_cols = ["temp_f", "wind_mph", "wind_dir_deg", "precip_in", "weather_code", "indoor"]

    if "game_id" not in stats.columns:
        for col in weather_cols:
            if col not in stats.columns:
                stats[col] = pd.NA
        stats["indoor"] = stats["indoor"].fillna(True).astype("boolean")
        return stats

    if weather.empty:
        for col in weather_cols:
            stats[col] = pd.NA
        stats["indoor"] = True
        return stats

    weather_slim = weather[["game_id", *weather_cols]]
    merged = stats.merge(weather_slim, on="game_id", how="left")
    merged["indoor"] = merged["indoor"].fillna(True)
    return merged
