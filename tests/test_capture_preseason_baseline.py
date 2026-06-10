from __future__ import annotations

import numpy as np
import pytest

from scripts.capture_preseason_baseline import (
    BaselineRow,
    format_markdown,
    score_predictions,
)


def test_score_predictions_perfect_calibration() -> None:
    y_true = np.array([1, 0, 1, 0])
    y_prob = np.array([1.0, 0.0, 1.0, 0.0])
    brier, log_loss = score_predictions(y_true=y_true, y_prob=y_prob)
    assert brier == pytest.approx(0.0)
    assert log_loss == pytest.approx(0.0, abs=1e-5)


def test_score_predictions_uniform_guess() -> None:
    y_true = np.array([1, 0, 1, 0])
    y_prob = np.array([0.5, 0.5, 0.5, 0.5])
    brier, log_loss = score_predictions(y_true=y_true, y_prob=y_prob)
    assert brier == pytest.approx(0.25)
    assert log_loss == pytest.approx(np.log(2.0), rel=1e-3)


def test_score_predictions_clips_extreme_probs_for_log_loss() -> None:
    # log(0) is -inf; the function must clip to avoid blowing up.
    y_true = np.array([1, 0])
    y_prob = np.array([0.0, 1.0])
    brier, log_loss = score_predictions(y_true=y_true, y_prob=y_prob)
    assert np.isfinite(log_loss)
    assert brier == pytest.approx(1.0)


def test_score_predictions_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError):
        score_predictions(y_true=np.array([1, 0]), y_prob=np.array([0.5]))


def test_score_predictions_rejects_out_of_range_probs() -> None:
    with pytest.raises(ValueError):
        score_predictions(y_true=np.array([1]), y_prob=np.array([1.5]))


def test_format_markdown_emits_one_row_per_baseline() -> None:
    rows = [
        BaselineRow(position="qb", stat="passing_yards", n=120, brier=0.21, log_loss=0.59),
        BaselineRow(position="rb", stat="rushing_yards", n=80, brier=0.24, log_loss=0.62),
    ]
    md = format_markdown(rows, year=2025)
    assert "# Preseason Baseline" in md
    assert "qb" in md and "passing_yards" in md
    assert "rb" in md and "rushing_yards" in md
    assert "0.21" in md
    assert "0.59" in md


def test_format_markdown_handles_empty_rows() -> None:
    md = format_markdown([], year=2025)
    assert "# Preseason Baseline" in md
    assert "no baseline rows" in md.lower()


def test_format_markdown_sorts_rows_position_then_stat() -> None:
    rows = [
        BaselineRow(position="wr_te", stat="receiving_yards", n=10, brier=0.1, log_loss=0.2),
        BaselineRow(position="qb", stat="passing_tds", n=10, brier=0.1, log_loss=0.2),
        BaselineRow(position="qb", stat="passing_yards", n=10, brier=0.1, log_loss=0.2),
    ]
    md = format_markdown(rows, year=2025)
    qb_yds_idx = md.index("passing_yards")
    qb_tds_idx = md.index("passing_tds")
    wr_idx = md.index("receiving_yards")
    assert qb_tds_idx < qb_yds_idx < wr_idx
