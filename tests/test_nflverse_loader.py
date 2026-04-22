"""Smoke tests for data/nflverse_loader.py.

Fast tests mock nfl_data_py to avoid network calls.
Slow tests (marked @pytest.mark.slow) hit the real API and are skipped by default.
Run slow tests with: uv run pytest tests/test_nflverse_loader.py -m slow -v
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Ensure the project root is importable when running from any working dir.
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.nflverse_loader import (
    HOLDOUT_YEARS,
    TRAIN_YEARS,
    ALL_YEARS,
    DOME_TEAMS,
    is_dome,
    load_injuries,
    load_ngs,
    load_pbp,
    load_qbr,
    load_rosters,
    load_schedules,
    load_seasonal,
    load_snap_counts,
    load_team_desc,
    load_weekly,
    _cache_path,
    _CACHE_DIR,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SMALL_YEARS = [2023]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def tmp_cache(tmp_path, monkeypatch):
    """Redirect all cache writes to a temp directory so tests don't touch real cache."""
    import data.nflverse_loader as mod
    monkeypatch.setattr(mod, "_CACHE_DIR", tmp_path)
    return tmp_path


def _make_df(**cols) -> pd.DataFrame:
    """Build a minimal DataFrame with the given columns (each 1-row)."""
    return pd.DataFrame({k: [v] for k, v in cols.items()})


# ---------------------------------------------------------------------------
# Helper: assert loader returns non-empty DataFrame with required columns
# ---------------------------------------------------------------------------


def _check(df: pd.DataFrame, required_cols: list[str]) -> None:
    assert isinstance(df, pd.DataFrame)
    assert len(df) > 0, "DataFrame is empty"
    for col in required_cols:
        assert col in df.columns, f"Missing column: {col}"


# ---------------------------------------------------------------------------
# Unit tests (mocked nfl_data_py)
# ---------------------------------------------------------------------------


class TestLoadWeekly:
    _fake = _make_df(player_id="P1", season=2023, week=1, recent_team="KC", completions=10)

    def test_returns_dataframe_with_key_cols(self, tmp_cache):
        with patch("nfl_data_py.import_weekly_data", return_value=self._fake.copy()) as mock:
            df = load_weekly(_SMALL_YEARS)
        _check(df, ["player_id", "season", "week"])
        mock.assert_called_once()

    def test_cache_file_created(self, tmp_cache):
        with patch("nfl_data_py.import_weekly_data", return_value=self._fake.copy()):
            load_weekly(_SMALL_YEARS)
        assert any(tmp_cache.glob("weekly_*.parquet"))

    def test_cache_hit_skips_fetch(self, tmp_cache):
        with patch("nfl_data_py.import_weekly_data", return_value=self._fake.copy()) as mock:
            df1 = load_weekly(_SMALL_YEARS)
            df2 = load_weekly(_SMALL_YEARS)
        mock.assert_called_once()  # second call hits cache
        assert df1.equals(df2)

    def test_force_refresh_re_fetches(self, tmp_cache):
        with patch("nfl_data_py.import_weekly_data", return_value=self._fake.copy()) as mock:
            load_weekly(_SMALL_YEARS)
            load_weekly(_SMALL_YEARS, force_refresh=True)
        assert mock.call_count == 2


class TestLoadPbp:
    _fake = _make_df(play_id=1, game_id="2023_01_KC_LV", season=2023, week=1, epa=0.5)

    def test_returns_dataframe_with_key_cols(self, tmp_cache):
        with patch("nfl_data_py.import_pbp_data", return_value=self._fake.copy()):
            df = load_pbp(_SMALL_YEARS)
        _check(df, ["play_id", "game_id", "season"])

    def test_cache_file_created(self, tmp_cache):
        with patch("nfl_data_py.import_pbp_data", return_value=self._fake.copy()):
            load_pbp(_SMALL_YEARS)
        assert any(tmp_cache.glob("pbp_*.parquet"))

    def test_cache_hit_skips_fetch(self, tmp_cache):
        with patch("nfl_data_py.import_pbp_data", return_value=self._fake.copy()) as mock:
            load_pbp(_SMALL_YEARS)
            load_pbp(_SMALL_YEARS)
        mock.assert_called_once()


class TestLoadSeasonal:
    _fake = _make_df(player_id="P1", season=2023, completions=200)

    def test_returns_dataframe_with_key_cols(self, tmp_cache):
        with patch("nfl_data_py.import_seasonal_data", return_value=self._fake.copy()):
            df = load_seasonal(_SMALL_YEARS)
        _check(df, ["player_id", "season"])

    def test_cache_hit_skips_fetch(self, tmp_cache):
        with patch("nfl_data_py.import_seasonal_data", return_value=self._fake.copy()) as mock:
            load_seasonal(_SMALL_YEARS)
            load_seasonal(_SMALL_YEARS)
        mock.assert_called_once()


class TestLoadRosters:
    _fake = _make_df(player_id="P1", season=2023, team="KC", position="WR")

    def test_returns_dataframe_with_key_cols(self, tmp_cache):
        with patch("nfl_data_py.import_weekly_rosters", return_value=self._fake.copy()):
            df = load_rosters(_SMALL_YEARS)
        _check(df, ["player_id", "season", "position"])

    def test_cache_hit_skips_fetch(self, tmp_cache):
        with patch("nfl_data_py.import_weekly_rosters", return_value=self._fake.copy()) as mock:
            load_rosters(_SMALL_YEARS)
            load_rosters(_SMALL_YEARS)
        mock.assert_called_once()


class TestLoadSchedules:
    _fake = _make_df(game_id="2023_01_KC_LV", season=2023, week=1, home_team="KC", away_team="LV")

    def test_returns_dataframe_with_key_cols(self, tmp_cache):
        with patch("nfl_data_py.import_schedules", return_value=self._fake.copy()):
            df = load_schedules(_SMALL_YEARS)
        _check(df, ["game_id", "season", "week"])

    def test_cache_hit_skips_fetch(self, tmp_cache):
        with patch("nfl_data_py.import_schedules", return_value=self._fake.copy()) as mock:
            load_schedules(_SMALL_YEARS)
            load_schedules(_SMALL_YEARS)
        mock.assert_called_once()


class TestLoadTeamDesc:
    _fake = _make_df(team_abbr="KC", team_name="Chiefs")

    def test_returns_dataframe_with_team_abbr_col(self, tmp_cache):
        with patch("nfl_data_py.import_team_desc", return_value=self._fake.copy()):
            df = load_team_desc()
        _check(df, ["team_abbr"])

    def test_team_abbr_column_present(self, tmp_cache):
        with patch("nfl_data_py.import_team_desc", return_value=self._fake.copy()):
            df = load_team_desc()
        assert "team_abbr" in df.columns

    def test_cache_hit_skips_fetch(self, tmp_cache):
        with patch("nfl_data_py.import_team_desc", return_value=self._fake.copy()) as mock:
            load_team_desc()
            load_team_desc()
        mock.assert_called_once()


    def test_no_year_in_cache_filename(self, tmp_cache):
        with patch("nfl_data_py.import_team_desc", return_value=self._fake.copy()):
            load_team_desc()
        assert (tmp_cache / "team_desc.parquet").exists()


class TestLoadNgs:
    _fake = _make_df(player_gsis_id="P1", season=2023, week=1, avg_air_yards=10.0)

    @pytest.mark.parametrize("stat_type", ["passing", "rushing", "receiving"])
    def test_returns_dataframe(self, stat_type, tmp_cache):
        with patch("nfl_data_py.import_ngs_data", return_value=self._fake.copy()):
            df = load_ngs(stat_type, _SMALL_YEARS)
        assert len(df) > 0

    def test_cache_keyed_by_stat_type(self, tmp_cache):
        with patch("nfl_data_py.import_ngs_data", return_value=self._fake.copy()):
            load_ngs("passing", _SMALL_YEARS)
            load_ngs("rushing", _SMALL_YEARS)
        files = list(tmp_cache.glob("ngs_*.parquet"))
        names = {f.name for f in files}
        assert "ngs_passing_2023_2023.parquet" in names
        assert "ngs_rushing_2023_2023.parquet" in names

    def test_cache_hit_skips_fetch(self, tmp_cache):
        with patch("nfl_data_py.import_ngs_data", return_value=self._fake.copy()) as mock:
            load_ngs("passing", _SMALL_YEARS)
            load_ngs("passing", _SMALL_YEARS)
        mock.assert_called_once()


class TestLoadInjuries:
    _fake = _make_df(player_id="P1", season=2023, week=1, report_status="Questionable")

    def test_returns_dataframe_with_key_cols(self, tmp_cache):
        with patch("nfl_data_py.import_injuries", return_value=self._fake.copy()):
            df = load_injuries(_SMALL_YEARS)
        _check(df, ["player_id", "season", "week"])

    def test_cache_hit_skips_fetch(self, tmp_cache):
        with patch("nfl_data_py.import_injuries", return_value=self._fake.copy()) as mock:
            load_injuries(_SMALL_YEARS)
            load_injuries(_SMALL_YEARS)
        mock.assert_called_once()


class TestLoadSnapCounts:
    _fake = _make_df(player_id="P1", season=2023, week=1, offense_snaps=60)

    def test_returns_dataframe_with_key_cols(self, tmp_cache):
        with patch("nfl_data_py.import_snap_counts", return_value=self._fake.copy()):
            df = load_snap_counts(_SMALL_YEARS)
        _check(df, ["player_id", "season", "week"])

    def test_cache_hit_skips_fetch(self, tmp_cache):
        with patch("nfl_data_py.import_snap_counts", return_value=self._fake.copy()) as mock:
            load_snap_counts(_SMALL_YEARS)
            load_snap_counts(_SMALL_YEARS)
        mock.assert_called_once()


class TestLoadQbr:
    _fake = _make_df(player_id="P1", season=2023, week=1, qbr_total=75.0)

    def test_returns_dataframe_with_key_cols(self, tmp_cache):
        with patch("nfl_data_py.import_qbr", return_value=self._fake.copy()):
            df = load_qbr(_SMALL_YEARS)
        _check(df, ["player_id", "season", "week"])

    def test_cache_hit_skips_fetch(self, tmp_cache):
        with patch("nfl_data_py.import_qbr", return_value=self._fake.copy()) as mock:
            load_qbr(_SMALL_YEARS)
            load_qbr(_SMALL_YEARS)
        mock.assert_called_once()


# ---------------------------------------------------------------------------
# Cache staleness test
# ---------------------------------------------------------------------------


class TestCacheStaleness:
    _fake = _make_df(player_id="P1", season=2023, week=1)

    def test_stale_cache_triggers_refetch(self, tmp_cache, monkeypatch):
        import data.nflverse_loader as mod

        with patch("nfl_data_py.import_weekly_data", return_value=self._fake.copy()) as mock:
            load_weekly(_SMALL_YEARS)

        # Make the cache file appear older than 24h
        cache_file = tmp_cache / "weekly_2023_2023.parquet"
        old_mtime = time.time() - (25 * 60 * 60)
        import os
        os.utime(cache_file, (old_mtime, old_mtime))

        with patch("nfl_data_py.import_weekly_data", return_value=self._fake.copy()) as mock2:
            load_weekly(_SMALL_YEARS)
        mock2.assert_called_once()


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------


def test_year_constants():
    assert TRAIN_YEARS == list(range(2015, 2025))
    assert HOLDOUT_YEARS == [2025]
    assert ALL_YEARS == list(range(1999, 2026))
    assert 2025 not in TRAIN_YEARS
    assert 2024 in TRAIN_YEARS


def test_dome_teams_constant():
    assert isinstance(DOME_TEAMS, frozenset)
    assert "MIN" in DOME_TEAMS
    assert "BUF" not in DOME_TEAMS


def test_is_dome():
    assert is_dome("MIN") is True
    assert is_dome("BUF") is False


# ---------------------------------------------------------------------------
# Slow integration tests (real network)
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_slow_load_weekly_real():
    df = load_weekly([2023])
    _check(df, ["player_id", "season", "week"])


@pytest.mark.slow
def test_slow_load_team_desc_real():
    df = load_team_desc()
    assert "team_abbr" in df.columns
    assert len(df) > 30  # 32+ teams


@pytest.mark.slow
def test_slow_load_schedules_real():
    df = load_schedules([2023])
    _check(df, ["game_id", "season", "week"])


@pytest.mark.slow
def test_slow_load_rosters_real():
    df = load_rosters([2023])
    _check(df, ["player_id", "season"])
