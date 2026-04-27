"""Weather data loader — ERA5 archive + Open-Meteo forecast stub.

See docs/plan.md Phase G3.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

_CACHE_DIR = Path(__file__).parent.parent / "cache"
_ARCHIVE_PATH = _CACHE_DIR / "weather_archive.parquet"

_WEATHER_COLUMNS = [
    "game_id",
    "season",
    "week",
    "home_team",
    "kickoff_utc",
    "temp_f",
    "wind_mph",
    "wind_dir_deg",
    "precip_in",
    "weather_code",
    "indoor",
]

_NUMERIC_COLS = ["temp_f", "wind_mph", "wind_dir_deg", "precip_in", "weather_code"]


def _empty_archive() -> pd.DataFrame:
    """Return an empty DataFrame with the correct archive schema."""
    return pd.DataFrame(columns=_WEATHER_COLUMNS).astype(
        {
            "game_id": "object",
            "season": "Int64",
            "week": "Int64",
            "home_team": "object",
            "temp_f": "Float64",
            "wind_mph": "Float64",
            "wind_dir_deg": "Float64",
            "precip_in": "Float64",
            "weather_code": "Float64",
            "indoor": "boolean",
        }
    )


def load_archive(seasons: list[int]) -> pd.DataFrame:
    """Load ERA5 weather from cache/weather_archive.parquet, filtered by season.

    If the file doesn't exist, returns an empty DataFrame with the correct columns.
    """
    if not _ARCHIVE_PATH.exists():
        return _empty_archive()

    df = pd.read_parquet(_ARCHIVE_PATH, engine="pyarrow")
    return df[df["season"].isin(seasons)].reset_index(drop=True)


def archive_available(seasons: list[int] | None = None) -> bool:
    """Return True when the archive cache exists and has rows for the window."""
    if not _ARCHIVE_PATH.exists():
        return False
    if seasons is None:
        try:
            return not pd.read_parquet(_ARCHIVE_PATH, engine="pyarrow").empty
        except Exception:  # noqa: BLE001 - availability is a metadata hint
            return False
    try:
        return not load_archive(seasons).empty
    except Exception:  # noqa: BLE001 - callers should degrade, not crash
        return False


def load_forecast(game_id: str) -> dict | None:
    """Hit Open-Meteo Forecast API for an upcoming game.

    Gated on settings.use_live_forecast — returns None when flag is off or
    the game is not upcoming (game_id not in schedules for current/next season).
    Always returns None until use_live_forecast=True is set.
    """
    from api.settings import get_settings

    settings = get_settings()
    if not settings.use_live_forecast:
        return None

    # TODO: implement Open-Meteo Forecast API call when use_live_forecast=True
    return None
