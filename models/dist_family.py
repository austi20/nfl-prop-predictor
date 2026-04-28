"""Helpers for H1.5 stat-family fitting and prediction."""

from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass
from typing import Any

import numpy as np
import statsmodels.api as sm
from scipy import stats

from models.base import StatDistribution
from models.glm_utils import fit_glm_with_optional_regularization

YARDAGE_QUANTILES: tuple[float, ...] = (0.1, 0.25, 0.5, 0.75, 0.9)
_EPS = 1e-6


class ConstantResult:
    """Fallback result that predicts a constant mean and exposes `.aic`."""

    def __init__(self, mean: float) -> None:
        self._mean = float(mean)
        self.aic = float("inf")

    def predict(self, X: Any) -> np.ndarray:
        n = X.shape[0] if hasattr(X, "shape") else 1
        return np.full(n, self._mean, dtype=float)


@dataclass
class CountFamilySpec:
    dist_type: str
    alpha: float = 0.0
    zero_inflation: float = 0.0


@dataclass
class RateModelSpec:
    result: Any
    mean: float
    std: float
    concentration: float = 0.0


def stable_rng(*parts: object) -> np.random.Generator:
    raw = "|".join(str(part) for part in parts).encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    seed = int.from_bytes(digest[:8], "big", signed=False)
    return np.random.default_rng(seed)


def _nbinom_shape_prob(mean: np.ndarray | float, alpha: float) -> tuple[np.ndarray, np.ndarray]:
    mu = np.clip(np.asarray(mean, dtype=float), _EPS, None)
    alpha = max(float(alpha), _EPS)
    shape = np.full_like(mu, 1.0 / alpha, dtype=float)
    prob = shape / (shape + mu)
    return shape, prob


def fit_count_model(
    y: np.ndarray,
    X_const: np.ndarray,
    *,
    l1_alpha: float = 0.0,
    maxiter: int = 500,
) -> tuple[Any, CountFamilySpec]:
    y_fit = np.clip(np.asarray(y, dtype=float), 0.0, None)
    if y_fit.size == 0:
        return ConstantResult(0.0), CountFamilySpec(dist_type="poisson")

    poisson_glm = sm.GLM(y_fit, X_const, family=sm.families.Poisson())
    poisson_result = fit_glm_with_optional_regularization(
        poisson_glm,
        l1_alpha=l1_alpha,
        maxiter=maxiter,
    )
    poisson_mu = np.clip(np.asarray(poisson_result.predict(X_const), dtype=float), _EPS, None)
    df_resid = float(getattr(poisson_result, "df_resid", max(len(y_fit) - X_const.shape[1], 1)))
    pearson = float(np.sum(((y_fit - poisson_mu) ** 2) / poisson_mu))
    dispersion = pearson / max(df_resid, 1.0)
    use_poisson = np.isfinite(dispersion) and abs(dispersion - 1.0) <= 0.1

    if use_poisson:
        result = poisson_result
        spec = CountFamilySpec(dist_type="poisson")
        expected_zero = float(np.mean(stats.poisson.pmf(0, poisson_mu)))
    else:
        mean_y = float(np.mean(y_fit))
        var_y = float(np.var(y_fit))
        alpha = max((var_y - mean_y) / max(mean_y**2, _EPS), _EPS)
        nb_glm = sm.GLM(
            y_fit,
            X_const,
            family=sm.families.NegativeBinomial(alpha=alpha),
        )
        result = fit_glm_with_optional_regularization(
            nb_glm,
            l1_alpha=l1_alpha,
            maxiter=maxiter,
        )
        nb_mu = np.clip(np.asarray(result.predict(X_const), dtype=float), _EPS, None)
        observed_ceiling = max(float(np.quantile(y_fit, 0.99)) * 10.0, mean_y * 20.0, 10.0)
        if (not np.all(np.isfinite(nb_mu))) or float(np.max(nb_mu)) > observed_ceiling:
            # NegBin GLM can become numerically explosive on sparse football counts.
            # Keep the over-dispersed family, but fall back to the stable Poisson mean fit.
            result = poisson_result
            nb_mu = poisson_mu
        shape, prob = _nbinom_shape_prob(nb_mu, alpha)
        spec = CountFamilySpec(dist_type="negative_binomial", alpha=alpha)
        expected_zero = float(np.mean(stats.nbinom.pmf(0, shape, prob)))

    observed_zero = float(np.mean(y_fit <= 0.0))
    if observed_zero > expected_zero * 1.2:
        zero_inflation = float(
            np.clip(
                (observed_zero - expected_zero) / max(1.0 - expected_zero, _EPS),
                0.0,
                0.95,
            )
        )
        spec.dist_type = f"zero_inflated_{spec.dist_type}"
        spec.zero_inflation = zero_inflation

    return result, spec


def make_count_distribution(mean: float, spec: CountFamilySpec) -> StatDistribution:
    mean = max(float(mean), 0.0)
    if mean <= 0.0:
        return StatDistribution(mean=0.0, std=0.0, dist_type=spec.dist_type, params={"alpha": spec.alpha})

    keep_weight = 1.0 - float(np.clip(spec.zero_inflation, 0.0, 0.999))
    component_mean = mean / max(keep_weight, _EPS)
    if "negative_binomial" in spec.dist_type:
        base_var = component_mean + spec.alpha * (component_mean**2)
    else:
        base_var = component_mean
    overall_var = keep_weight * base_var + keep_weight * (1.0 - keep_weight) * (component_mean**2)
    return StatDistribution(
        mean=mean,
        std=float(np.sqrt(max(overall_var, _EPS))),
        dist_type=spec.dist_type,
        params={
            "alpha": float(spec.alpha),
            "zero_inflation": float(spec.zero_inflation),
            "component_mean": float(component_mean),
        },
    )


def fit_quantile_models(
    y: np.ndarray,
    X_const: np.ndarray,
    *,
    quantiles: tuple[float, ...] = YARDAGE_QUANTILES,
) -> dict[float, Any]:
    y_fit = np.asarray(y, dtype=float)
    if y_fit.size == 0:
        return {}

    models: dict[float, Any] = {}
    quant_reg = sm.QuantReg(y_fit, X_const)
    for q in quantiles:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                models[q] = quant_reg.fit(q=q, max_iter=1000)
        except Exception:
            continue
    return models


def predict_quantiles(models: dict[float, Any], X_const: np.ndarray) -> dict[float, float]:
    predicted: dict[float, float] = {}
    for q, result in sorted(models.items()):
        try:
            predicted[float(q)] = max(float(result.predict(X_const)[0]), 0.0)
        except Exception:
            continue
    if not predicted:
        return {}

    sorted_items = sorted(predicted.items())
    running_max = 0.0
    monotone: dict[float, float] = {}
    for q, value in sorted_items:
        running_max = max(running_max, value)
        monotone[q] = running_max
    return monotone


def make_quantile_distribution(
    mean: float,
    std: float,
    quantiles: dict[float, float],
) -> StatDistribution:
    if not quantiles:
        return StatDistribution(mean=float(mean), std=float(std), dist_type="gamma")

    q10 = float(quantiles.get(0.1, mean))
    q90 = float(quantiles.get(0.9, mean))
    inferred_std = max(float(std), float((q90 - q10) / 2.56), _EPS)
    return StatDistribution(
        mean=float(mean),
        std=inferred_std,
        dist_type="quantile",
        quantiles={float(q): float(v) for q, v in quantiles.items()},
    )


def fit_gamma_rate_model(
    y: np.ndarray,
    opportunities: np.ndarray,
    X_const: np.ndarray,
    *,
    l1_alpha: float = 0.0,
    maxiter: int = 500,
) -> RateModelSpec:
    y_arr = np.asarray(y, dtype=float)
    opp = np.asarray(opportunities, dtype=float)
    mask = opp > 0
    if not np.any(mask):
        return RateModelSpec(result=ConstantResult(0.0), mean=0.0, std=1.0)

    rate = np.clip(y_arr[mask] / np.clip(opp[mask], 1.0, None), _EPS, None)
    X_rate = X_const[mask]
    glm = sm.GLM(
        rate,
        X_rate,
        family=sm.families.Gamma(sm.families.links.Log()),
    )
    result = fit_glm_with_optional_regularization(
        glm,
        l1_alpha=l1_alpha,
        maxiter=maxiter,
    )
    return RateModelSpec(
        result=result,
        mean=float(rate.mean()),
        std=float(max(rate.std(ddof=0), _EPS)),
    )


def fit_beta_rate_model(
    successes: np.ndarray,
    trials: np.ndarray,
    X_const: np.ndarray,
    *,
    maxiter: int = 500,
) -> RateModelSpec:
    successes_arr = np.asarray(successes, dtype=float)
    trials_arr = np.asarray(trials, dtype=float)
    mask = trials_arr > 0
    if not np.any(mask):
        return RateModelSpec(result=ConstantResult(0.5), mean=0.5, std=0.1, concentration=20.0)

    clipped_trials = np.clip(trials_arr[mask], 1.0, None)
    rate = np.clip(successes_arr[mask] / clipped_trials, 1e-4, 1.0 - 1e-4)
    glm = sm.GLM(
        rate,
        X_const[mask],
        family=sm.families.Binomial(),
        var_weights=clipped_trials,
    )
    result = glm.fit(maxiter=maxiter)

    mean_rate = float(rate.mean())
    var_rate = float(rate.var(ddof=0))
    max_var = max(mean_rate * (1.0 - mean_rate), _EPS)
    concentration = max((max_var / max(var_rate, _EPS)) - 1.0, 2.0)
    return RateModelSpec(
        result=result,
        mean=mean_rate,
        std=float(np.sqrt(max(var_rate, _EPS))),
        concentration=float(concentration),
    )


def compose_receptions_distribution(
    target_distribution: StatDistribution,
    catch_rate_mean: float,
    concentration: float,
    *,
    seed_parts: tuple[object, ...],
    samples: int = 1000,
) -> StatDistribution:
    rng = stable_rng(*seed_parts)
    target_draws = np.rint(target_distribution.sample(rng, samples)).astype(int)
    target_draws = np.clip(target_draws, 0, None)

    catch_rate_mean = float(np.clip(catch_rate_mean, 1e-4, 1.0 - 1e-4))
    concentration = max(float(concentration), 2.0)
    alpha = catch_rate_mean * concentration
    beta = max((1.0 - catch_rate_mean) * concentration, 1e-4)
    catch_draws = rng.beta(alpha, beta, size=samples)
    receptions = rng.binomial(target_draws, np.clip(catch_draws, 1e-6, 1.0 - 1e-6))
    return StatDistribution.from_samples(receptions.astype(float))


def compose_product_distribution(
    count_distribution: StatDistribution,
    rate_mean: float,
    rate_std: float,
    *,
    seed_parts: tuple[object, ...],
    samples: int = 1000,
) -> StatDistribution:
    rng = stable_rng(*seed_parts)
    count_draws = np.clip(count_distribution.sample(rng, samples), 0.0, None)
    rate_mean = max(float(rate_mean), _EPS)
    rate_std = max(float(rate_std), _EPS)
    shape = max((rate_mean / rate_std) ** 2, _EPS)
    scale = max((rate_std**2) / rate_mean, _EPS)
    rate_draws = rng.gamma(shape=shape, scale=scale, size=samples)
    return StatDistribution.from_samples((count_draws * rate_draws).astype(float))
