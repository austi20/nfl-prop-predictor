"""Four-window calibration discipline for Phase H walk-forward training.

Enforces strict disjointness across:
  model_train ⊥ calibrator_fit ⊥ policy_tune ⊥ final_eval

The final_eval window (2025) is reserved and must not be touched until H5 close.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrainingWindows:
    model_train: list[int]
    calibrator_fit: list[int]
    policy_tune: list[int]
    final_eval: list[int]


def assert_four_window_disjoint(
    model_train: list[int],
    calibrator_fit: list[int],
    policy_tune: list[int],
    final_eval: list[int],
) -> None:
    """Raise ValueError if any two windows share a year."""
    windows = {
        "model_train": set(int(y) for y in model_train),
        "calibrator_fit": set(int(y) for y in calibrator_fit),
        "policy_tune": set(int(y) for y in policy_tune),
        "final_eval": set(int(y) for y in final_eval),
    }
    names = list(windows.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            overlap = sorted(windows[a] & windows[b])
            if overlap:
                raise ValueError(
                    f"Windows '{a}' and '{b}' overlap on years: {overlap}"
                )


def build_training_windows(
    *,
    model_train: list[int] | None = None,
    calibrator_fit: list[int] | None = None,
    policy_tune: list[int] | None = None,
    final_eval: list[int] | None = None,
) -> TrainingWindows:
    """Return the default four-window split for Phase H walk-forward.

    Default split (2018-2025):
      model_train:    2018-2021 (walk-forward harness trains here)
      calibrator_fit: 2022      (isotonic calibration fit)
      policy_tune:    2023-2024 (edge threshold + cap tuning)
      final_eval:     2025      (held out until H5 close - do not touch)
    """
    w = TrainingWindows(
        model_train=model_train if model_train is not None else list(range(2018, 2022)),
        calibrator_fit=calibrator_fit if calibrator_fit is not None else [2022],
        policy_tune=policy_tune if policy_tune is not None else [2023, 2024],
        final_eval=final_eval if final_eval is not None else [2025],
    )
    assert_four_window_disjoint(
        w.model_train, w.calibrator_fit, w.policy_tune, w.final_eval
    )
    return w
