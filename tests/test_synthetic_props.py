from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from eval.calibration_pipeline import load_props_file
from scripts.generate_synthetic_props import _build_rows, _round_line, generate


def _make_weekly() -> pd.DataFrame:
    """Minimal weekly DataFrame covering 2023 + 2024 for a QB, WR rookie, and RB."""
    rows: list[dict] = []

    # QB with 6 games in 2023 (history) + 6 games in 2024 (target)
    for season in [2023, 2024]:
        for week in range(1, 7):
            rows.append({
                "player_id": "qb1",
                "position": "QB",
                "season": season,
                "week": week,
                "recent_team": "KC",
                "opponent_team": "LAC",
                "passing_yards": 280.0 + week * 5,
                "passing_tds": 2.0,
                "interceptions": 0.5,
                "completions": 22.0 + week,
                "rushing_yards": 15.0,
                "carries": 3.0,
                "rushing_tds": 0.0,
            })

    # WR rookie with only 1 game in 2024 (should be excluded at min_games=3)
    rows.append({
        "player_id": "wr_rookie",
        "position": "WR",
        "season": 2024,
        "week": 2,
        "recent_team": "SF",
        "opponent_team": "DAL",
        "receptions": 4.0,
        "receiving_yards": 55.0,
        "receiving_tds": 0.0,
        "rushing_yards": 0.0,
        "carries": 0.0,
    })

    # RB with 4 games in 2023 + 4 in 2024
    for season in [2023, 2024]:
        for week in range(1, 5):
            rows.append({
                "player_id": "rb1",
                "position": "RB",
                "season": season,
                "week": week,
                "recent_team": "DAL",
                "opponent_team": "NYG",
                "rushing_yards": 80.0 + week * 3,
                "carries": 18.0 + week,
                "rushing_tds": 1.0,
                "receptions": 3.0,
                "receiving_yards": 22.0,
                "receiving_tds": 0.0,
            })

    return pd.DataFrame(rows)


class TestRoundLine:
    def test_yards_rounds_to_floor_plus_half(self):
        assert _round_line(87.4) == 87.5
        assert _round_line(87.6) == 87.5
        assert _round_line(87.0) == 87.5

    def test_count_stat_rounds_to_floor_plus_half(self):
        assert _round_line(1.8) == 1.5
        assert _round_line(2.0) == 2.5
        assert _round_line(0.7) == 0.5


class TestBuildRows:
    def test_qb_with_history_produces_expected_stats(self):
        weekly = _make_weekly()
        result = _build_rows(weekly, target_seasons=[2024], window=4, min_games=3)

        qb_rows = result[result["player_id"] == "qb1"]
        qb_stats = set(qb_rows["stat"].unique())

        # QB should get passing + rushing stats
        assert "passing_yards" in qb_stats
        assert "passing_tds" in qb_stats
        assert "rushing_yards" in qb_stats
        # QB should not get WR/TE-only stats
        assert "receiving_yards" not in qb_stats

    def test_rookie_wr_excluded_with_insufficient_history(self):
        weekly = _make_weekly()
        result = _build_rows(weekly, target_seasons=[2024], window=4, min_games=3)

        assert result[result["player_id"] == "wr_rookie"].empty

    def test_lines_are_positive_and_end_in_half(self):
        weekly = _make_weekly()
        result = _build_rows(weekly, target_seasons=[2024], window=4, min_games=3)

        assert (result["line"] > 0).all()
        # All lines should end in .5
        remainders = (result["line"] * 2) % 2
        assert (remainders == 1.0).all(), "All lines must end in .5"

    def test_no_duplicate_player_week_stat(self):
        weekly = _make_weekly()
        result = _build_rows(weekly, target_seasons=[2024], window=4, min_games=3)

        dupes = result.duplicated(subset=["player_id", "season", "week", "stat"])
        assert not dupes.any()

    def test_odds_columns_are_set(self):
        weekly = _make_weekly()
        result = _build_rows(weekly, target_seasons=[2024], window=4, min_games=3)

        assert (result["over_odds"] == -110).all()
        assert (result["under_odds"] == -110).all()
        assert (result["book"] == "synthetic").all()

    def test_only_target_seasons_in_output(self):
        weekly = _make_weekly()
        result = _build_rows(weekly, target_seasons=[2024], window=4, min_games=3)

        assert set(result["season"].unique()) == {2024}


class TestGenerateValidatesSchema:
    def test_output_passes_load_props_file_validation(self, tmp_path: Path):
        """Generated CSV must pass the calibration_pipeline schema check."""
        weekly = _make_weekly()

        # Patch load_weekly to return our fake data
        from unittest.mock import patch
        out_file = tmp_path / "test_props.csv"

        with patch("scripts.generate_synthetic_props.load_weekly", return_value=weekly):
            generate(seasons=[2024], window=4, min_games=3, out_file=out_file)

        assert out_file.exists()
        # This raises ValueError if schema validation fails
        loaded = load_props_file(out_file, require_odds=True)
        assert len(loaded) > 0
