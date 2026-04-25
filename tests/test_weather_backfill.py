"""Tests for scripts/backfill_weather.py.

All HTTP calls are mocked — no real network access.
"""

from __future__ import annotations

import sys
from datetime import datetime as dt
from datetime import timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.backfill_weather import (
    _extract_hour,
    _kickoff_utc,
    _rows_to_df,
    process_games,
    write_results,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OPEN_METEO_RESPONSE = {
    "hourly": {
        "time": [
            "2023-09-10T00:00",
            "2023-09-10T01:00",
            "2023-09-10T17:00",  # ~1pm ET = 17:00 UTC
            "2023-09-10T18:00",
            "2023-09-10T20:00",
            "2023-09-10T23:00",
        ],
        "temperature_2m": [15.0, 14.5, 22.2, 21.8, 20.0, 17.0],  # °C
        "wind_speed_10m": [10.0, 11.0, 20.0, 19.5, 18.0, 12.0],  # km/h
        "wind_direction_10m": [180, 185, 270, 265, 260, 200],
        "precipitation": [0.0, 0.0, 2.54, 1.27, 0.0, 0.0],  # mm
        "weather_code": [0, 0, 61, 61, 3, 1],
    }
}


def _make_game(game_id: str, home_team: str, gameday: str = "2023-09-10", gametime: str = "13:00") -> pd.DataFrame:
    return pd.DataFrame([{
        "game_id": game_id,
        "season": 2023,
        "week": 1,
        "home_team": home_team,
        "away_team": "NE",
        "gameday": gameday,
        "gametime": gametime,
    }])


# ---------------------------------------------------------------------------
# Test 1: Indoor game skipped — LV = Allegiant Stadium (fixed dome)
# ---------------------------------------------------------------------------

class TestIndoorGame:
    def test_indoor_row_has_indoor_true(self):
        games = _make_game("2023_01_NE_LV", "LV")
        with patch("scripts.backfill_weather.requests.get") as mock_get:
            rows = process_games(games, existing_ids=set(), sleep_secs=0)
            mock_get.assert_not_called()

        assert len(rows) == 1
        assert rows[0]["indoor"] is True

    def test_indoor_row_numeric_columns_are_na(self):
        games = _make_game("2023_01_NE_LV", "LV")
        with patch("scripts.backfill_weather.requests.get") as mock_get:
            rows = process_games(games, existing_ids=set(), sleep_secs=0)
            mock_get.assert_not_called()

        row = rows[0]
        for col in ("temp_f", "wind_mph", "wind_dir_deg", "precip_in", "weather_code"):
            assert pd.isna(row[col]), f"{col} should be NA for indoor game, got {row[col]}"

    def test_indoor_game_makes_zero_http_calls(self):
        games = _make_game("2023_01_NE_LV", "LV")
        with patch("scripts.backfill_weather.requests.get") as mock_get:
            process_games(games, existing_ids=set(), sleep_secs=0)

        mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# Test 2: Outdoor game — BUF (open air), mocked Open-Meteo response
# ---------------------------------------------------------------------------

class TestOutdoorGame:
    def _run_buf_game(self) -> list[dict]:
        games = _make_game("2023_01_NE_BUF", "BUF", gameday="2023-09-10", gametime="13:00")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _OPEN_METEO_RESPONSE

        with patch("scripts.backfill_weather.requests.get", return_value=mock_resp):
            rows = process_games(games, existing_ids=set(), sleep_secs=0)

        return rows

    def test_outdoor_row_has_indoor_false(self):
        rows = self._run_buf_game()
        assert len(rows) == 1
        assert rows[0]["indoor"] is False

    def test_outdoor_temp_f_converted(self):
        rows = self._run_buf_game()
        # 13:00 ET = 17:00 UTC → index 2 in mock data → 22.2°C → 71.96°F
        expected = 22.2 * 9 / 5 + 32
        assert abs(rows[0]["temp_f"] - expected) < 0.01

    def test_outdoor_wind_mph_converted(self):
        rows = self._run_buf_game()
        # 20.0 km/h → 12.4274 mph
        expected = 20.0 * 0.621371
        assert abs(rows[0]["wind_mph"] - expected) < 0.001

    def test_outdoor_precip_in_converted(self):
        rows = self._run_buf_game()
        # 2.54 mm → 0.1 in
        expected = 2.54 / 25.4
        assert abs(rows[0]["precip_in"] - expected) < 0.0001

    def test_outdoor_wind_dir_populated(self):
        rows = self._run_buf_game()
        assert rows[0]["wind_dir_deg"] == 270

    def test_outdoor_weather_code_populated(self):
        rows = self._run_buf_game()
        assert rows[0]["weather_code"] == 61.0

    def test_outdoor_makes_one_http_call(self):
        games = _make_game("2023_01_NE_BUF", "BUF", gameday="2023-09-10", gametime="13:00")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _OPEN_METEO_RESPONSE

        with patch("scripts.backfill_weather.requests.get", return_value=mock_resp) as mock_get:
            process_games(games, existing_ids=set(), sleep_secs=0)

        assert mock_get.call_count == 1


# ---------------------------------------------------------------------------
# Test 3: Idempotency — existing game_id skips HTTP call, output has one row
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_existing_game_skipped_no_http(self):
        game_id = "2023_01_NE_BUF"
        games = _make_game(game_id, "BUF")
        with patch("scripts.backfill_weather.requests.get") as mock_get:
            rows = process_games(games, existing_ids={game_id}, sleep_secs=0)

        assert rows == []
        mock_get.assert_not_called()

    def test_write_results_deduplicates(self, tmp_path):
        game_id = "2023_01_NE_BUF"
        # Write a first row into the archive.
        first_row = {
            "game_id": game_id,
            "season": 2023,
            "week": 1,
            "home_team": "BUF",
            "kickoff_utc": pd.Timestamp("2023-09-10 17:00:00", tz="UTC"),
            "temp_f": 71.96,
            "wind_mph": 12.43,
            "wind_dir_deg": 270.0,
            "precip_in": 0.1,
            "weather_code": 61.0,
            "indoor": False,
        }
        archive_path = tmp_path / "weather_archive.parquet"
        _rows_to_df([first_row]).to_parquet(archive_path, index=False)

        # Patch the module-level path and call write_results with same row.
        with patch("scripts.backfill_weather._ARCHIVE_PARQUET", archive_path), \
             patch("scripts.backfill_weather._CACHE_DIR", tmp_path):
            combined = write_results([first_row])

        # Should still have exactly one row for this game_id.
        assert combined[combined["game_id"] == game_id].shape[0] == 1

    def test_full_idempotency_no_double_rows(self, tmp_path):
        """End-to-end: two runs of process_games produce one row, not two."""
        game_id = "2023_01_NE_BUF"
        games = _make_game(game_id, "BUF", gameday="2023-09-10", gametime="13:00")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _OPEN_METEO_RESPONSE

        # First run.
        with patch("scripts.backfill_weather.requests.get", return_value=mock_resp):
            rows1 = process_games(games, existing_ids=set(), sleep_secs=0)

        # Second run: game_id already present.
        with patch("scripts.backfill_weather.requests.get") as mock_get2:
            rows2 = process_games(games, existing_ids={game_id}, sleep_secs=0)

        assert len(rows1) == 1
        assert rows2 == []
        mock_get2.assert_not_called()


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------

class TestKickoffUtc:
    def test_eastern_kickoff(self):
        # 1:00 PM ET on 2023-09-10 = 17:00 UTC (EDT = UTC-4)
        ko = _kickoff_utc("2023-09-10", "13:00", "America/New_York")
        assert ko.hour == 17
        assert ko.minute == 0

    def test_central_kickoff(self):
        # 12:00 PM CT = 17:00 UTC (CDT = UTC-5)
        ko = _kickoff_utc("2023-09-10", "12:00", "America/Chicago")
        assert ko.hour == 17

    def test_pacific_kickoff(self):
        # 1:05 PM PT = 20:05 UTC (PDT = UTC-7)
        ko = _kickoff_utc("2023-09-10", "13:05", "America/Los_Angeles")
        assert ko.hour == 20
        assert ko.minute == 5


class TestExtractHour:
    def test_picks_closest_hour(self):
        # Kickoff at 17:00 UTC → index 2 in mock data
        ko = dt(2023, 9, 10, 17, 0, tzinfo=timezone.utc)
        result = _extract_hour(_OPEN_METEO_RESPONSE, ko)
        assert abs(result["temp_f"] - (22.2 * 9 / 5 + 32)) < 0.01

    def test_unit_conversions(self):
        ko = dt(2023, 9, 10, 17, 0, tzinfo=timezone.utc)
        result = _extract_hour(_OPEN_METEO_RESPONSE, ko)
        assert abs(result["wind_mph"] - 20.0 * 0.621371) < 0.001
        assert abs(result["precip_in"] - 2.54 / 25.4) < 0.0001


class TestRowsToDf:
    def test_indoor_numeric_cols_are_nan(self):
        rows = [{
            "game_id": "2023_01_NE_LV",
            "season": 2023,
            "week": 1,
            "home_team": "LV",
            "kickoff_utc": pd.NaT,
            "temp_f": pd.NA,
            "wind_mph": pd.NA,
            "wind_dir_deg": pd.NA,
            "precip_in": pd.NA,
            "weather_code": pd.NA,
            "indoor": True,
        }]
        df = _rows_to_df(rows)
        assert df["indoor"].iloc[0]
        for col in ("temp_f", "wind_mph", "wind_dir_deg", "precip_in", "weather_code"):
            assert pd.isna(df[col].iloc[0]), f"{col} should be NaN"

    def test_empty_rows_returns_empty_df_with_columns(self):
        df = _rows_to_df([])
        for col in ("game_id", "temp_f", "indoor"):
            assert col in df.columns


class TestMissingGametime:
    def test_nan_gametime_skipped(self):
        games = pd.DataFrame([{
            "game_id": "2023_00_BYE_BUF",
            "season": 2023,
            "week": 9,
            "home_team": "BUF",
            "away_team": float("nan"),
            "gameday": "2023-11-05",
            "gametime": float("nan"),
        }])
        with patch("scripts.backfill_weather.requests.get") as mock_get:
            rows = process_games(games, existing_ids=set(), sleep_secs=0)
        assert rows == []
        mock_get.assert_not_called()

    def test_none_gameday_skipped(self):
        games = pd.DataFrame([{
            "game_id": "2023_00_TBD_KC",
            "season": 2023,
            "week": 18,
            "home_team": "KC",
            "away_team": "TBD",
            "gameday": None,
            "gametime": "TBD",
        }])
        with patch("scripts.backfill_weather.requests.get") as mock_get:
            rows = process_games(games, existing_ids=set(), sleep_secs=0)
        assert rows == []
        mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# Test 5: Retry and stop paths
# ---------------------------------------------------------------------------

class TestRetryAndStop:
    def test_5xx_retries_then_succeeds(self):
        """503 on first attempt, 200 on second - process_games returns one row."""
        games = _make_game("2023_01_NE_BUF", "BUF", gameday="2023-09-10", gametime="13:00")

        fail_resp = MagicMock()
        fail_resp.status_code = 503

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = _OPEN_METEO_RESPONSE

        with patch(
            "scripts.backfill_weather.requests.get",
            side_effect=[fail_resp, ok_resp],
        ) as mock_get:
            with patch("scripts.backfill_weather.time.sleep"):
                rows = process_games(games, existing_ids=set(), sleep_secs=0)

        assert len(rows) == 1
        assert mock_get.call_count == 2

    def test_429_stops_cleanly(self):
        """First game succeeds; second triggers RuntimeError (429 path) - no exception raised."""
        game1 = _make_game("2023_01_NE_BUF", "BUF", gameday="2023-09-10", gametime="13:00")
        game2 = _make_game("2023_01_NE_KC", "KC", gameday="2023-09-10", gametime="13:00")
        games = pd.concat([game1, game2], ignore_index=True)

        # First call returns valid data; second raises RuntimeError (simulates 429 stop).
        call_count = {"n": 0}

        def _fetch_side_effect(lat, lon, date_str):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _OPEN_METEO_RESPONSE
            raise RuntimeError("HTTP 429 from Open-Meteo - stopping (rate limit / forbidden)")

        with patch("scripts.backfill_weather._fetch_weather", side_effect=_fetch_side_effect):
            rows = process_games(games, existing_ids=set(), sleep_secs=0)

        assert len(rows) == 1
