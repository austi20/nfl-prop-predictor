"""Weather data loader — ERA5 archive + Open-Meteo forecast stub.

See docs/plan.md Phase G3.
"""

from __future__ import annotations

from functools import lru_cache
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


_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_FORECAST_HOURLY = "temperature_2m,precipitation,wind_speed_10m,wind_direction_10m,weather_code"


def _forecast_kickoff_utc(gameday: str, gametime: str):
    """nflverse `gametime` is the broadcast time (US/Eastern). Return tz-aware UTC."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    hh, mm = (gametime or "13:00").split(":")[:2]
    local = datetime.fromisoformat(gameday).replace(
        hour=int(hh), minute=int(mm), tzinfo=ZoneInfo("America/New_York")
    )
    return local.astimezone(timezone.utc)


@lru_cache(maxsize=512)
def load_forecast(game_id: str) -> dict | None:
    """Open-Meteo forecast for an upcoming game, keyed by `game_id`.

    Returns {temp_f, wind_mph, wind_dir_deg, precip_in, weather_code, indoor}
    for an outdoor venue; {indoor: True, ...} for a dome/retractable; None when
    the game is unknown, out of the forecast horizon (~16 days), or the call
    fails. Free, no API key. Gated on ``settings.use_live_forecast``.
    """
    from datetime import datetime, timezone

    from api.settings import get_settings

    if not get_settings().use_live_forecast:
        return None

    try:  # everything here degrades to None on failure
        import requests

        from data.nflverse_loader import load_schedules
        from data.stadium_coords import STADIUMS, is_indoor

        parts = game_id.split("_")
        if len(parts) < 2 or not parts[0].isdigit():
            return None
        season = int(parts[0])
        sched = load_schedules([season])
        row = sched[sched["game_id"] == game_id]
        if row.empty:
            return None
        row = row.iloc[0]
        home = str(row.get("home_team", "")).upper()
        roof = str(row.get("roof", "")).strip().lower()

        if roof in {"dome", "closed"} or (home in STADIUMS and is_indoor(home)):
            return {
                "temp_f": 70.0,
                "wind_mph": 0.0,
                "wind_dir_deg": None,
                "precip_in": 0.0,
                "weather_code": 0.0,
                "indoor": True,
            }
        stadium = STADIUMS.get(home)
        if stadium is None:
            return None

        kickoff = _forecast_kickoff_utc(str(row.get("gameday", "")), str(row.get("gametime", "")))
        horizon_days = (kickoff - datetime.now(timezone.utc)).total_seconds() / 86400.0
        if horizon_days < -1 or horizon_days > 15:
            return None  # archive covers the past; forecast horizon is ~16 days

        resp = requests.get(
            _FORECAST_URL,
            params={
                "latitude": stadium.lat,
                "longitude": stadium.lon,
                "hourly": _FORECAST_HOURLY,
                "timezone": "UTC",
                "start_date": kickoff.date().isoformat(),
                "end_date": kickoff.date().isoformat(),
                "wind_speed_unit": "mph",
                "temperature_unit": "fahrenheit",
                "precipitation_unit": "inch",
            },
            timeout=15,
        )
        resp.raise_for_status()
        hourly = resp.json().get("hourly", {})
        times = hourly.get("time") or []
        if not times:
            return None
        target = kickoff.replace(minute=0, second=0, microsecond=0)
        idx = min(
            range(len(times)),
            key=lambda i: abs(
                (datetime.fromisoformat(times[i]).replace(tzinfo=timezone.utc) - target).total_seconds()
            ),
        )

        def _at(key: str) -> float | None:
            seq = hourly.get(key) or []
            return float(seq[idx]) if idx < len(seq) and seq[idx] is not None else None

        return {
            "temp_f": _at("temperature_2m"),
            "wind_mph": _at("wind_speed_10m"),
            "wind_dir_deg": _at("wind_direction_10m"),
            "precip_in": _at("precipitation"),
            "weather_code": _at("weather_code"),
            "indoor": False,
        }
    except Exception:  # noqa: BLE001 - callers degrade to neutral weather
        return None
