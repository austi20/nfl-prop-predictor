"""WR/TE model - receptions, receiving yards, receiving TDs.

Uses Poisson GLM for receptions and TDs, Gamma GLM (log link) for yards,
with empirical-Bayes shrinkage.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import GammaRegressor, PoissonRegressor

from models.base import StatDistribution
from models.feature_utils import (
    add_group_rolling_mean,
    merge_group_context,
    safe_col,
    safe_ratio,
)

# Columns we want from weekly data
_WEEKLY_COLS = [
    "player_id", "player_name", "position", "season", "week", "recent_team",
    "opponent_team", "receptions", "receiving_yards", "receiving_tds", "targets",
    "target_share", "air_yards_share", "wopr", "receiving_epa",
]

_TARGET_STATS = ["receptions", "receiving_yards", "receiving_tds"]

# Minimum mean value to avoid degenerate fits
_MIN_MEAN = 1e-3

# Distribution type per stat
_DIST_TYPES: dict[str, str] = {
    "receptions": "poisson",
    "receiving_yards": "gamma",
    "receiving_tds": "poisson",
}

def _build_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Build per-player feature matrix. df must be sorted by player, season, week."""
    df = df.sort_values(["player_id", "season", "week"]).copy()

    targets = safe_col(df, "targets")
    receptions = safe_col(df, "receptions")
    receiving_yards = safe_col(df, "receiving_yards")
    receiving_tds = safe_col(df, "receiving_tds")
    df["catch_rate"] = safe_ratio(receptions, targets).to_numpy()
    df["yards_per_target"] = safe_ratio(receiving_yards, targets).to_numpy()
    df["tds_per_target"] = safe_ratio(receiving_tds, targets).to_numpy()

    feature_cols: list[str] = []

    grp = df.groupby("player_id", group_keys=False)

    for col in _TARGET_STATS + ["targets"]:
        fname = f"roll_{col}"
        df[fname] = grp[col].transform(lambda s: s.shift(1).rolling(4, min_periods=1).mean())
        feature_cols.append(fname)

    for source_col, feature_name in (
        ("catch_rate", "roll_catch_rate"),
        ("yards_per_target", "roll_yards_per_target"),
        ("tds_per_target", "roll_tds_per_target"),
    ):
        df = add_group_rolling_mean(df, "player_id", source_col, feature_name)
        feature_cols.append(feature_name)

    df["roll_target_share"] = grp["target_share"].transform(
        lambda s: s.shift(1).rolling(4, min_periods=1).mean()
    ) if "target_share" in df.columns else 0.0
    feature_cols.append("roll_target_share")

    df["roll_air_yards_share"] = grp["air_yards_share"].transform(
        lambda s: s.shift(1).rolling(4, min_periods=1).mean()
    ) if "air_yards_share" in df.columns else 0.0
    feature_cols.append("roll_air_yards_share")

    df["roll_wopr"] = grp["wopr"].transform(
        lambda s: s.shift(1).rolling(4, min_periods=1).mean()
    ) if "wopr" in df.columns else 0.0
    feature_cols.append("roll_wopr")

    df["roll_receiving_epa"] = grp["receiving_epa"].transform(
        lambda s: s.shift(1).rolling(4, min_periods=1).mean()
    ) if "receiving_epa" in df.columns else 0.0
    feature_cols.append("roll_receiving_epa")

    df, team_feature_cols = merge_group_context(
        df,
        group_col="recent_team",
        stat_cols=("receptions", "receiving_yards", "receiving_tds", "targets"),
        prefix="team_rec",
    )
    feature_cols.extend(team_feature_cols)

    df, opponent_feature_cols = merge_group_context(
        df,
        group_col="opponent_team",
        stat_cols=("receptions", "receiving_yards", "receiving_tds", "targets"),
        prefix="opp_rec_allowed",
    )
    feature_cols.extend(opponent_feature_cols)

    df["is_home"] = safe_col(df, "is_home", 0.5)
    feature_cols.append("is_home")

    df["week_num"] = df["week"].astype(float)
    feature_cols.append("week_num")

    df = df.fillna(0.0)
    return df, feature_cols


def _shrink_toward_prior(y: np.ndarray, n_obs: int, prior_mean: float, k: int = 8) -> float:
    """Empirical Bayes shrinkage: blend observed mean toward prior."""
    weight = n_obs / (n_obs + k)
    observed_mean = y.mean() if len(y) > 0 else prior_mean
    return prior_mean + weight * (observed_mean - prior_mean)


class WRTEModel:
    def __init__(self) -> None:
        self._models: dict[str, GammaRegressor | PoissonRegressor] = {}
        self._feature_cols: list[str] = []
        self._prior_means: dict[str, float] = {}
        self._prior_stds: dict[str, float] = {}
        self._player_stats: pd.DataFrame | None = None

    # ------------------------------------------------------------------
    # Fit
    # ------------------------------------------------------------------

    def fit(self, years: list[int], weekly: pd.DataFrame | None = None) -> None:
        if weekly is None:
            from data.nflverse_loader import load_weekly

            weekly = load_weekly(years)
        else:
            weekly = weekly.copy()

        receivers = weekly[weekly["position"].isin(["WR", "TE"])].copy()

        # Ensure required columns exist (fill missing with 0)
        for col in _WEEKLY_COLS:
            if col not in receivers.columns:
                receivers[col] = 0.0

        receivers, feature_cols = _build_features(receivers)
        train_receivers = receivers[receivers["season"].isin(years)].copy()
        self._feature_cols = feature_cols

        # Drop rows with NaN in features or targets
        receivers = receivers.dropna(subset=feature_cols + _TARGET_STATS)
        train_receivers = train_receivers.dropna(subset=feature_cols + _TARGET_STATS)

        # Store player rolling stats for predict()
        self._player_stats = receivers.copy()

        for stat in _TARGET_STATS:
            y = train_receivers[stat].values.astype(float)
            y_fit = np.clip(y, 1e-2, None)

            X = train_receivers[feature_cols].values.astype(float)

            self._prior_means[stat] = float(y.mean()) if len(y) > 0 else 0.0
            self._prior_stds[stat] = float(y.std()) if len(y) > 0 else 1.0

            if stat == "receiving_yards":
                model: GammaRegressor | PoissonRegressor = GammaRegressor(max_iter=500, alpha=0.1)
            else:
                model = PoissonRegressor()

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model.fit(X, y_fit)
            self._models[stat] = model

    # ------------------------------------------------------------------
    # Predict
    # ------------------------------------------------------------------

    def predict(
        self,
        player_id: str,
        week: int,
        season: int,
        opp_team: str,
    ) -> dict[str, StatDistribution]:
        result: dict[str, StatDistribution] = {}

        if not self._models or self._player_stats is None:
            for stat in _TARGET_STATS:
                result[stat] = StatDistribution(mean=0.0, std=0.0, dist_type=_DIST_TYPES[stat])
            return result

        player_rows = self._player_stats[
            (self._player_stats["player_id"] == player_id)
            & (self._player_stats["season"] == season)
            & (self._player_stats["week"] < week)
        ]

        if player_rows.empty:
            # No history - return prior means
            for stat in _TARGET_STATS:
                mean = self._prior_means.get(stat, 0.0)
                std = self._prior_stds.get(stat, 0.0)
                result[stat] = StatDistribution(mean=mean, std=std, dist_type=_DIST_TYPES[stat])
            return result

        # Use the most recent row's rolling features
        latest = player_rows.sort_values("week").iloc[[-1]]
        X = latest[self._feature_cols].values.astype(float)

        for stat in _TARGET_STATS:
            model = self._models[stat]
            prior_mean = self._prior_means.get(stat, 0.0)
            prior_std = self._prior_stds.get(stat, 1.0)

            try:
                pred_mean = float(model.predict(X)[0])
            except Exception:
                pred_mean = prior_mean

            # Empirical Bayes shrinkage
            n = len(player_rows)
            shrunk_mean = prior_mean + (n / (n + 8)) * (pred_mean - prior_mean)
            shrunk_mean = max(shrunk_mean, _MIN_MEAN)

            # Std: use positional std scaled by ratio of shrunk/prior
            std = prior_std * (shrunk_mean / max(prior_mean, _MIN_MEAN))
            std = max(std, _MIN_MEAN)

            result[stat] = StatDistribution(mean=shrunk_mean, std=std, dist_type=_DIST_TYPES[stat])

        return result

    # ------------------------------------------------------------------
    # Save / load
    # ------------------------------------------------------------------

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @classmethod
    def load(cls, path: Path) -> "WRTEModel":
        return joblib.load(Path(path))
