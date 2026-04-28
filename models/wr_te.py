"""WR/TE model - receptions, receiving yards, receiving TDs.

Uses statsmodels GLMs with an H1.5 stat-family layer:
- `legacy`: original Gamma/Poisson-style output
- `count_aware`: count stats use Poisson / NegBin (+ optional zero inflation)
- `decomposed`: receptions sampled from targets x catch rate
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import statsmodels.api as sm

from models.base import StatDistribution
from models.dist_family import (
    ConstantResult,
    CountFamilySpec,
    RateModelSpec,
    compose_receptions_distribution,
    fit_beta_rate_model,
    fit_count_model,
    fit_quantile_models,
    make_count_distribution,
    make_quantile_distribution,
    predict_quantiles,
)
from models.feature_utils import (
    add_group_rolling_mean,
    merge_group_context,
    safe_col,
    safe_ratio,
)
from models.glm_utils import fit_glm_with_optional_regularization

_WEEKLY_COLS = [
    "player_id",
    "player_name",
    "position",
    "season",
    "week",
    "recent_team",
    "opponent_team",
    "receptions",
    "receiving_yards",
    "receiving_tds",
    "targets",
    "target_share",
    "air_yards_share",
    "wopr",
    "receiving_epa",
]

_TARGET_STATS = ["receptions", "receiving_yards", "receiving_tds"]
_COUNT_STATS = {"receptions", "receiving_tds"}

_MIN_MEAN = 1e-3

_DIST_TYPES: dict[str, str] = {
    "receptions": "poisson",
    "receiving_yards": "gamma",
    "receiving_tds": "poisson",
}

_FAMILIES: dict[str, Any] = {
    "receptions": sm.families.Poisson(),
    "receiving_yards": sm.families.Gamma(sm.families.links.Log()),
    "receiving_tds": sm.families.Poisson(),
}


def _build_features(df: pd.DataFrame, *, use_weather: bool = False) -> tuple[pd.DataFrame, list[str]]:
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

    df["roll_target_share"] = (
        grp["target_share"].transform(lambda s: s.shift(1).rolling(4, min_periods=1).mean())
        if "target_share" in df.columns
        else 0.0
    )
    feature_cols.append("roll_target_share")

    df["roll_air_yards_share"] = (
        grp["air_yards_share"].transform(lambda s: s.shift(1).rolling(4, min_periods=1).mean())
        if "air_yards_share" in df.columns
        else 0.0
    )
    feature_cols.append("roll_air_yards_share")

    df["roll_wopr"] = (
        grp["wopr"].transform(lambda s: s.shift(1).rolling(4, min_periods=1).mean())
        if "wopr" in df.columns
        else 0.0
    )
    feature_cols.append("roll_wopr")

    df["roll_receiving_epa"] = (
        grp["receiving_epa"].transform(lambda s: s.shift(1).rolling(4, min_periods=1).mean())
        if "receiving_epa" in df.columns
        else 0.0
    )
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

    if use_weather:
        indoor_mask = safe_col(df, "indoor", 0.0).astype(bool)
        wind = safe_col(df, "wind_mph", 0.0)
        precip = safe_col(df, "precip_in", 0.0)
        temp = safe_col(df, "temp_f", 60.0)

        df["wind_mph"] = np.where(indoor_mask, 0.0, wind)
        df["precip_in"] = np.where(indoor_mask, 0.0, precip)
        df["temp_f_minus_60"] = np.where(indoor_mask, 0.0, temp - 60.0)
        feature_cols.extend(["wind_mph", "precip_in", "temp_f_minus_60"])

    df = df.fillna(0.0)
    return df, feature_cols


class WRTEModel:
    def __init__(self) -> None:
        self._models: dict[str, Any] = {}
        self._feature_cols: list[str] = []
        self._prior_means: dict[str, float] = {}
        self._prior_stds: dict[str, float] = {}
        self._player_stats: pd.DataFrame | None = None
        self._use_weather: bool = False
        self._dist_family: str = "legacy"
        self._count_specs: dict[str, CountFamilySpec] = {}
        self._quantile_models: dict[str, dict[float, Any]] = {}
        self._targets_model: Any | None = None
        self._targets_spec: CountFamilySpec | None = None
        self._catch_rate_model: RateModelSpec | None = None

    def _legacy_distribution(self, stat: str, mean: float) -> StatDistribution:
        prior_mean = self._prior_means.get(stat, 0.0)
        prior_std = self._prior_stds.get(stat, 1.0)
        std = prior_std * (mean / max(prior_mean, _MIN_MEAN))
        std = max(std, _MIN_MEAN)
        return StatDistribution(mean=mean, std=std, dist_type=_DIST_TYPES[stat])

    def fit(
        self,
        years: list[int],
        weekly: pd.DataFrame | None = None,
        *,
        use_weather: bool = False,
        l1_alpha: float = 0.0,
        dist_family: str = "legacy",
    ) -> None:
        if weekly is None:
            if use_weather:
                from data.nflverse_loader import load_weekly_with_weather

                weekly = load_weekly_with_weather(years)
            else:
                from data.nflverse_loader import load_weekly

                weekly = load_weekly(years)
        else:
            weekly = weekly.copy()

        self._use_weather = use_weather
        self._dist_family = dist_family
        self._count_specs = {}
        self._quantile_models = {}
        self._targets_model = None
        self._targets_spec = None
        self._catch_rate_model = None

        receivers = weekly[weekly["position"].isin(["WR", "TE"])].copy()
        for col in _WEEKLY_COLS:
            if col not in receivers.columns:
                receivers[col] = 0.0

        receivers, feature_cols = _build_features(receivers, use_weather=use_weather)
        train_receivers = receivers[receivers["season"].isin(years)].copy()
        self._feature_cols = feature_cols

        receivers = receivers.dropna(subset=feature_cols + _TARGET_STATS)
        train_receivers = train_receivers.dropna(subset=feature_cols + _TARGET_STATS)
        self._player_stats = receivers.copy()

        X = train_receivers[feature_cols].values.astype(float)
        X_const = sm.add_constant(X, has_constant="add")

        for stat in _TARGET_STATS:
            y = train_receivers[stat].values.astype(float)
            y_fit = np.clip(y, 1e-2, None)

            self._prior_means[stat] = float(y.mean()) if len(y) > 0 else 0.0
            self._prior_stds[stat] = float(y.std()) if len(y) > 0 else 1.0

            if dist_family != "legacy" and stat in _COUNT_STATS:
                try:
                    result, spec = fit_count_model(y, X_const, l1_alpha=l1_alpha, maxiter=500)
                except (ValueError, np.linalg.LinAlgError):
                    result, spec = ConstantResult(float(max(y.mean(), _MIN_MEAN))), CountFamilySpec("poisson")
                self._models[stat] = result
                self._count_specs[stat] = spec
                continue

            glm = sm.GLM(y_fit, X_const, family=_FAMILIES[stat])
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    result = fit_glm_with_optional_regularization(glm, l1_alpha=l1_alpha, maxiter=500)
                except (ValueError, np.linalg.LinAlgError):
                    result = ConstantResult(float(y_fit.mean()))
            self._models[stat] = result

            if dist_family != "legacy" and stat == "receiving_yards":
                self._quantile_models[stat] = fit_quantile_models(y, X_const)

        if dist_family == "decomposed":
            targets = train_receivers["targets"].values.astype(float)
            receptions = train_receivers["receptions"].values.astype(float)
            try:
                self._targets_model, self._targets_spec = fit_count_model(
                    targets,
                    X_const,
                    l1_alpha=l1_alpha,
                    maxiter=500,
                )
            except (ValueError, np.linalg.LinAlgError):
                self._targets_model = ConstantResult(float(max(targets.mean(), _MIN_MEAN)))
                self._targets_spec = CountFamilySpec("poisson")
            self._catch_rate_model = fit_beta_rate_model(receptions, targets, X_const, maxiter=500)

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
                "WRTEModel.predict(opp_team=...) without future_row uses the latest "
                "historical row's opponent context, not the upcoming opponent. "
                "Pass future_row=build_upcoming_row(...) to use upcoming-game context. "
                "This compatibility path will be removed after Phase H.",
                DeprecationWarning,
                stacklevel=2,
            )

        if not self._models or self._player_stats is None:
            for stat in _TARGET_STATS:
                result[stat] = StatDistribution(mean=0.0, std=0.0, dist_type=_DIST_TYPES[stat])
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
                result[stat] = StatDistribution(mean=mean, std=std, dist_type=_DIST_TYPES[stat])
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
            model_result = self._models[stat]
            prior_mean = self._prior_means.get(stat, 0.0)
            prior_std = self._prior_stds.get(stat, 1.0)

            try:
                pred_mean = float(model_result.predict(X_const)[0])
            except Exception:
                pred_mean = prior_mean
            ceiling = max(prior_mean + (6.0 * prior_std), prior_mean * 5.0, 1.0)
            pred_mean = float(np.clip(pred_mean, _MIN_MEAN, ceiling))

            n = len(player_rows)
            shrunk_mean = prior_mean + (n / (n + 8)) * (pred_mean - prior_mean)
            shrunk_mean = max(shrunk_mean, _MIN_MEAN)

            if self._dist_family == "decomposed" and stat == "receptions":
                dist = self._predict_receptions_distribution(
                    X_const,
                    shrunk_mean,
                    player_id=player_id,
                    season=season,
                    week=week,
                )
            elif self._dist_family != "legacy" and stat in self._count_specs:
                dist = make_count_distribution(shrunk_mean, self._count_specs[stat])
            elif self._dist_family != "legacy" and stat in self._quantile_models:
                quantiles = predict_quantiles(self._quantile_models[stat], X_const)
                if quantiles:
                    scale = shrunk_mean / max(pred_mean, _MIN_MEAN)
                    scaled_quantiles = {q: max(v * scale, 0.0) for q, v in quantiles.items()}
                    dist = make_quantile_distribution(
                        shrunk_mean,
                        self._legacy_distribution(stat, shrunk_mean).std,
                        scaled_quantiles,
                    )
                else:
                    dist = self._legacy_distribution(stat, shrunk_mean)
            else:
                dist = self._legacy_distribution(stat, shrunk_mean)

            result[stat] = dist

        return result

    def _predict_receptions_distribution(
        self,
        X_const: np.ndarray,
        mean: float,
        *,
        player_id: str,
        season: int,
        week: int,
    ) -> StatDistribution:
        if self._targets_model is None or self._targets_spec is None or self._catch_rate_model is None:
            return self._legacy_distribution("receptions", mean)

        try:
            targets_mean = max(float(self._targets_model.predict(X_const)[0]), _MIN_MEAN)
        except Exception:
            targets_mean = max(self._prior_means.get("receptions", 4.0), _MIN_MEAN)

        targets_dist = make_count_distribution(targets_mean, self._targets_spec)

        try:
            catch_rate_mean = float(self._catch_rate_model.result.predict(X_const)[0])
        except Exception:
            catch_rate_mean = self._catch_rate_model.mean
        catch_rate_mean = float(np.clip(catch_rate_mean, 1e-4, 1.0 - 1e-4))

        raw_mean = max(targets_mean * catch_rate_mean, _MIN_MEAN)
        scaled_catch_rate = float(np.clip(catch_rate_mean * (mean / raw_mean), 1e-4, 1.0 - 1e-4))
        return compose_receptions_distribution(
            targets_dist,
            scaled_catch_rate,
            self._catch_rate_model.concentration,
            seed_parts=("wrte_receptions", player_id, season, week),
            samples=1000,
        )

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @classmethod
    def load(cls, path: Path) -> "WRTEModel":
        return joblib.load(Path(path))
