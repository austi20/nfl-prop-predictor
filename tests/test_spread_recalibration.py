"""Unit tests for models.dist_family.residual_cv and recalibrate_spread.

Both were added in v0.9-m3.1 for the future_row-gated spread calibration and had
no direct coverage. These lock the contract for each of the four distribution
representations recalibrate_spread handles.
"""
from __future__ import annotations

import numpy as np
import pytest

from models.base import StatDistribution
from models.dist_family import recalibrate_spread, residual_cv


# ---------------------------------------------------------------------------
# residual_cv
# ---------------------------------------------------------------------------


def test_residual_cv_returns_zero_below_20_samples():
    a = np.arange(19, dtype=float)
    p = a + 1.0
    assert residual_cv(a, p) == 0.0


def test_residual_cv_matches_known_spread():
    rng = np.random.default_rng(0)
    pred = np.full(2000, 50.0)
    actual = pred + rng.normal(0.0, 10.0, size=pred.size)
    cv = residual_cv(actual, pred)
    # resid std ~10, mean pred 50 -> cv ~0.2
    assert cv == pytest.approx(0.2, abs=0.03)


def test_residual_cv_is_clipped_to_bounds():
    # Huge residuals -> clipped at 3.0
    a = np.concatenate([np.zeros(50), np.full(50, 1000.0)])
    p = np.full(100, 1.0)
    assert residual_cv(a, p) == 3.0
    # Zero residuals -> clipped up to 0.05
    a2 = np.full(100, 7.0)
    p2 = np.full(100, 7.0)
    assert residual_cv(a2, p2) == 0.05


def test_residual_cv_ignores_non_finite():
    a = np.array([1.0, 2.0, np.nan, 4.0] * 10, dtype=float)
    p = np.array([1.0, np.inf, 3.0, 4.0] * 10, dtype=float)
    cv = residual_cv(a, p)
    assert np.isfinite(cv)
    assert 0.05 <= cv <= 3.0


# ---------------------------------------------------------------------------
# recalibrate_spread - early return
# ---------------------------------------------------------------------------


def test_recalibrate_spread_noop_when_close():
    d = StatDistribution(mean=100.0, std=25.0, dist_type="gamma")
    out = recalibrate_spread(d, 25.5)  # <5% change
    assert out is d


# ---------------------------------------------------------------------------
# recalibrate_spread - empirical samples representation
# ---------------------------------------------------------------------------


def test_recalibrate_spread_samples_hits_target_std():
    rng = np.random.default_rng(1)
    samples = rng.gamma(shape=(300.0 / 90.0) ** 2, scale=90.0**2 / 300.0, size=4000)
    d = StatDistribution.from_samples(samples, dist_type="empirical")
    target = 120.0
    out = recalibrate_spread(d, target)
    assert out.std == pytest.approx(target, rel=0.05)
    assert out.mean == pytest.approx(d.mean, rel=0.02)
    assert min(out.samples) >= 0.0


def test_recalibrate_spread_samples_can_shrink():
    rng = np.random.default_rng(2)
    samples = rng.normal(200.0, 80.0, size=4000).clip(0.0)
    d = StatDistribution.from_samples(samples, dist_type="empirical")
    out = recalibrate_spread(d, 40.0)
    assert out.std == pytest.approx(40.0, rel=0.08)


# ---------------------------------------------------------------------------
# recalibrate_spread - quantile-knot representation
# ---------------------------------------------------------------------------


def test_recalibrate_spread_quantile_preserves_monotonicity():
    d = StatDistribution(
        mean=100.0,
        std=20.0,
        dist_type="quantile",
        quantiles={0.1: 70.0, 0.25: 85.0, 0.5: 100.0, 0.75: 115.0, 0.9: 130.0},
    )
    out = recalibrate_spread(d, 60.0)  # 3x widen
    knots = [out.quantiles[q] for q in sorted(out.quantiles)]
    assert all(b >= a for a, b in zip(knots, knots[1:])), knots
    assert out.std == pytest.approx(60.0)
    # median knot unchanged (rescale pivots on it)
    assert out.quantiles[0.5] == pytest.approx(100.0)


def test_recalibrate_spread_quantile_monotone_under_extreme_factor():
    d = StatDistribution(
        mean=10.0,
        std=8.0,
        dist_type="quantile",
        quantiles={0.1: 1.0, 0.25: 3.0, 0.5: 6.0, 0.75: 12.0, 0.9: 25.0},
    )
    out = recalibrate_spread(d, 0.5)  # heavy shrink -> knots collapse toward median
    knots = [out.quantiles[q] for q in sorted(out.quantiles)]
    assert all(b >= a for a, b in zip(knots, knots[1:])), knots


# ---------------------------------------------------------------------------
# recalibrate_spread - count-family representation
# ---------------------------------------------------------------------------


def test_recalibrate_spread_count_matches_target_variance_negbin():
    d = StatDistribution(
        mean=6.0, std=5.0, dist_type="negative_binomial", params={"alpha": 0.5}
    )
    target = 3.6
    out = recalibrate_spread(d, target)
    assert out.dist_type == "negative_binomial"
    alpha = out.params["alpha"]
    # NB variance in this parameterisation: mean + alpha*mean^2
    assert 6.0 + alpha * 36.0 == pytest.approx(target**2, rel=0.02)
    assert 0.0 <= out.prob_over(6.0) <= 1.0


def test_recalibrate_spread_count_collapses_to_poisson_when_underdispersed():
    d = StatDistribution(
        mean=4.0, std=5.0, dist_type="negative_binomial", params={"alpha": 1.0}
    )
    out = recalibrate_spread(d, 2.0)  # target var 4 == mean -> Poisson
    assert out.dist_type == "poisson"
    assert out.std == pytest.approx(2.0, rel=0.01)


def test_recalibrate_spread_count_drops_zero_inflation():
    # Documented tradeoff: ZINB is rebuilt as plain NB/Poisson (moment-matched),
    # losing the explicit zero point-mass.
    d = StatDistribution(
        mean=3.0,
        std=4.0,
        dist_type="zero_inflated_negative_binomial",
        params={"alpha": 0.8, "zero_inflation": 0.3, "component_mean": 4.3},
    )
    out = recalibrate_spread(d, 2.4)
    assert out.dist_type in {"negative_binomial", "poisson"}
    assert "zero_inflation" not in out.params


# ---------------------------------------------------------------------------
# recalibrate_spread - plain gamma/tweedie/normal fallback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dist_type", ["gamma", "tweedie", "normal"])
def test_recalibrate_spread_plain_sets_std_keeps_shape(dist_type):
    d = StatDistribution(mean=80.0, std=30.0, dist_type=dist_type, params={"k": 1})
    out = recalibrate_spread(d, 12.0)
    assert out.dist_type == dist_type
    assert out.std == pytest.approx(12.0)
    assert out.mean == pytest.approx(80.0)
