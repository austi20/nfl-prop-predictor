"""Unit tests for evaluation_service._effective_train_years.

v0.9-m3.1 widened the fit window for future-season requests. This locks the
leakage-relevant behaviour: a request for season S must never fold S into the
training years, only complete seasons < S that the weekly frame actually has.
"""
from __future__ import annotations

import pandas as pd

from api.services.evaluation_service import _effective_train_years

_BASE = tuple(range(2015, 2024))  # 2015-2023 (matches AppSettings.default_train_years)


def _weekly(seasons: list[int]) -> pd.DataFrame:
    return pd.DataFrame({"season": seasons, "week": [1] * len(seasons)})


def test_no_widen_when_eval_season_within_one_of_window():
    # 2024 is max(base)+1 -> untouched (existing walk-forward semantics).
    assert _effective_train_years(_BASE, 2024, _weekly([2015, 2024])) == _BASE


def test_widen_for_2025_stops_before_eval_season():
    # 2025 request: fold in 2024 only. 2025 itself must NOT enter training.
    out = _effective_train_years(_BASE, 2025, _weekly(list(range(2015, 2026))))
    assert out == tuple(range(2015, 2025))
    assert 2025 not in out


def test_widen_for_2026_includes_2024_2025_only():
    out = _effective_train_years(_BASE, 2026, _weekly(list(range(2015, 2026))))
    assert out == tuple(range(2015, 2026))
    assert 2026 not in out


def test_widen_skips_seasons_absent_from_weekly():
    # weekly frame is missing 2025 -> only 2024 gets folded in.
    out = _effective_train_years(_BASE, 2026, _weekly(list(range(2015, 2025))))
    assert out == tuple(range(2015, 2025))


def test_empty_train_years_returns_unchanged():
    assert _effective_train_years((), 2026, _weekly([2024])) == ()


def test_missing_season_column_is_safe():
    out = _effective_train_years(_BASE, 2026, pd.DataFrame({"week": [1, 2]}))
    assert out == _BASE
