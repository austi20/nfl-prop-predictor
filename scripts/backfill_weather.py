"""Backfill NFL game weather from Open-Meteo Archive API.

Usage:
    python -m uv run python scripts/backfill_weather.py --seasons 2018,2019
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

# Allow imports from project root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.nflverse_loader import load_schedules
from data.stadium_coords import STADIUMS, is_indoor

_LOG = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).parent.parent / "cache"
_ARCHIVE_PARQUET = _CACHE_DIR / "weather_archive.parquet"
_OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"

_OUTPUT_COLS = [
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


def _parse_seasons(raw: str) -> list[int]:
    return [int(s.strip()) for s in raw.split(",") if s.strip()]


def _load_existing() -> set[str]:
    """Return set of game_ids already in the parquet cache."""
    if not _ARCHIVE_PARQUET.exists():
        return set()
    df = pd.read_parquet(_ARCHIVE_PARQUET, columns=["game_id"])
    return set(df["game_id"].tolist())


def _kickoff_utc(gameday: str, gametime: str, tz_name: str) -> datetime:
    """Convert gameday (YYYY-MM-DD) + gametime (HH:MM local) to UTC datetime."""
    local_tz = ZoneInfo(tz_name)
    hour, minute = int(gametime.split(":")[0]), int(gametime.split(":")[1])
    naive = datetime(
        int(gameday[:4]),
        int(gameday[5:7]),
        int(gameday[8:10]),
        hour,
        minute,
    )
    local_dt = naive.replace(tzinfo=local_tz)
    return local_dt.astimezone(timezone.utc)


def _fetch_weather(lat: float, lon: float, date_str: str) -> dict:
    """Call Open-Meteo Archive for one day; return raw JSON. Retries on 5xx."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": date_str,
        "end_date": date_str,
        "hourly": "temperature_2m,precipitation,wind_speed_10m,wind_direction_10m,weather_code",
        "timezone": "UTC",
    }
    backoff = 1
    for attempt in range(4):
        resp = requests.get(_OPEN_METEO_URL, params=params, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (429, 403):
            raise RuntimeError(
                f"HTTP {resp.status_code} from Open-Meteo - stopping (rate limit / forbidden)"
            )
        if 500 <= resp.status_code < 600 and attempt < 3:
            _LOG.warning("HTTP %d on attempt %d, retrying in %ds", resp.status_code, attempt + 1, backoff)
            time.sleep(backoff)
            backoff *= 2
            continue
        resp.raise_for_status()
    resp.raise_for_status()  # should not reach here
    return {}  # unreachable, satisfies type checker


def _extract_hour(data: dict, kickoff: datetime) -> dict:
    """Pick the hourly slot closest to kickoff UTC and apply unit conversions."""
    times = data["hourly"]["time"]  # list of "YYYY-MM-DDTHH:00" strings
    target_hour = kickoff.replace(minute=0, second=0, microsecond=0)

    best_idx = 0
    best_delta = float("inf")
    for i, t_str in enumerate(times):
        slot = datetime.fromisoformat(t_str).replace(tzinfo=timezone.utc)
        delta = abs((slot - target_hour).total_seconds())
        if delta < best_delta:
            best_delta = delta
            best_idx = i

    temp_c = data["hourly"]["temperature_2m"][best_idx]
    wind_kmh = data["hourly"]["wind_speed_10m"][best_idx]
    precip_mm = data["hourly"]["precipitation"][best_idx]
    wind_dir = data["hourly"]["wind_direction_10m"][best_idx]
    w_code = data["hourly"]["weather_code"][best_idx]

    temp_f = temp_c * 9 / 5 + 32 if temp_c is not None else None
    wind_mph = wind_kmh * 0.621371 if wind_kmh is not None else None
    precip_in = precip_mm / 25.4 if precip_mm is not None else None

    return {
        "temp_f": temp_f,
        "wind_mph": wind_mph,
        "wind_dir_deg": wind_dir,
        "precip_in": precip_in,
        "weather_code": float(w_code) if w_code is not None else None,
    }


def process_games(
    games: pd.DataFrame,
    existing_ids: set[str],
    *,
    sleep_secs: float = 0.1,
) -> list[dict]:
    """Core loop: process game rows, return list of output dicts.

    Separates fetch logic from I/O so tests can call directly.
    """
    rows: list[dict] = []
    processed = 0

    for _, game in games.iterrows():
        game_id = str(game["game_id"])

        if game_id in existing_ids:
            _LOG.debug("Skipping already-cached game %s", game_id)
            continue

        home_team = str(game["home_team"])
        gameday = game.get("gameday")
        gametime = game.get("gametime")

        # Skip bye weeks / TBD games.
        if pd.isna(gameday) or pd.isna(gametime) or gameday == "" or gametime == "":
            _LOG.debug("Skipping game %s: missing gameday/gametime", game_id)
            continue

        # Resolve stadium; skip unknown teams rather than crash.
        if home_team not in STADIUMS:
            _LOG.warning("Unknown home_team %r in game %s - skipping", home_team, game_id)
            continue

        base_row: dict = {
            "game_id": game_id,
            "season": int(game["season"]) if not pd.isna(game.get("season")) else None,
            "week": int(game["week"]) if not pd.isna(game.get("week")) else None,
            "home_team": home_team,
        }

        if is_indoor(home_team):
            rows.append({
                **base_row,
                "kickoff_utc": pd.NaT,
                "temp_f": pd.NA,
                "wind_mph": pd.NA,
                "wind_dir_deg": pd.NA,
                "precip_in": pd.NA,
                "weather_code": pd.NA,
                "indoor": True,
            })
            processed += 1
            continue

        # Outdoor: resolve kickoff UTC then fetch.
        stadium = STADIUMS[home_team]
        try:
            ko_utc = _kickoff_utc(str(gameday), str(gametime), stadium.tz)
        except Exception as exc:
            _LOG.warning("Cannot parse kickoff for %s: %s - skipping", game_id, exc)
            continue

        date_str = ko_utc.strftime("%Y-%m-%d")
        try:
            weather_json = _fetch_weather(stadium.lat, stadium.lon, date_str)
        except RuntimeError as exc:
            # 429/403 - stop cleanly, log progress so far.
            _LOG.error(
                "Stopping early at game %s after processing %d rows: %s",
                game_id,
                processed,
                exc,
            )
            break

        weather = _extract_hour(weather_json, ko_utc)
        rows.append({
            **base_row,
            "kickoff_utc": pd.Timestamp(ko_utc),
            **weather,
            "indoor": False,
        })
        processed += 1
        time.sleep(sleep_secs)

    return rows


def _rows_to_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=_OUTPUT_COLS)
    df = pd.DataFrame(rows, columns=_OUTPUT_COLS)
    # Ensure correct dtypes.
    df["kickoff_utc"] = pd.to_datetime(df["kickoff_utc"], utc=True, errors="coerce")
    df["indoor"] = df["indoor"].astype(bool)
    for col in ("temp_f", "wind_mph", "wind_dir_deg", "precip_in", "weather_code"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def write_results(new_rows: list[dict]) -> pd.DataFrame:
    """Merge new rows with existing cache and write parquet."""
    new_df = _rows_to_df(new_rows)

    if _ARCHIVE_PARQUET.exists():
        existing_df = pd.read_parquet(_ARCHIVE_PARQUET)
        combined = pd.concat([existing_df, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["game_id"], keep="last")
    else:
        combined = new_df

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(_ARCHIVE_PARQUET, engine="pyarrow", index=False)
    _LOG.info("Wrote %d total rows to %s", len(combined), _ARCHIVE_PARQUET)
    return combined


def run(seasons: list[int]) -> None:
    _LOG.info("Loading schedules for seasons: %s", seasons)
    schedules = load_schedules(seasons)
    existing_ids = _load_existing()
    _LOG.info("Schedules: %d rows, %d already cached", len(schedules), len(existing_ids))

    new_rows = process_games(schedules, existing_ids)
    _LOG.info("Fetched %d new rows", len(new_rows))

    if new_rows:
        write_results(new_rows)
    else:
        _LOG.info("Nothing new to write.")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(description="Backfill NFL game weather from Open-Meteo.")
    parser.add_argument(
        "--seasons",
        default="2018,2019,2020,2021,2022,2023,2024,2025",
        help="Comma-separated list of seasons to backfill (default: 2018-2025)",
    )
    args = parser.parse_args()
    seasons = _parse_seasons(args.seasons)
    run(seasons)


if __name__ == "__main__":
    main()
