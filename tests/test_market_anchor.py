import pytest

import api.services.fantasy_service as fs
from api.services.market_lines import market_quote
from eval.fantasy_calibration import default_calibration
from models.base import StatDistribution


def _dist(mean: float, std: float, dist_type: str = "gamma") -> StatDistribution:
    return StatDistribution(mean=mean, std=std, dist_type=dist_type)


def test_scale_to_market_matches_the_priced_probability():
    """The market states P(stat >= strike). The solved scale must reproduce it."""
    dist = _dist(250.0, 70.0)
    strike, target = 224.5, 0.48

    scale = fs._scale_to_market(dist, strike, target, 0.6, 1.6)
    scaled = _dist(dist.mean * scale, dist.std * scale)

    assert scaled.prob_over(strike) == pytest.approx(target, abs=0.01)


def test_scale_to_market_is_bounded_by_the_band():
    """A market wildly at odds with the model cannot escape the clamp."""
    dist = _dist(250.0, 70.0)
    # Market says 25 yards is a coin flip; the model is enormously higher.
    assert fs._scale_to_market(dist, 25.0, 0.5, 0.6, 1.6) == 0.6
    # ...and the reverse.
    assert fs._scale_to_market(dist, 900.0, 0.5, 0.6, 1.6) == 1.6


def test_scale_is_identity_when_model_already_agrees():
    dist = _dist(100.0, 30.0)
    strike = 100.0
    target = dist.prob_over(strike)
    assert fs._scale_to_market(dist, strike, target, 0.6, 1.6) == pytest.approx(1.0, abs=0.01)


def test_market_factor_built_from_a_quote():
    calib = default_calibration()
    factors = fs._market_factors(
        {"passing_yards": _dist(250.0, 70.0)},
        {"P1|passing_yards": [224.5, 0.48]},
        player_id="P1",
        position="QB",
        calib=calib,
    )
    assert len(factors) == 1
    factor = factors[0]
    assert factor.name == "market"
    assert factor.affected_stats == ["passing_yards"]
    assert factor.applied
    assert calib.market_clamp_lo <= factor.multiplier <= calib.market_clamp_hi
    assert "224.5+" in factor.reason


def test_market_factor_skipped_for_a_lopsided_quote():
    """Near 0 or 1 the strike carries no line information."""
    assert fs._market_factors(
        {"passing_yards": _dist(250.0, 70.0)},
        {"P1|passing_yards": [400.0, 0.005]},
        player_id="P1",
        position="QB",
        calib=default_calibration(),
    ) == []


def test_no_quote_produces_no_factor():
    assert fs._market_factors(
        {"passing_yards": _dist(250.0, 70.0)},
        {},
        player_id="P1",
        position="QB",
        calib=default_calibration(),
    ) == []


# --- precedence -------------------------------------------------------------


def _factor(name, multiplier, applied, stats):
    return fs.FantasyContextFactor(
        name=name, label=name, multiplier=multiplier, applied=applied,
        affected_stats=list(stats), reason="x",
    )


def test_market_supersedes_depth_chart_on_the_stats_it_prices():
    resolved = fs._resolve_role_precedence([
        _factor("market", 1.2, True, ["rushing_yards"]),
        _factor("depth_chart", 1.15, True, ["rushing_yards", "receptions"]),
    ])
    depth = next(f for f in resolved if f.name == "depth_chart")
    assert depth.affected_stats == ["receptions"], "priced stat stripped, rest kept"


def test_depth_chart_fully_superseded_when_market_prices_everything():
    resolved = fs._resolve_role_precedence([
        _factor("market", 1.2, True, ["rushing_yards"]),
        _factor("depth_chart", 1.15, True, ["rushing_yards"]),
    ])
    depth = next(f for f in resolved if f.name == "depth_chart")
    assert not depth.applied
    assert "market" in depth.reason


def test_usage_trend_yields_to_both_tiers():
    resolved = fs._resolve_role_precedence([
        _factor("market", 1.2, True, ["rushing_yards"]),
        _factor("usage_trend", 1.1, True, ["rushing_yards"]),
    ])
    usage = next(f for f in resolved if f.name == "usage_trend")
    assert not usage.applied


def test_market_bypasses_the_context_clamp():
    """The context clamp is +/-22%; a market statement gets its own wider band."""
    calib = default_calibration()
    out = fs._stat_multipliers(
        [_factor("market", 1.45, True, ["rushing_yards"])], calib
    )
    assert out["rushing_yards"] == pytest.approx(1.45, abs=1e-6)
    assert out["rushing_yards"] > calib.context_clamp_hi


def test_market_is_still_bounded_by_its_own_band():
    calib = default_calibration()
    out = fs._stat_multipliers(
        [_factor("market", 9.0, True, ["rushing_yards"])], calib
    )
    assert out["rushing_yards"] == pytest.approx(calib.market_clamp_hi)


def test_market_quote_rejects_a_malformed_cache_entry():
    assert market_quote({"P1|rushing_yards": 62.5}, "P1", "rushing_yards") is None
    assert market_quote({"P1|rushing_yards": []}, "P1", "rushing_yards") is None
    assert market_quote({}, "P1", "rushing_yards") is None
    assert market_quote(
        {"P1|rushing_yards": [62.0, 0.5]}, "P1", "rushing_yards"
    ) == (62.0, 0.5)
