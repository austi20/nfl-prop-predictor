from __future__ import annotations

from pathlib import Path

import pandas as pd

TRAINING_ODDS_FEATURE_EXCLUSIONS = frozenset({
    "actual_value",
    "outcome_over",
    "prior_games",
    "line_source",
    "line_window",
    "synthetic_source_version",
    "market_source",
    "market_prob_over_no_vig",
    "market_prob_under_no_vig",
    "vig_rate",
    "line_outlier_flag",
    "odds_outlier_flag",
    "eligible_for_training",
    "exclusion_reason",
    "book",
    "over_odds",
    "under_odds",
})


def load_synthetic_training_props(path: Path) -> pd.DataFrame:
    """Load the synthetic-surrogate odds dataset used for offline H/J/K prep."""
    df = pd.read_csv(Path(path))
    if "eligible_for_training" in df.columns:
        df = df[df["eligible_for_training"].astype(bool)].copy()
    if "market_source" in df.columns:
        sources = set(df["market_source"].dropna().astype(str))
        if sources and sources != {"synthetic_surrogate_v1"}:
            raise ValueError(f"Unsupported training market_source values: {sorted(sources)}")
    return df.reset_index(drop=True)
