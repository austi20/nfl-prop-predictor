"""RB model - rushing yards, carries, rushing TDs.

Uses statsmodels GLMs with an H1.5 stat-family layer:
- `legacy`: Tweedie/Poisson-style legacy output
- `count_aware`: count stats use Poisson / NegBin (+ optional zero inflation)
- `decomposed`: rushing yards sampled from carries x yards-per-carry
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
    compose_product_distribution,
    fit_count_model,
    fit_gamma_rate_model,
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
    "rushing_yards",
    "carries",
    "rushing_tds",
    "rushing_epa",
]

_TARGET_STATS = ["rushing_yards", "carries", "rushing_tds"]
_COUNT_STATS = {"carries", "rushing_tds"}

_MIN_MEAN = 1e-3

_DIST_TYPE: dict[str, str] = {
    "rushing_yards": "tweedie",
    "carries": "poisson",
    "rushing_tds": "poisson",
}

_FAMILIES: dict[str, Any] = {
    "rushing_yards": sm.families.Tweedie(var_power=1.5, link=sm.families.links.Log()),
    "carries": sm.families.Poisson(),
    "rushing_tds": sm.families.Poisson(),
}


def _build_features(df: pd.DataFrame, *, use_weather: bool = False) -> tuple[pd.DataFrame, list[str]]:
    df = df.sort_values(["player_id", "season", "week"]).copy()

    carries = safe_col(df, "carries")
    rushing_yards = safe_col(df, "rushing_yards")
    rushing_tds = safe_col(df, "rushing_tds")
    df["yards_per_carry"] = safe_ratio(rushing_yards, carries).to_numpy()
    df["tds_per_carry"] = safe_ratio(rushing_tds, carries).to_numpy()

    feature_cols: list[str] = []
    grp = df.groupby("player_id", group_keys=False)

    for col in _TARGET_STATS:
        fname = f"roll_{col}"
        df[fname] = grp[col].transform(lambda s: s.shift(1).rolling(4, min_periods=1).mean())
        feature_cols.append(fname)

    for source_col, feature_name in (
        ("yards_per_carry", "roll_yards_per_carry"),
        ("tds_per_carry", "roll_tds_per_carry"),
    ):
        df = add_group_rolling_mean(df, "player_id", source_col, feature_name)
        feature_cols.append(feature_name)

    df["roll_rushing_epa"] = (
        grp["rushing_epa"].transform(lambda s: s.shift(1).rolling(4, min_periods=1).mean())
        if "rushing_epa" in df.columns
        else 0.0
    )
    feature_cols.append("roll_rushing_epa")

    df, team_feature_cols = merge_group_context(
        df,
        group_col="recent_team",
        stat_cols=("rushing_yards", "carries", "rushing_tds"),
        prefix="team_rush",
    )
    feature_cols.extend(team_feature_cols)

    df, opponent_feature_cols = merge_group_context(
        df,
        group_col="opponent_team",
        stat_cols=("rushing_yards", "carries", "rushing_tds"),
        prefix="opp_rush_allowed",
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


class RBModel:
    def __init__(self) -> None:
        self._models: dict[str, Any] = {}
        self._feature_cols: list[str] = []
        self._prior_means: dict[str, float] = {}
        self._prior_stds: dict[str, float] = {}
        self._residual_stds: dict[str, float] = {}
        self._player_stats: pd.DataFrame | None = None
        self._use_weather: bool = False
        self._dist_family: str = "legacy"
        self._count_specs: dict[str, CountFamilySpec] = {}
        self._quantile_models: dict[str, dict[float, Any]] = {}
        self._ypc_model: RateModelSpec | None = None

    def _legacy_distribution(self, stat: str, mean: float) -> StatDistribution:
        if stat in self._residual_stds:
            std = max(self._residual_stds[stat], _MIN_MEAN)
        else:
            warnings.warn(
                f"No empirical residual std cached for {stat!r}; "
                "falling back to prior-scaled estimate. "
                "Fit the model before calling predict.",
                DeprecationWarning,
                stacklevel=2,
            )
            prior_mean = self._prior_means.get(stat, 0.0)
            prior_std = self._prior_stds.get(stat, 1.0)
            std = prior_std * (mean / max(prior_mean, _MIN_MEAN))
            std = max(std, _MIN_MEAN)
        return StatDistribution(mean=mean, std=std, dist_type=_DIST_TYPE[stat])

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
        self._ypc_model = None

        rbs = weekly[weekly["position"] == "RB"].copy()
        for col in _WEEKLY_COLS:
            if col not in rbs.columns:
                rbs[col] = 0.0

        rbs, feature_cols = _build_features(rbs, use_weather=use_weather)
        train_rbs = rbs[rbs["season"].isin(years)].copy()
        self._feature_cols = feature_cols

        rbs = rbs.dropna(subset=feature_cols + _TARGET_STATS)
        train_rbs = train_rbs.dropna(subset=feature_cols + _TARGET_STATS)
        self._player_stats = rbs.copy()

        X = train_rbs[feature_cols].values.astype(float)
        X_const = sm.add_constant(X, has_constant="add")

        for stat in _TARGET_STATS:
            y = train_rbs[stat].values.astype(float)
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
            try:
                y_pred_train = np.array(result.predict(X_const)).ravel()
                self._residual_stds[stat] = float(np.std(y_fit - y_pred_train))
            except Exception:
                pass

            if dist_family != "legacy" and stat == "rushing_yards":
                self._quantile_models[stat] = fit_quantile_models(y, X_const)

        if dist_family == "decomposed":
            self._ypc_model = fit_gamma_rate_model(
                train_rbs["rushing_yards"].values.astype(float),
                train_rbs["carries"].values.astype(float),
                X_const,
                l1_alpha=l1_alpha,
                maxiter=500,
            )

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
                "RBModel.predict(opp_team=...) without future_row uses the latest "
                "historical row's opponent context, not the upcoming opponent. "
                "Pass future_row=build_upcoming_row(...) to use upcoming-game context. "
                "This compatibility path will be removed after Phase H.",
                DeprecationWarning,
                stacklevel=2,
            )

        if not self._models or self._player_stats is None:
            for stat in _TARGET_STATS:
                result[stat] = StatDistribution(mean=0.0, std=0.0, dist_type=_DIST_TYPE[stat])
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
                result[stat] = StatDistribution(mean=mean, std=std, dist_type=_DIST_TYPE[stat])
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

            if self._dist_family == "decomposed" and stat == "rushing_yards":
                dist = self._predict_rushing_yards_distribution(
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

    def _predict_rushing_yards_distribution(
        self,
        X_const: np.ndarray,
        mean: float,
        *,
        player_id: str,
        season: int,
        week: int,
    ) -> StatDistribution:
        if self._ypc_model is None or "carries" not in self._count_specs:
            return self._legacy_distribution("rushing_yards", mean)

        carries_result = self._models.get("carries")
        if carries_result is None:
            return self._legacy_distribution("rushing_yards", mean)

        try:
            carries_mean = max(float(carries_result.predict(X_const)[0]), _MIN_MEAN)
        except Exception:
            carries_mean = max(self._prior_means.get("carries", 10.0), _MIN_MEAN)

        carries_dist = make_count_distribution(carries_mean, self._count_specs["carries"])

        try:
            ypc_mean = max(float(self._ypc_model.result.predict(X_const)[0]), _MIN_MEAN)
        except Exception:
            ypc_mean = max(self._ypc_model.mean, _MIN_MEAN)

        raw_mean = max(carries_mean * ypc_mean, _MIN_MEAN)
        scale = mean / raw_mean
        ypc_std = self._ypc_model.std * (ypc_mean / max(self._ypc_model.mean, _MIN_MEAN)) * scale
        return compose_product_distribution(
            carries_dist,
            ypc_mean * scale,
            max(ypc_std, _MIN_MEAN),
            seed_parts=("rb_rushing_yards", player_id, season, week),
            samples=1000,
        )

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @classmethod
    def load(cls, path: Path) -> "RBModel":
        return joblib.load(Path(path))
