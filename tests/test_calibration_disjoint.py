"""H4.5 tests: four-window calibration disjointness discipline.

Four windows must be mutually disjoint:
  model_train ⊥ calibrator_fit ⊥ policy_tune ⊥ final_eval
"""

from __future__ import annotations

import pytest


def test_four_windows_all_disjoint_passes():
    from eval.calibration_fit import assert_four_window_disjoint
    assert_four_window_disjoint(
        model_train=[2018, 2019, 2020],
        calibrator_fit=[2021],
        policy_tune=[2022],
        final_eval=[2023],
    )


def test_model_train_overlaps_calibrator_fit_raises():
    from eval.calibration_fit import assert_four_window_disjoint
    with pytest.raises(ValueError, match="2021"):
        assert_four_window_disjoint(
            model_train=[2018, 2019, 2020, 2021],
            calibrator_fit=[2021],
            policy_tune=[2022],
            final_eval=[2023],
        )


def test_calibrator_fit_overlaps_policy_tune_raises():
    from eval.calibration_fit import assert_four_window_disjoint
    with pytest.raises(ValueError, match="2022"):
        assert_four_window_disjoint(
            model_train=[2018, 2019, 2020],
            calibrator_fit=[2021, 2022],
            policy_tune=[2022],
            final_eval=[2023],
        )


def test_policy_tune_overlaps_final_eval_raises():
    from eval.calibration_fit import assert_four_window_disjoint
    with pytest.raises(ValueError, match="2023"):
        assert_four_window_disjoint(
            model_train=[2018, 2019, 2020],
            calibrator_fit=[2021],
            policy_tune=[2022, 2023],
            final_eval=[2023],
        )


def test_model_train_overlaps_final_eval_raises():
    from eval.calibration_fit import assert_four_window_disjoint
    with pytest.raises(ValueError, match="2018"):
        assert_four_window_disjoint(
            model_train=[2018, 2019],
            calibrator_fit=[2020],
            policy_tune=[2021],
            final_eval=[2018, 2022],
        )


def test_error_message_names_overlapping_years():
    from eval.calibration_fit import assert_four_window_disjoint
    with pytest.raises(ValueError, match="2021"):
        assert_four_window_disjoint(
            model_train=[2019, 2020, 2021],
            calibrator_fit=[2021, 2022],
            policy_tune=[2023],
            final_eval=[2024],
        )


def test_empty_windows_allowed():
    from eval.calibration_fit import assert_four_window_disjoint
    assert_four_window_disjoint(
        model_train=[2018, 2019],
        calibrator_fit=[],
        policy_tune=[],
        final_eval=[2020],
    )


def test_build_windows_helper_produces_disjoint_default():
    """build_training_windows() leaves final_eval empty after H4 consumes 2025."""
    from eval.calibration_fit import build_training_windows
    w = build_training_windows()
    assert w.final_eval == []
    assert_sets = [set(w.model_train), set(w.calibrator_fit), set(w.policy_tune), set(w.final_eval)]
    all_years = []
    for s in assert_sets:
        all_years.extend(s)
    assert len(all_years) == len(set(all_years)), "Default windows have overlap"
