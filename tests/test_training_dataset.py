from __future__ import annotations

import pandas as pd
import pytest

from eval.no_vig import remove_vig_two_sided
from eval.training_dataset import TRAINING_ODDS_FEATURE_EXCLUSIONS, load_synthetic_training_props


def test_training_loader_filters_ineligible_rows(tmp_path):
    path = tmp_path / "training.csv"
    pd.DataFrame([
        {
            "player_id": "p1",
            "market_source": "synthetic_surrogate_v1",
            "eligible_for_training": True,
        },
        {
            "player_id": "p2",
            "market_source": "synthetic_surrogate_v1",
            "eligible_for_training": False,
        },
    ]).to_csv(path, index=False)

    loaded = load_synthetic_training_props(path)

    assert loaded["player_id"].tolist() == ["p1"]


def test_training_loader_rejects_unknown_market_source(tmp_path):
    path = tmp_path / "training.csv"
    pd.DataFrame([
        {"player_id": "p1", "market_source": "unknown", "eligible_for_training": True},
    ]).to_csv(path, index=False)

    with pytest.raises(ValueError, match="market_source"):
        load_synthetic_training_props(path)


def test_training_no_vig_columns_match_utility_sample():
    sample = pd.read_csv("docs/training/synthetic_props_training.csv", nrows=25)
    for row in sample.itertuples(index=False):
        over, under = remove_vig_two_sided(int(row.over_odds), int(row.under_odds))
        assert over == pytest.approx(float(row.market_prob_over_no_vig), abs=0.02)
        assert under == pytest.approx(float(row.market_prob_under_no_vig), abs=0.02)


def test_training_exclusion_list_blocks_odds_from_features():
    assert "over_odds" in TRAINING_ODDS_FEATURE_EXCLUSIONS
    assert "market_prob_over_no_vig" in TRAINING_ODDS_FEATURE_EXCLUSIONS
    assert "outcome_over" in TRAINING_ODDS_FEATURE_EXCLUSIONS
