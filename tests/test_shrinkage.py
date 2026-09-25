from __future__ import annotations

import json

import pytest

from models import shrinkage


@pytest.fixture(autouse=True)
def _clear_cache():
    shrinkage._load.cache_clear()
    yield
    shrinkage._load.cache_clear()


def test_known_stat_uses_its_fitted_weight():
    assert shrinkage.shrinkage_weight("qb", "passing_yards") == pytest.approx(0.7918)


def test_unknown_stat_falls_back_to_the_median():
    default, _ = shrinkage._load()
    assert shrinkage.shrinkage_weight("qb", "not_a_stat") == default


def test_shipped_weights_cover_every_modelled_stat():
    """A stat missing from the file silently reverts to the median, so the
    shipped file has to cover the models' full box score."""
    from eval.model_backtest import MODEL_SPECS

    _, weights = shrinkage._load()
    missing = [
        f"{spec.name}/{stat}"
        for spec in MODEL_SPECS
        for stat in spec.target_stats
        if f"{spec.name}/{stat}" not in weights
    ]
    # wr_te/rushing_tds is deliberately excluded: its leave-one-season-out CV is
    # 92%, so it is dropped in favour of the median weight.
    assert missing == ["wr_te/rushing_tds"]


def test_an_unstable_weight_is_dropped_for_the_default(tmp_path, monkeypatch):
    path = tmp_path / "w.json"
    path.write_text(
        json.dumps(
            {
                "default": 0.8,
                "weights": {"qb/steady": 0.5, "qb/jumpy": 0.5},
                "loo_cv": {"qb/steady": 0.01, "qb/jumpy": 0.9},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(shrinkage, "_WEIGHTS_FILE", path)
    shrinkage._load.cache_clear()

    assert shrinkage.shrinkage_weight("qb", "steady") == 0.5
    assert shrinkage.shrinkage_weight("qb", "jumpy") == 0.8


def test_a_missing_file_degrades_to_the_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(shrinkage, "_WEIGHTS_FILE", tmp_path / "absent.json")
    shrinkage._load.cache_clear()

    assert shrinkage.shrinkage_weight("rb", "carries") == shrinkage._FALLBACK
