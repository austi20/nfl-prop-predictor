"""QB model - passing yards, TDs, INTs, completions.

Uses statsmodels Gamma GLM (log link) per stat with empirical-Bayes shrinkage.
Weather features are flag-guarded; default off to preserve parity with pre-H1 output.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import statsmodels.api as sm

from models.feature_utils import (
    add_group_rolling_mean,
    merge_group_context,
    safe_col,
    safe_ratio,
)
from models.base import StatDistribution


class _ConstantResult:
    """Fallback when GLM fails on sparse data - predicts training mean."""
    def __init__(self, mean: float) -> None:
        self._mean = mean
        self.aic = float("inf")

    def predict(self, X: Any) -> np.ndarray:
        n = X.shape[0] if hasattr(X, "shape") else 1
        return np.full(n, self._mean)


_WEEKLY_COLS = [
    "player_id", "player_name", "position", "season", "week", "recent_team",
    "opponent_team", "passing_yards", "passing_tds", "interceptions", "completions",
    "attempts", "sacks", "passing_air_yards", "passing_epa", "dakota",
]

_TARGET_STATS = ["passing_yards", "passing_tds", "interceptions", "completions"]

_MIN_MEAN = 1e-3

_FAMILIES = {
    "passing_yards": sm.families.Gamma(sm.families.links.Log()),
    "passing_tds": sm.families.Gamma(sm.families.links.Log()),
    "interceptions": sm.families.Gamma(sm.families.links.Log()),
    "completions": sm.families.Gamma(sm.families.links.Log()),
}


def _build_features(df: pd.DataFrame, *, use_weather: bool = False) -> tuple[pd.DataFrame, list[str]]:
    """Build per-player feature matrix. df must have weather cols when use_weather=True."""
    df = df.sort_values(["player_id", "season", "week"]).copy()

    attempts = safe_col(df, "attempts")
    sacks = safe_col(df, "sacks")
    completions = safe_col(df, "completions")
    passing_yards = safe_col(df, "passing_yards")
    passing_tds = safe_col(df, "passing_tds")
    interceptions = safe_col(df, "interceptions")

    total_drops = sacks + attempts
    df["pressure_proxy"] = np.where(total_drops > 0, sacks / total_drops, 0.0)
    df["yards_per_attempt"] = safe_ratio(passing_yards, attempts).to_numpy()
    df["td_rate"] = safe_ratio(passing_tds, attempts).to_numpy()
    df["int_rate"] = safe_ratio(interceptions, attempts).to_numpy()
    df["completion_rate"] = safe_ratio(completions, attempts).to_numpy()

    feature_cols: list[str] = []
    grp = df.groupby("player_id", group_keys=False)

    for col in _TARGET_STATS + ["attempts"]:
        fname = f"roll_{col}"
        df[fname] = grp[col].transform(lambda s: s.shift(1).rolling(4, min_periods=1).mean())
        feature_cols.append(fname)

    for source_col, feature_name in (
        ("yards_per_attempt", "roll_yards_per_attempt"),
        ("td_rate", "roll_td_rate"),
        ("int_rate", "roll_int_rate"),
        ("completion_rate", "roll_completion_rate"),
    ):
        df = add_group_rolling_mean(df, "player_id", source_col, feature_name)
        feature_cols.append(feature_name)

    df["roll_air_yards"] = (
        grp["passing_air_yards"].transform(lambda s: s.shift(1).rolling(4, min_periods=1).mean())
        if "passing_air_yards" in df.columns else 0.0
    )
    feature_cols.append("roll_air_yards")

    df["roll_pressure"] = grp["pressure_proxy"].transform(
        lambda s: s.shift(1).rolling(4, min_periods=1).mean()
    )
    feature_cols.append("roll_pressure")

    df["roll_passing_epa"] = (
        grp["passing_epa"].transform(lambda s: s.shift(1).rolling(4, min_periods=1).mean())
        if "passing_epa" in df.columns else 0.0
    )
    feature_cols.append("roll_passing_epa")

    df["roll_dakota"] = (
        grp["dakota"].transform(lambda s: s.shift(1).rolling(4, min_periods=1).mean())
        if "dakota" in df.columns else 0.0
    )
    feature_cols.append("roll_dakota")

    df, team_feature_cols = merge_group_context(
        df,
        group_col="recent_team",
        stat_cols=("passing_yards", "passing_tds", "completions", "attempts", "interceptions", "sacks"),
        prefix="team_pass",
    )
    feature_cols.extend(team_feature_cols)

    df, opponent_feature_cols = merge_group_context(
        df,
        group_col="opponent_team",
        stat_cols=("passing_yards", "passing_tds", "completions", "attempts", "interceptions", "sacks"),
        prefix="opp_pass_allowed",
    )
    feature_cols.extend(opponent_feature_cols)

    df["is_home"] = safe_col(df, "is_home", 0.5)
    feature_cols.append("is_home")

    df["week_num"] = df["week"].astype(float)
    feature_cols.append("week_num")

    if use_weather:
        indoor_mask = safe_col(df, "indoor", 0.0).astype(bool)
        wind = safe_col(df, "wind_mph", 0.0)
        precip = safe_col(df, "precip_in", 0.0)
        temp = safe_col(df, "temp_f", 60.0)

        df["wind_mph"] = np.where(indoor_mask, 0.0, wind)
        df["precip_in"] = np.where(indoor_mask, 0.0, precip)
        df["temp_f_minus_60"] = np.where(indoor_mask, 0.0, temp - 60.0)
        # Interaction: wind × rolling pass volume (outdoor only)
        df["wind_x_pass_attempt_rate"] = np.where(
            indoor_mask, 0.0, df["wind_mph"] * df["roll_attempts"]
        )
        feature_cols.extend(["wind_mph", "precip_in", "temp_f_minus_60", "wind_x_pass_attempt_rate"])

    df = df.fillna(0.0)
    return df, feature_cols


def _shrink_toward_prior(y: np.ndarray, n_obs: int, prior_mean: float, k: int = 8) -> float:
    weight = n_obs / (n_obs + k)
    observed_mean = float(y.mean()) if len(y) > 0 else prior_mean
    return prior_mean + weight * (observed_mean - prior_mean)


class QBModel:
    def __init__(self) -> None:
        self._models: dict[str, Any] = {}
        self._feature_cols: list[str] = []
        self._prior_means: dict[str, float] = {}
        self._prior_stds: dict[str, float] = {}
        self._player_stats: pd.DataFrame | None = None
        self._use_weather: bool = False

    def fit(
        self,
        years: list[int],
        weekly: pd.DataFrame | None = None,
        *,
        use_weather: bool = False,
        l1_alpha: float = 0.0,
    ) -> None:
        if weekly is None:
            from data.nflverse_loader import load_weekly
            weekly = load_weekly(years)
        else:
            weekly = weekly.copy()

        self._use_weather = use_weather

        qbs = weekly[weekly["position"] == "QB"].copy()
        for col in _WEEKLY_COLS:
            if col not in qbs.columns:
                qbs[col] = 0.0

        qbs, feature_cols = _build_features(qbs, use_weather=use_weather)
        train_qbs = qbs[qbs["season"].isin(years)].copy()
        self._feature_cols = feature_cols

        qbs = qbs.dropna(subset=feature_cols + _TARGET_STATS)
        train_qbs = train_qbs.dropna(subset=feature_cols + _TARGET_STATS)
        self._player_stats = qbs.copy()

        for stat in _TARGET_STATS:
            y = train_qbs[stat].values.astype(float)
            y_fit = np.clip(y, 1e-2, None)
            X = train_qbs[feature_cols].values.astype(float)
            X_const = sm.add_constant(X, has_constant="add")

            self._prior_means[stat] = float(y.mean()) if len(y) > 0 else 0.0
            self._prior_stds[stat] = float(y.std()) if len(y) > 0 else 1.0

            glm = sm.GLM(y_fit, X_const, family=_FAMILIES[stat])
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    if l1_alpha > 0.0:
                        result = glm.fit_regularized(alpha=l1_alpha, L1_wt=1.0, maxiter=500)
                    else:
                        result = glm.fit(maxiter=500)
                except (ValueError, np.linalg.LinAlgError):
                    result = _ConstantResult(float(y_fit.mean()))
            self._models[stat] = result

    def predict(
        self,
        player_id: str,
        week: int,
        season: int,
        opp_team: str | None = None,
        *,
        future_row: dict | None = None,
    ) -> dict[str, StatDistribution]:
        result: dict[str, StatDistribution] = {}

        if future_row is None and opp_team is not None:
            warnings.warn(
                "QBModel.predict(opp_team=...) without future_row uses the latest "
                "historical row's opponent context, not the upcoming opponent. "
                "Pass future_row=build_upcoming_row(...) to use upcoming-game context. "
                "This compatibility path will be removed after Phase H.",
                DeprecationWarning,
                stacklevel=2,
            )

        if not self._models or self._player_stats is None:
            for stat in _TARGET_STATS:
                result[stat] = StatDistribution(mean=0.0, std=0.0, dist_type="gamma")
            return result

        player_rows = self._player_stats[
            (self._player_stats["player_id"] == player_id)
            & (self._player_stats["season"] == season)
            & (self._player_stats["week"] < week)
        ]

        if future_row is None and player_rows.empty:
            for stat in _TARGET_STATS:
                mean = self._prior_means.get(stat, 0.0)
                std = self._prior_stds.get(stat, 0.0)
                result[stat] = StatDistribution(mean=mean, std=std, dist_type="gamma")
            return result

        if future_row is not None:
            X = np.array(
                [[float(future_row.get(col, 0.0) or 0.0) for col in self._feature_cols]],
                dtype=float,
            )
        else:
            latest = player_rows.sort_values("week").iloc[[-1]]
            X = latest[self._feature_cols].values.astype(float)

        X_const = sm.add_constant(X, has_constant="add")

        for stat in _TARGET_STATS:
            sm_result = self._models[stat]
            prior_mean = self._prior_means.get(stat, 0.0)
            prior_std = self._prior_stds.get(stat, 1.0)

            try:
                pred_mean = float(sm_result.predict(X_const)[0])
            except Exception:
                pred_mean = prior_mean

            n = len(player_rows)
            shrunk_mean = prior_mean + (n / (n + 8)) * (pred_mean - prior_mean)
            shrunk_mean = max(shrunk_mean, _MIN_MEAN)

            std = prior_std * (shrunk_mean / max(prior_mean, _MIN_MEAN))
            std = max(std, _MIN_MEAN)

            result[stat] = StatDistribution(mean=shrunk_mean, std=std, dist_type="gamma")

        return result

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @classmethod
    def load(cls, path: Path) -> "QBModel":
        return joblib.load(Path(path))
