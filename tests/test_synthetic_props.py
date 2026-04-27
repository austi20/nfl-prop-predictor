from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from eval.calibration_pipeline import load_props_file
from eval.replay_pipeline import run_replay
from models.qb import _build_features as _build_qb_features
from models.rb import _build_features as _build_rb_features
from models.wr_te import _build_features as _build_wr_te_features
from scripts.generate_synthetic_props import (
    TRAINING_OUTPUT_COLUMNS,
    _build_rows,
    _build_training_rows,
    _round_line,
    generate,
)


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

    # WR with enough history to fit WR/TE model paths in replay compatibility tests.
    for season in [2023, 2024]:
        for week in range(1, 5):
            rows.append({
                "player_id": "wr1",
                "position": "WR",
                "season": season,
                "week": week,
                "recent_team": "SF",
                "opponent_team": "DAL",
                "receptions": 5.0 + (week % 2),
                "receiving_yards": 60.0 + week * 4,
                "receiving_tds": float(week % 2),
                "rushing_yards": 0.0,
                "carries": 0.0,
                "targets": 8.0 + week,
                "target_share": 0.22,
                "air_yards_share": 0.30,
                "wopr": 0.65,
                "receiving_epa": 4.0 + week,
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

    def test_default_generate_does_not_emit_training_columns(self, tmp_path: Path):
        weekly = _make_weekly()
        out_file = tmp_path / "test_props.csv"
        training_file = tmp_path / "training.csv"

        from unittest.mock import patch

        with patch("scripts.generate_synthetic_props.load_weekly", return_value=weekly):
            generate(seasons=[2024], window=4, min_games=3, out_file=out_file)

        loaded = pd.read_csv(out_file)
        assert "market_source" not in loaded.columns
        assert "actual_value" not in loaded.columns
        assert not training_file.exists()


class TestTrainingDataset:
    def test_training_rows_add_schema_and_varied_odds(self):
        weekly = _make_weekly()
        props = _build_rows(weekly, target_seasons=[2024], window=4, min_games=3)

        training = _build_training_rows(weekly, props, window=4)

        assert list(training.columns) == TRAINING_OUTPUT_COLUMNS
        loaded = load_props_file_for_test(training)
        assert len(loaded) == len(training)
        assert (training["market_source"] == "synthetic_surrogate_v1").all()
        assert not (
            (training["over_odds"] == -110) & (training["under_odds"] == -110)
        ).all()
        assert (
            (training["market_prob_over_no_vig"] + training["market_prob_under_no_vig"])
            .round(12)
            == 1.0
        ).all()

    def test_training_generation_is_deterministic(self):
        weekly = _make_weekly()
        props = _build_rows(weekly, target_seasons=[2024], window=4, min_games=3)

        first = _build_training_rows(weekly, props, window=4)
        second = _build_training_rows(weekly, props, window=4)

        pd.testing.assert_frame_equal(first, second)

    def test_target_game_outcome_does_not_change_that_rows_odds(self):
        weekly = _make_weekly()
        props = _build_rows(weekly, target_seasons=[2024], window=4, min_games=3)

        changed = weekly.copy()
        target_mask = (
            (changed["player_id"] == "qb1")
            & (changed["season"] == 2024)
            & (changed["week"] == 4)
        )
        changed.loc[target_mask, "passing_yards"] = 999.0

        baseline = _build_training_rows(weekly, props, window=4)
        mutated = _build_training_rows(changed, props, window=4)

        key = (
            (baseline["player_id"] == "qb1")
            & (baseline["season"] == 2024)
            & (baseline["week"] == 4)
            & (baseline["stat"] == "passing_yards")
        )
        odds_cols = ["over_odds", "under_odds", "market_prob_over_no_vig", "market_prob_under_no_vig"]
        pd.testing.assert_frame_equal(
            baseline.loc[key, odds_cols].reset_index(drop=True),
            mutated.loc[key, odds_cols].reset_index(drop=True),
        )
        assert baseline.loc[key, "actual_value"].iloc[0] != mutated.loc[key, "actual_value"].iloc[0]

    def test_outlier_flags_do_not_make_rows_ineligible(self):
        weekly = _weekly_for_outlier_test()
        props = pd.DataFrame([
            _prop_row(f"rb{i}", 2024, 1, "rushing_yards", line, actual=actual)
            for i, (line, actual) in enumerate(
                [(10.5, 11.0), (11.5, 12.0), (12.5, 13.0), (13.5, 14.0), (100.5, 101.0)],
                start=1,
            )
        ])

        training = _build_training_rows(weekly, props, window=4)

        outlier = training[training["line"] == 100.5].iloc[0]
        assert bool(outlier["line_outlier_flag"]) is True
        assert bool(outlier["eligible_for_training"]) is True
        assert outlier["exclusion_reason"] == ""

    def test_generate_writes_training_file_when_requested(self, tmp_path: Path):
        weekly = _make_weekly()
        out_file = tmp_path / "replay.csv"
        training_file = tmp_path / "training" / "synthetic_props_training.csv"

        from unittest.mock import patch

        with patch("scripts.generate_synthetic_props.load_weekly", return_value=weekly):
            generate(
                seasons=[2024],
                window=4,
                min_games=3,
                out_file=out_file,
                emit_training_dataset=True,
                training_out_file=training_file,
            )

        assert out_file.exists()
        assert training_file.exists()
        training = pd.read_csv(training_file)
        assert list(training.columns) == TRAINING_OUTPUT_COLUMNS
        load_props_file(training_file, require_odds=True)

    def test_replay_pipeline_accepts_training_dataset_with_varied_odds(self):
        weekly = _make_weekly()
        props = _build_rows(weekly, target_seasons=[2024], window=4, min_games=3)
        training = _build_training_rows(weekly, props, window=4)

        report = run_replay(
            props_path=_write_tmp_training(training),
            replay_years=[2024],
            train_years=[2023],
            weekly=weekly,
            min_edge=0.0,
        )

        assert report["validation"]["rows_priced"] > 0
        assert report["validation"]["skipped_rows"]["missing_odds"] == 0

    def test_odds_columns_are_not_model_features(self):
        weekly = _make_weekly().copy()
        for col in ("attempts", "sacks", "passing_air_yards", "passing_epa", "dakota", "is_home"):
            if col not in weekly.columns:
                weekly[col] = 1.0
        for col in TRAINING_OUTPUT_COLUMNS:
            if col not in weekly.columns:
                weekly[col] = 1.0
        forbidden = set(TRAINING_OUTPUT_COLUMNS) - {"season", "week", "recent_team", "opponent_team"}

        _, qb_features = _build_qb_features(weekly[weekly["position"] == "QB"])
        _, rb_features = _build_rb_features(weekly[weekly["position"] == "RB"])
        _, wr_features = _build_wr_te_features(weekly[weekly["position"].isin(["WR", "TE"])])

        assert not (set(qb_features) & forbidden)
        assert not (set(rb_features) & forbidden)
        assert not (set(wr_features) & forbidden)


def load_props_file_for_test(training: pd.DataFrame) -> pd.DataFrame:
    path = Path("tmp") / "synthetic_training_test.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    training.to_csv(path, index=False)
    return load_props_file(path, require_odds=True)


def _write_tmp_training(training: pd.DataFrame) -> Path:
    path = Path("tmp") / "synthetic_training_replay_test.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    training.to_csv(path, index=False)
    return path


def _prop_row(
    player_id: str,
    season: int,
    week: int,
    stat: str,
    line: float,
    *,
    actual: float,
) -> dict[str, object]:
    return {
        "player_id": player_id,
        "season": season,
        "week": week,
        "stat": stat,
        "line": line,
        "book": "synthetic",
        "over_odds": -110,
        "under_odds": -110,
        "recent_team": "KC",
        "opponent_team": "LAC",
        "game_id": f"{season}_{week:02d}_KC_LAC_{player_id}",
        "_actual": actual,
    }


def _weekly_for_outlier_test() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for i, line in enumerate([10.5, 11.5, 12.5, 13.5, 100.5], start=1):
        player_id = f"rb{i}"
        for week, yards in enumerate([line + 1.0, line + 2.0, line + 3.0], start=1):
            rows.append({
                "player_id": player_id,
                "position": "RB",
                "season": 2023,
                "week": week,
                "recent_team": "KC",
                "opponent_team": "LAC",
                "rushing_yards": yards,
                "carries": 8.0,
                "rushing_tds": 0.0,
            })
        rows.append({
            "player_id": player_id,
            "position": "RB",
            "season": 2024,
            "week": 1,
            "recent_team": "KC",
            "opponent_team": "LAC",
            "rushing_yards": line + 0.5,
            "carries": 8.0,
            "rushing_tds": 0.0,
        })
    return pd.DataFrame(rows)
