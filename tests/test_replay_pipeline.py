from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd

from eval.prop_pricer import PropCalibrator
from eval.replay_pipeline import run_replay, save_replay_report


def _make_fake_weekly() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for season in [2022, 2023, 2024]:
        for week in [1, 2, 3, 4, 5, 6]:
            rows.append({
                "player_id": "qb1",
                "player_name": "QB One",
                "position": "QB",
                "season": season,
                "week": week,
                "recent_team": "KC",
                "opponent_team": "LAC",
                "passing_yards": 230.0 + week * 8 + (season - 2022) * 2,
                "passing_tds": float(1 + (week % 3)),
                "interceptions": float(week % 2),
                "completions": 20.0 + week,
                "attempts": 31.0 + week,
                "sacks": float(week % 3),
                "passing_air_yards": 250.0 + week * 12,
                "passing_epa": 5.0 + week,
                "dakota": 10.0 + week,
                "is_home": float(week % 2),
                "game_id": f"{season}_{week}_KC_LAC",
            })
            rows.append({
                "player_id": "rb1",
                "player_name": "RB One",
                "position": "RB",
                "season": season,
                "week": week,
                "recent_team": "KC",
                "opponent_team": "LAC",
                "rushing_yards": 60.0 + week * 6,
                "carries": 12.0 + week,
                "rushing_tds": float(week % 2),
                "rushing_epa": 2.0 + week / 10,
                "is_home": float((week + 1) % 2),
                "game_id": f"{season}_{week}_KC_LAC",
            })
        rows.append({
            "player_id": "wr1",
            "player_name": "WR One",
            "position": "WR",
            "season": season,
            "week": 1,
            "recent_team": "KC",
            "opponent_team": "LAC",
            "receptions": 7.0,
            "receiving_yards": 84.0 + (season - 2022) * 2,
            "receiving_tds": 1.0,
            "targets": 10.0,
            "target_share": 0.24,
            "air_yards_share": 0.32,
            "wopr": 0.72,
            "receiving_epa": 6.0,
            "is_home": 1.0,
            "game_id": f"{season}_1_KC_LAC",
        })

    return pd.DataFrame(rows)


def _make_fake_props() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "player_id": "qb1",
            "season": 2024,
            "week": 1,
            "stat": "passing_yards",
            "line": 240.5,
            "opp_team": "LAC",
            "book": "testbook",
            "over_odds": -110,
            "under_odds": -110,
            "game_id": "2024_1_KC_LAC",
            "recent_team": "KC",
            "opponent_team": "LAC",
        },
        {
            "player_id": "rb1",
            "season": 2024,
            "week": 1,
            "stat": "rushing_yards",
            "line": 61.5,
            "opp_team": "LAC",
            "book": "testbook",
            "over_odds": -105,
            "under_odds": -115,
            "game_id": "2024_1_KC_LAC",
            "recent_team": "KC",
            "opponent_team": "LAC",
        },
        {
            "player_id": "wr1",
            "season": 2024,
            "week": 1,
            "stat": "receiving_yards",
            "line": 79.5,
            "opp_team": "LAC",
            "book": "otherbook",
            "over_odds": -110,
            "under_odds": -110,
            "game_id": "2024_1_KC_LAC",
            "recent_team": "KC",
            "opponent_team": "LAC",
        },
    ])


def test_run_replay_produces_picks_and_summary(tmp_path):
    props = _make_fake_props()
    props_path = tmp_path / "props.csv"
    props.to_csv(props_path, index=False)

    with patch("eval.calibration_pipeline.load_weekly", return_value=_make_fake_weekly()):
        report = run_replay(
            props_path=props_path,
            replay_years=[2024],
            train_years=[2022, 2023],
            min_edge=0.0,
        )

    assert not report["picks"].empty
    assert "roi" in report["summary"]
    assert "breakdowns" in report
    assert report["validation"]["skipped_rows"]["missing_odds"] == 0


def test_run_replay_supports_filters_and_calibrator(tmp_path):
    props = _make_fake_props()
    props_path = tmp_path / "props.csv"
    props.to_csv(props_path, index=False)

    calibrator = PropCalibrator(method="isotonic").fit(
        raw_probs=[0.45, 0.55, 0.65, 0.75],
        outcomes=[0.0, 0.0, 1.0, 1.0],
    )
    calibrator_path = tmp_path / "calibrator.joblib"
    calibrator.save(calibrator_path)

    with patch("eval.calibration_pipeline.load_weekly", return_value=_make_fake_weekly()):
        report = run_replay(
            props_path=props_path,
            replay_years=[2024],
            weeks=[1],
            stats=["passing_yards"],
            books=["testbook"],
            train_years=[2022, 2023],
            min_edge=0.0,
            calibrator_path=calibrator_path,
        )

    assert len(report["rows"]) == 1
    assert len(report["picks"]) == 1
    assert report["validation"]["rows_after_filters"] == 1
    assert report["validation"]["applied_filters"]["stats"] == ["passing_yards"]
    assert report["summary_payload"]["context"]["calibrator_path"].endswith("calibrator.joblib")


def test_save_replay_report_writes_files(tmp_path):
    props = _make_fake_props()
    props_path = tmp_path / "props.csv"
    props.to_csv(props_path, index=False)

    with patch("eval.calibration_pipeline.load_weekly", return_value=_make_fake_weekly()):
        report = run_replay(
            props_path=props_path,
            replay_years=[2024],
            train_years=[2022, 2023],
            min_edge=0.0,
        )

    save_replay_report(report, tmp_path, "2024")

    assert (tmp_path / "paper_trade_summary_2024.json").exists()
    assert (tmp_path / "paper_trade_summary_2024.md").exists()
    assert (tmp_path / "paper_trade_picks_2024.csv").exists()
    assert (tmp_path / "paper_trade_parlays_2024.csv").exists()
    assert (tmp_path / "paper_trade_breakdown_by_week_2024.csv").exists()
    assert (tmp_path / "paper_trade_breakdown_by_stat_2024.json").exists()
