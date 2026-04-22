"""RB model - rushing yards, carries, rushing TDs.

Uses Tweedie GLM for rushing yards (zero-inflated continuous) and
Poisson GLM for carries and rushing TDs. Empirical-Bayes shrinkage
toward positional priors.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import PoissonRegressor, TweedieRegressor

from models.base import StatDistribution

# Columns we want from weekly data
_WEEKLY_COLS = [
    "player_id", "player_name", "position", "season", "week", "recent_team",
    "rushing_yards", "carries", "rushing_tds", "rushing_epa",
]

_TARGET_STATS = ["rushing_yards", "carries", "rushing_tds"]

# Minimum mean value to avoid degenerate fits
_MIN_MEAN = 1e-3

# dist_type per stat
_DIST_TYPE: dict[str, str] = {
    "rushing_yards": "tweedie",
    "carries": "poisson",
    "rushing_tds": "poisson",
}


def _safe_col(df: pd.DataFrame, col: str, fill: float = 0.0) -> pd.Series:
    if col in df.columns:
        return df[col].fillna(fill)
    return pd.Series(fill, index=df.index)


def _rolling_mean(series: pd.Series, window: int = 4) -> pd.Series:
    return series.shift(1).rolling(window, min_periods=1).mean()


def _build_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Build per-player feature matrix. df must be sorted by player, season, week."""
    df = df.sort_values(["player_id", "season", "week"]).copy()

    feature_cols: list[str] = []

    grp = df.groupby("player_id", group_keys=False)

    # 4-game rolling means of each target stat
    for col in _TARGET_STATS:
        fname = f"roll_{col}"
        df[fname] = grp[col].transform(lambda s: _rolling_mean(s))
        feature_cols.append(fname)

    df["roll_rushing_epa"] = grp["rushing_epa"].transform(
        lambda s: _rolling_mean(s)
    ) if "rushing_epa" in df.columns else 0.0
    feature_cols.append("roll_rushing_epa")

    df["is_home"] = _safe_col(df, "is_home", 0.5)
    feature_cols.append("is_home")

    df["week_num"] = df["week"].astype(float)
    feature_cols.append("week_num")

    df = df.fillna(0.0)
    return df, feature_cols


def _shrink_toward_prior(
    y: np.ndarray, n_obs: int, prior_mean: float, k: int = 8
) -> float:
    """Empirical Bayes shrinkage: blend observed mean toward prior."""
    weight = n_obs / (n_obs + k)
    observed_mean = float(y.mean()) if len(y) > 0 else prior_mean
    return prior_mean + weight * (observed_mean - prior_mean)


class RBModel:
    def __init__(self) -> None:
        self._models: dict[str, TweedieRegressor | PoissonRegressor] = {}
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

        rbs = weekly[weekly["position"] == "RB"].copy()

        # Ensure required columns exist (fill missing with 0)
        for col in _WEEKLY_COLS:
            if col not in rbs.columns:
                rbs[col] = 0.0

        rbs, feature_cols = _build_features(rbs)
        train_rbs = rbs[rbs["season"].isin(years)].copy()
        self._feature_cols = feature_cols

        # Drop rows with no data yet
        rbs = rbs.dropna(subset=feature_cols + _TARGET_STATS)
        train_rbs = train_rbs.dropna(subset=feature_cols + _TARGET_STATS)

        # Store player rolling stats for predict()
        self._player_stats = rbs.copy()

        for stat in _TARGET_STATS:
            y = train_rbs[stat].values.astype(float)
            # Tweedie/Poisson require strictly positive target
            y_fit = np.clip(y, 1e-2, None)

            X = train_rbs[feature_cols].values.astype(float)

            self._prior_means[stat] = float(y.mean()) if len(y) > 0 else 0.0
            self._prior_stds[stat] = float(y.std()) if len(y) > 0 else 1.0

            if stat == "rushing_yards":
                model: TweedieRegressor | PoissonRegressor = TweedieRegressor(
                    power=1.5, link="log", max_iter=500, alpha=0.1
                )
            else:
                model = PoissonRegressor(max_iter=500, alpha=0.1)

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
                result[stat] = StatDistribution(
                    mean=0.0, std=0.0, dist_type=_DIST_TYPE[stat]
                )
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
                result[stat] = StatDistribution(
                    mean=mean, std=std, dist_type=_DIST_TYPE[stat]
                )
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

            result[stat] = StatDistribution(
                mean=shrunk_mean, std=std, dist_type=_DIST_TYPE[stat]
            )

        return result

    # ------------------------------------------------------------------
    # Save / load
    # ------------------------------------------------------------------

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @classmethod
    def load(cls, path: Path) -> "RBModel":
        return joblib.load(Path(path))
