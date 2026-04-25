"""Tests for data/weather.py and load_weekly_with_weather."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.weather import load_archive, load_forecast


# ---------------------------------------------------------------------------
# load_archive
# ---------------------------------------------------------------------------


def test_load_archive_returns_empty_when_file_missing(tmp_path):
    """When the archive parquet doesn't exist, return empty DF with correct columns."""
    missing = tmp_path / "weather_archive.parquet"
    with patch("data.weather._ARCHIVE_PATH", missing):
        df = load_archive([2024])

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 0
    for col in ("game_id", "season", "week", "home_team", "kickoff_utc",
                "temp_f", "wind_mph", "wind_dir_deg", "precip_in", "weather_code", "indoor"):
        assert col in df.columns, f"Column '{col}' missing from empty archive"


def test_load_archive_filters_by_season(tmp_path):
    """Only rows matching the requested seasons are returned."""
    rows = [
        {
            "game_id": "2022_01_NE_BUF",
            "season": 2022,
            "week": 1,
            "home_team": "BUF",
            "kickoff_utc": pd.Timestamp("2022-09-11 17:00:00", tz="UTC"),
            "temp_f": 70.0,
            "wind_mph": 10.0,
            "wind_dir_deg": 270.0,
            "precip_in": 0.0,
            "weather_code": 0.0,
            "indoor": False,
        },
        {
            "game_id": "2023_01_NE_KC",
            "season": 2023,
            "week": 1,
            "home_team": "KC",
            "kickoff_utc": pd.Timestamp("2023-09-10 20:00:00", tz="UTC"),
            "temp_f": 80.0,
            "wind_mph": 5.0,
            "wind_dir_deg": 180.0,
            "precip_in": 0.1,
            "weather_code": 1.0,
            "indoor": False,
        },
    ]
    archive_path = tmp_path / "weather_archive.parquet"
    pd.DataFrame(rows).to_parquet(archive_path, index=False)

    with patch("data.weather._ARCHIVE_PATH", archive_path):
        result = load_archive([2022])

    assert len(result) == 1
    assert result.iloc[0]["season"] == 2022
    assert result.iloc[0]["game_id"] == "2022_01_NE_BUF"


# ---------------------------------------------------------------------------
# load_forecast
# ---------------------------------------------------------------------------


def test_load_forecast_returns_none_when_flag_off():
    """load_forecast returns None when use_live_forecast=False (default)."""
    result = load_forecast("2024_01_NE_BUF")
    assert result is None


# ---------------------------------------------------------------------------
# load_weekly_with_weather
# ---------------------------------------------------------------------------


def test_load_weekly_with_weather_joins_correctly():
    """Weather columns fan out to all player rows for matching game_id."""
    from data.nflverse_loader import load_weekly_with_weather

    stats_df = pd.DataFrame([
        {"player_id": "P1", "game_id": "2023_01_NE_BUF", "passing_yards": 300},
        {"player_id": "P2", "game_id": "2023_01_NE_BUF", "passing_yards": 50},
        {"player_id": "P3", "game_id": "2023_01_NE_KC",  "passing_yards": 200},
    ])
    weather_df = pd.DataFrame([
        {
            "game_id": "2023_01_NE_BUF",
            "season": 2023,
            "week": 1,
            "home_team": "BUF",
            "kickoff_utc": pd.Timestamp("2023-09-10 17:00:00", tz="UTC"),
            "temp_f": 72.0,
            "wind_mph": 12.0,
            "wind_dir_deg": 270.0,
            "precip_in": 0.0,
            "weather_code": 0.0,
            "indoor": False,
        },
    ])

    with (
        patch("data.nflverse_loader.load_weekly", return_value=stats_df),
        patch("data.weather._ARCHIVE_PATH", Path("/nonexistent/path/weather_archive.parquet")),
        patch("data.weather.load_archive", return_value=weather_df),
    ):
        result = load_weekly_with_weather(years=[2023])

    assert len(result) == 3

    buf_rows = result[result["game_id"] == "2023_01_NE_BUF"]
    assert len(buf_rows) == 2
    assert (buf_rows["temp_f"] == 72.0).all()
    assert (buf_rows["wind_mph"] == 12.0).all()
    assert (buf_rows["indoor"] == False).all()  # noqa: E712

    kc_rows = result[result["game_id"] == "2023_01_NE_KC"]
    assert len(kc_rows) == 1
    assert pd.isna(kc_rows.iloc[0]["temp_f"])
    assert pd.isna(kc_rows.iloc[0]["wind_mph"])
