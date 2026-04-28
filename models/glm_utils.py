"""Helpers for statsmodels GLM fits shared across position models."""

from __future__ import annotations

from typing import Any

import numpy as np
import statsmodels.api as sm


class RegularizedResultProxy:
    """Wrap a regularized fit with metadata expected by downstream code."""

    def __init__(self, wrapped: Any, *, aic: float) -> None:
        self._wrapped = wrapped
        self.aic = float(aic)

    def predict(self, X: Any) -> np.ndarray:
        return self._wrapped.predict(X)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)


def regularized_aic(glm: sm.GLM, params: np.ndarray, *, tol: float = 1e-8) -> float:
    """Return a simple active-set AIC proxy for a regularized GLM fit."""
    try:
        params = np.asarray(params, dtype=float)
        llf = float(glm.loglike(params))
        if not np.isfinite(llf):
            return float("inf")
        active_k = max(int(np.count_nonzero(np.abs(params) > tol)), 1)
        return float((2.0 * active_k) - (2.0 * llf))
    except Exception:
        return float("inf")


def fit_glm_with_optional_regularization(
    glm: sm.GLM,
    *,
    l1_alpha: float,
    maxiter: int = 500,
) -> Any:
    """Fit a GLM and preserve `.aic` even on the regularized path."""
    if l1_alpha <= 0.0:
        return glm.fit(maxiter=maxiter)

    result = glm.fit_regularized(
        alpha=l1_alpha,
        L1_wt=1.0,
        maxiter=maxiter,
        refit=True,
    )
    if hasattr(result, "aic"):
        return result
    return RegularizedResultProxy(
        result,
        aic=regularized_aic(glm, np.asarray(result.params, dtype=float)),
    )
