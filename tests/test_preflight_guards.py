from __future__ import annotations

import pandas as pd
import pytest

from eval.calibration_pipeline import assert_disjoint_years, build_calibration_rows
from eval.replay_pipeline import run_replay


def test_disjoint_year_guard_lists_overlap():
    with pytest.raises(ValueError, match="2024"):
        assert_disjoint_years([2022, 2024], [2024])


def test_calibration_rows_reject_overlap_before_fit():
    with pytest.raises(ValueError, match="2024"):
        build_calibration_rows(
            props_df=pd.DataFrame(columns=["player_id", "season", "week", "stat", "line"]),
            train_years=[2024],
            holdout_years=[2024],
            weekly=pd.DataFrame(),
        )


def test_run_replay_rejects_overlap(tmp_path):
    props = pd.DataFrame([
        {
            "player_id": "p1",
            "season": 2024,
            "week": 1,
            "stat": "passing_yards",
            "line": 250.5,
            "over_odds": -110,
            "under_odds": -110,
        }
    ])
    path = tmp_path / "props.csv"
    props.to_csv(path, index=False)

    with pytest.raises(ValueError, match="2024"):
        run_replay(path, train_years=[2024], replay_years=[2024])
