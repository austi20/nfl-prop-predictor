from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd

from eval.calibration_pipeline import (
    build_calibration_rows,
    load_props_file,
    run_calibration,
)


def _make_fake_weekly() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    seasons = [2022, 2023, 2024]
    weeks = [1, 2, 3, 4, 5, 6]

    for season in seasons:
        for week in weeks:
            rows.append({
                "player_id": "qb1",
                "player_name": "QB One",
                "position": "QB",
                "season": season,
                "week": week,
                "recent_team": "KC",
                "opponent_team": "LAC",
                "passing_yards": 220.0 + (season - 2022) * 4 + week * 8,
                "passing_tds": float(1 + (week % 3)),
                "interceptions": float(week % 2),
                "completions": 20.0 + week,
                "attempts": 30.0 + week,
                "sacks": float(week % 3),
                "air_yards_completed": 140.0 + week * 5,
                "is_home": float(week % 2),
            })
            rows.append({
                "player_id": "rb1",
                "player_name": "RB One",
                "position": "RB",
                "season": season,
                "week": week,
                "recent_team": "KC",
                "opponent_team": "LAC",
                "rushing_yards": 60.0 + (season - 2022) * 2 + week * 6,
                "carries": 12.0 + week,
                "rushing_tds": float(week % 2),
                "is_home": float((week + 1) % 2),
            })
            rows.append({
                "player_id": "wr1",
                "player_name": "WR One",
                "position": "WR",
                "season": season,
                "week": week,
                "recent_team": "KC",
                "opponent_team": "LAC",
                "receptions": 4.0 + week,
                "receiving_yards": 55.0 + (season - 2022) * 3 + week * 7,
                "receiving_tds": float(week % 2),
                "targets": 6.0 + week,
                "is_home": float(week % 2),
            })

    return pd.DataFrame(rows)


def _make_fake_props() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for week in [1, 2, 3, 4, 5, 6]:
        rows.append({
            "player_id": "qb1",
            "season": 2024,
            "week": week,
            "stat": "passing_yards",
            "line": 235.5 + week,
            "opp_team": "LAC",
            "book": "testbook",
        })
        rows.append({
            "player_id": "rb1",
            "season": 2024,
            "week": week,
            "stat": "rushing_yards",
            "line": 65.5 + week,
            "opp_team": "LAC",
            "book": "testbook",
        })
        rows.append({
            "player_id": "wr1",
            "season": 2024,
            "week": week,
            "stat": "receiving_yards",
            "line": 60.5 + week,
            "opp_team": "LAC",
            "book": "testbook",
        })
    return pd.DataFrame(rows)


def test_build_calibration_rows_returns_probabilities_and_outcomes():
    weekly = _make_fake_weekly()
    props = _make_fake_props()

    rows = build_calibration_rows(
        props_df=props,
        train_years=[2022, 2023],
        holdout_years=[2024],
        weekly=weekly,
    )

    assert len(rows) == len(props)
    assert rows["raw_prob"].between(0.0, 1.0).all()
    assert rows["outcome"].isin([0.0, 1.0]).all()


def test_load_props_file_rejects_missing_required_columns(tmp_path):
    props = pd.DataFrame([
        {
            "player_id": "qb1",
            "season": 2024,
            "week": 1,
            "line": 250.5,
        }
    ])
    path = tmp_path / "bad_props.csv"
    props.to_csv(path, index=False)

    try:
        load_props_file(path)
    except ValueError as exc:
        assert "Missing required prop columns" in str(exc)
    else:
        raise AssertionError("Expected missing required columns to raise")


def test_load_props_file_normalizes_opponent_fields(tmp_path):
    props = pd.DataFrame([
        {
            "player_id": "qb1",
            "season": 2024,
            "week": 1,
            "stat": "passing_yards",
            "line": 250.5,
            "opp_team": "LAC",
            "over_odds": -110,
            "under_odds": -110,
        }
    ])
    path = tmp_path / "props.csv"
    props.to_csv(path, index=False)

    loaded = load_props_file(path, require_odds=True)

    assert "opponent_team" in loaded.columns
    assert loaded.loc[0, "opponent_team"] == "LAC"
    assert loaded.loc[0, "opp_team"] == "LAC"


def test_build_calibration_rows_reports_skipped_rows():
    weekly = _make_fake_weekly()
    props = pd.DataFrame([
        {
            "player_id": "qb1",
            "season": 2024,
            "week": 1,
            "stat": "passing_yards",
            "line": 236.5,
            "opp_team": "LAC",
            "book": "testbook",
            "over_odds": -110,
            "under_odds": -110,
        },
        {
            "player_id": "qb1",
            "season": 2024,
            "week": 2,
            "stat": "made_up_stat",
            "line": 1.5,
            "opp_team": "LAC",
            "book": "testbook",
            "over_odds": -110,
            "under_odds": -110,
        },
        {
            "player_id": "rb1",
            "season": 2024,
            "week": 3,
            "stat": "rushing_yards",
            "line": 68.5,
            "opp_team": "LAC",
            "book": "testbook",
            "over_odds": None,
            "under_odds": -110,
        },
        {
            "player_id": "wr1",
            "season": 2024,
            "week": 99,
            "stat": "receiving_yards",
            "line": 67.5,
            "opp_team": "LAC",
            "book": "testbook",
            "over_odds": -110,
            "under_odds": -110,
        },
    ])

    rows, metadata = build_calibration_rows(
        props_df=props,
        train_years=[2022, 2023],
        holdout_years=[2024],
        weekly=weekly,
        strict_stats=False,
        require_odds=True,
        return_metadata=True,
    )

    assert len(rows) == 1
    assert metadata["skipped_rows"]["unsupported_stat"] == 1
    assert metadata["skipped_rows"]["missing_odds"] == 1
    assert metadata["skipped_rows"]["missing_actual_outcome"] == 1


def test_run_calibration_writes_artifacts(tmp_path):
    weekly = _make_fake_weekly()
    props = _make_fake_props()
    props_path = tmp_path / "props.csv"
    props.to_csv(props_path, index=False)

    docs_dir = tmp_path / "docs"
    model_dir = tmp_path / "models"

    with patch("eval.calibration_pipeline.load_weekly", return_value=weekly):
        report = run_calibration(
            props_path=props_path,
            train_years=[2022, 2023],
            holdout_years=[2024],
            docs_dir=docs_dir,
            model_dir=model_dir,
        )

    assert report["best_method"] in {"isotonic", "platt"}
    assert Path(report["artifact_path"]).exists()
    assert Path(report["plot_path"]).exists()
    assert (docs_dir / "calibration_report_2024.md").exists()
    assert (docs_dir / "calibration_report_2024.json").exists()
    assert (docs_dir / "calibration_rows_2024.csv").exists()
