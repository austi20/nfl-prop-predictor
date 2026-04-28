"""Tests for H2.5 residual-based uncertainty estimation."""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

from models.qb import QBModel
from models.rb import RBModel
from models.wr_te import WRTEModel


def _make_qb_weekly(n: int = 120, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "player_id": [f"p{i % 5}" for i in range(n)],
        "player_name": [f"QB{i % 5}" for i in range(n)],
        "position": ["QB"] * n,
        "season": [2018 + (i // 20) for i in range(n)],
        "week": [(i % 17) + 1 for i in range(n)],
        "recent_team": ["KC"] * n,
        "opponent_team": ["BUF"] * n,
        "passing_yards": np.clip(rng.normal(250, 55, n), 1, None),
        "passing_tds": rng.integers(0, 5, n).astype(float),
        "interceptions": rng.integers(0, 3, n).astype(float),
        "completions": np.clip(rng.normal(22, 5, n), 1, None),
        "attempts": np.clip(rng.normal(32, 6, n), 1, None),
        "sacks": rng.integers(0, 4, n).astype(float),
        "passing_air_yards": rng.uniform(150, 300, n),
        "passing_epa": rng.normal(0, 1, n),
        "dakota": rng.normal(0, 1, n),
    })


def _make_rb_weekly(n: int = 120, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "player_id": [f"p{i % 5}" for i in range(n)],
        "player_name": [f"RB{i % 5}" for i in range(n)],
        "position": ["RB"] * n,
        "season": [2018 + (i // 20) for i in range(n)],
        "week": [(i % 17) + 1 for i in range(n)],
        "recent_team": ["KC"] * n,
        "opponent_team": ["BUF"] * n,
        "rushing_yards": np.clip(rng.normal(60, 30, n), 0.01, None),
        "carries": np.clip(rng.normal(14, 5, n), 1, None),
        "rushing_tds": rng.integers(0, 2, n).astype(float),
        "rushing_epa": rng.normal(0, 1, n),
    })


def _make_wr_weekly(n: int = 120, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "player_id": [f"p{i % 5}" for i in range(n)],
        "player_name": [f"WR{i % 5}" for i in range(n)],
        "position": ["WR"] * n,
        "season": [2018 + (i // 20) for i in range(n)],
        "week": [(i % 17) + 1 for i in range(n)],
        "recent_team": ["KC"] * n,
        "opponent_team": ["BUF"] * n,
        "receptions": np.clip(rng.normal(5, 2, n), 0.01, None),
        "receiving_yards": np.clip(rng.normal(60, 25, n), 0.01, None),
        "receiving_tds": rng.integers(0, 2, n).astype(float),
        "targets": np.clip(rng.normal(7, 2, n), 1, None),
        "target_share": rng.uniform(0.05, 0.3, n),
        "air_yards_share": rng.uniform(0.05, 0.3, n),
        "wopr": rng.uniform(0.1, 0.5, n),
        "receiving_epa": rng.normal(0, 1, n),
    })


# --- QB ---

def test_qb_residual_stds_populated_after_fit():
    model = QBModel()
    model.fit([2018, 2019, 2020, 2021], weekly=_make_qb_weekly())
    assert len(model._residual_stds) > 0
    for std in model._residual_stds.values():
        assert std > 0


def test_qb_residual_std_is_positive_for_passing_yards():
    model = QBModel()
    model.fit([2018, 2019, 2020, 2021], weekly=_make_qb_weekly())
    assert "passing_yards" in model._residual_stds
    assert model._residual_stds["passing_yards"] > 0


def test_qb_legacy_distribution_no_warning_after_fit():
    model = QBModel()
    model.fit([2018, 2019, 2020, 2021], weekly=_make_qb_weekly())
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        dist = model._legacy_distribution("passing_yards", mean=250.0)
    residual_warns = [
        w for w in caught
        if issubclass(w.category, DeprecationWarning) and "residual" in str(w.message).lower()
    ]
    assert len(residual_warns) == 0
    assert dist.std > 0


def test_qb_legacy_distribution_warns_without_fit():
    model = QBModel()
    with pytest.warns(DeprecationWarning, match="residual"):
        dist = model._legacy_distribution("passing_yards", mean=250.0)
    assert dist.std > 0


# --- RB ---

def test_rb_residual_stds_populated_after_fit():
    model = RBModel()
    model.fit([2018, 2019, 2020, 2021], weekly=_make_rb_weekly())
    assert len(model._residual_stds) > 0
    for std in model._residual_stds.values():
        assert std > 0


def test_rb_legacy_distribution_no_warning_after_fit():
    model = RBModel()
    model.fit([2018, 2019, 2020, 2021], weekly=_make_rb_weekly())
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        dist = model._legacy_distribution("rushing_yards", mean=60.0)
    residual_warns = [
        w for w in caught
        if issubclass(w.category, DeprecationWarning) and "residual" in str(w.message).lower()
    ]
    assert len(residual_warns) == 0
    assert dist.std > 0


def test_rb_legacy_distribution_warns_without_fit():
    model = RBModel()
    with pytest.warns(DeprecationWarning, match="residual"):
        dist = model._legacy_distribution("rushing_yards", mean=60.0)
    assert dist.std > 0


# --- WR/TE ---

def test_wr_te_residual_stds_populated_after_fit():
    model = WRTEModel()
    model.fit([2018, 2019, 2020, 2021], weekly=_make_wr_weekly())
    assert len(model._residual_stds) > 0
    for std in model._residual_stds.values():
        assert std > 0


def test_wr_te_legacy_distribution_no_warning_after_fit():
    model = WRTEModel()
    model.fit([2018, 2019, 2020, 2021], weekly=_make_wr_weekly())
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        dist = model._legacy_distribution("receiving_yards", mean=60.0)
    residual_warns = [
        w for w in caught
        if issubclass(w.category, DeprecationWarning) and "residual" in str(w.message).lower()
    ]
    assert len(residual_warns) == 0
    assert dist.std > 0


def test_wr_te_legacy_distribution_warns_without_fit():
    model = WRTEModel()
    with pytest.warns(DeprecationWarning, match="residual"):
        dist = model._legacy_distribution("receiving_yards", mean=60.0)
    assert dist.std > 0


# --- Cross-model consistency ---

def test_residual_std_is_smaller_than_prior_std_after_fit():
    """Fitted residual std should be <= prior std since the GLM explains some variance."""
    model = QBModel()
    model.fit([2018, 2019, 2020, 2021], weekly=_make_qb_weekly())
    for stat, res_std in model._residual_stds.items():
        prior_std = model._prior_stds.get(stat, 0.0)
        if prior_std > 0:
            assert res_std <= prior_std * 1.05, (
                f"{stat}: residual_std={res_std:.3f} > prior_std={prior_std:.3f}"
            )
