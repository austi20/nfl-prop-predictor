# nflverse data ingestion + parquet cache
# See docs/plan.md Step 1

from __future__ import annotations

import time
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
    "NYG",  # MetLife Stadium (open, but included as shared dome-adjacent)
    "NYJ",  # MetLife Stadium (open, but included as shared dome-adjacent)
})


def is_dome(team_abbr: str) -> bool:
    return team_abbr in DOME_TEAMS


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_CACHE_DIR = Path(__file__).parent.parent / "cache"
_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60  # 24 hours


def _year_tag(years: list[int]) -> str:
    return f"{min(years)}_{max(years)}"


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


# ---------------------------------------------------------------------------
# Public loaders
# ---------------------------------------------------------------------------


def load_weekly(years: list[int] = TRAIN_YEARS, force_refresh: bool = False) -> pd.DataFrame:
    path = _cache_path("weekly", years)
    return _load_or_fetch(path, lambda: nfl.import_weekly_data(years), force_refresh)


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
