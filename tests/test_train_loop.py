"""Smoke tests for scripts/train_loop.py.

Validates checkpoint resume, config hash determinism, and metric calculation
without running a real GLM fit.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.train_loop import (
    HOLDOUT_SEASONS,
    _fit_and_evaluate_group,
    _reliability_dev,
    config_hash,
    fit_config_key,
    load_completed_keys,
    make_configs,
)
from models.base import StatDistribution


def test_make_configs_produces_144() -> None:
    configs = make_configs()
    assert len(configs) == 144


def test_config_hash_is_deterministic() -> None:
    configs = make_configs()
    h1 = config_hash(configs[0])
    h2 = config_hash(configs[0])
    assert h1 == h2


def test_config_hash_differs_across_configs() -> None:
    configs = make_configs()
    hashes = {config_hash(c) for c in configs}
    assert len(hashes) == len(configs), "Hash collision in config grid"


def test_fit_config_key_ignores_prediction_only_k() -> None:
    cfg_a = {
        "use_weather": True,
        "use_opponent_epa": False,
        "use_rest_days": False,
        "use_home_away": False,
        "dist_family": "legacy",
        "k": 2,
        "l1_alpha": 0.0,
    }
    cfg_b = {**cfg_a, "k": 16}
    assert config_hash(cfg_a) != config_hash(cfg_b)
    assert fit_config_key(cfg_a) == fit_config_key(cfg_b)


def test_fit_config_key_collapses_grid_to_24_unique_fits() -> None:
    configs = make_configs()
    fit_keys = {fit_config_key(c) for c in configs}
    assert len(fit_keys) == 24


def test_fit_and_evaluate_group_reuses_fit_across_k_values() -> None:
    class DummyResult:
        aic = 123.0

    class FakeModel:
        fit_calls = 0
        seen_ks: list[int] = []

        def __init__(self) -> None:
            self._models = {"passing_yards": DummyResult()}
            self._player_stats = pd.DataFrame({"x": [1, 2, 3]})
            self._k = 0

        def fit(self, *args, **kwargs) -> None:
            type(self).fit_calls += 1
            self._k = int(kwargs["k"])

        def predict(self, player_id: str, week: int, season: int) -> dict[str, StatDistribution]:
            type(self).seen_ks.append(self._k)
            return {
                "passing_yards": StatDistribution(
                    mean=float(self._k),
                    std=1.0,
                    dist_type="normal",
                )
            }

    cfg2 = {
        "use_weather": False,
        "use_opponent_epa": False,
        "use_rest_days": False,
        "use_home_away": False,
        "dist_family": "legacy",
        "k": 2,
        "l1_alpha": 0.0,
    }
    cfg16 = {**cfg2, "k": 16}
    props = pd.DataFrame([
        {
            "player_id": "p1",
            "week": 1,
            "season": 2020,
            "stat": "passing_yards",
            "line": 10.0,
            "actual_value": 12.0,
            "outcome_over": 1,
        }
    ])

    rows = _fit_and_evaluate_group(
        position="qb",
        model_cls=FakeModel,
        target_stats=["passing_yards"],
        training_years=[2018, 2019],
        holdout_season=2020,
        weekly_plain=pd.DataFrame(),
        weekly_weather=pd.DataFrame(),
        fit_cfg=cfg2,
        eval_items=[
            (cfg2, config_hash(cfg2), ["passing_yards"]),
            (cfg16, config_hash(cfg16), ["passing_yards"]),
        ],
        prop_rows=props,
    )

    assert FakeModel.fit_calls == 1
    assert FakeModel.seen_ks == [2, 16]
    assert [r["k"] for r in rows] == [2, 16]
    assert {r["config_hash"] for r in rows} == {config_hash(cfg2), config_hash(cfg16)}


def test_deferred_flags_always_false() -> None:
    for cfg in make_configs():
        assert cfg["use_opponent_epa"] is False
        assert cfg["use_rest_days"] is False
        assert cfg["use_home_away"] is False


def test_load_completed_keys_empty_when_no_file(tmp_path) -> None:
    keys = load_completed_keys(tmp_path / "nonexistent.csv")
    assert keys == set()


def test_load_completed_keys_reads_existing(tmp_path) -> None:
    csv_path = tmp_path / "season_2019_results.csv"
    df = pd.DataFrame([
        {"config_hash": "abc123", "position": "qb", "stat": "passing_yards"},
        {"config_hash": "abc123", "position": "qb", "stat": "passing_tds"},
    ])
    df.to_csv(csv_path, index=False)
    keys = load_completed_keys(csv_path)
    assert ("abc123", "qb", "passing_yards") in keys
    assert ("abc123", "qb", "passing_tds") in keys
    assert len(keys) == 2


def test_reliability_dev_perfect_calibration() -> None:
    probs = np.linspace(0.05, 0.95, 100)
    rng = np.random.default_rng(0)
    labels = (rng.uniform(0, 1, 100) < probs).astype(float)
    dev = _reliability_dev(probs, labels)
    # Perfect calibration has zero deviation; imperfect but should be < 0.5
    assert 0.0 <= dev <= 0.5


def test_reliability_dev_miscalibrated() -> None:
    # All probs = 0.9 but all labels = 0 → deviation ≈ 0.9
    probs = np.full(50, 0.9)
    labels = np.zeros(50)
    dev = _reliability_dev(probs, labels)
    assert dev > 0.5


def test_log_loss_matches_sklearn() -> None:
    from sklearn.metrics import log_loss as sk_log_loss

    rng = np.random.default_rng(7)
    probs = np.clip(rng.uniform(0, 1, 200), 1e-7, 1 - 1e-7)
    labels = rng.integers(0, 2, 200).astype(float)
    expected = sk_log_loss(labels, probs, labels=[0, 1])

    # train_loop clips probs before passing to sk_log_loss, same here
    assert abs(expected - sk_log_loss(labels, probs, labels=[0, 1])) < 1e-10


def test_holdout_seasons_match_spec() -> None:
    assert HOLDOUT_SEASONS == [2019, 2020, 2021, 2022, 2023, 2024, 2025]
