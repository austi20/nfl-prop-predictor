from __future__ import annotations

import numpy as np

from api.services.fantasy_service import _weather_factors
from eval.fantasy_points import (
    BOOM_MULTIPLIER,
    BUST_MULTIPLIER,
    project_fantasy_points,
    relative_cutoffs,
    stable_simulation_seed,
)
from models.base import StatDistribution


def _dist(mean: float, std: float = 1.0, dist_type: str = "normal") -> StatDistribution:
    return StatDistribution(mean=mean, std=std, dist_type=dist_type)


def test_full_ppr_scoring_from_component_means():
    projection = project_fantasy_points(
        {
            "passing_yards": _dist(250.0),
            "passing_tds": _dist(2.0),
            "interceptions": _dist(1.0),
            "rushing_yards": _dist(20.0),
            "rushing_tds": _dist(0.5),
            "receptions": _dist(5.0),
            "receiving_yards": _dist(70.0),
            "receiving_tds": _dist(0.5),
        },
        scoring_mode="full_ppr",
        simulations=0,
    )

    assert projection.projected_points == 36.0
    assert projection.boom_cutoff == 36.0 * 1.5
    assert projection.bust_cutoff == 36.0 * 0.5


def test_half_ppr_keeps_same_interface_with_lower_reception_weight():
    full = project_fantasy_points(
        {"receptions": _dist(6.0), "receiving_yards": _dist(60.0)},
        scoring_mode="full_ppr",
        simulations=0,
    )
    half = project_fantasy_points(
        {"receptions": _dist(6.0), "receiving_yards": _dist(60.0)},
        scoring_mode="half_ppr",
        simulations=0,
    )

    assert full.projected_points == 12.0
    assert half.projected_points == 9.0


def test_boom_bust_probabilities_are_deterministic_for_same_seed():
    distributions = {
        "rushing_yards": _dist(80.0, 18.0, "gamma"),
        "rushing_tds": _dist(0.6, 0.8, "poisson"),
        "receptions": _dist(3.0, 1.5, "poisson"),
        "receiving_yards": _dist(24.0, 10.0, "gamma"),
    }
    seed = stable_simulation_seed("rb1", 2024, 10, "full_ppr")

    first = project_fantasy_points(distributions, seed=seed)
    second = project_fantasy_points(distributions, seed=seed)

    assert np.isclose(first.boom_probability, second.boom_probability)
    assert np.isclose(first.bust_probability, second.bust_probability)
    assert np.isclose(first.median_points, second.median_points)


def test_relative_cutoffs_scale_with_the_projection():
    assert relative_cutoffs(20.0) == (20.0 * BOOM_MULTIPLIER, 20.0 * BUST_MULTIPLIER)
    assert relative_cutoffs(0.0) == (0.0, 0.0)
    assert relative_cutoffs(-1.0) == (0.0, 0.0)


def _wr() -> dict[str, StatDistribution]:
    return {
        "receptions": _dist(5.0, 2.5, "poisson"),
        "receiving_yards": _dist(65.0, 30.0, "gamma"),
        "receiving_tds": _dist(0.4, 0.6, "poisson"),
    }


def test_boom_and_bust_are_the_sample_share_past_each_cutoff():
    projection = project_fantasy_points(_wr(), seed=7, simulations=20000)
    boom_cut, bust_cut = relative_cutoffs(projection.projected_points)
    assert projection.boom_cutoff == boom_cut
    assert projection.bust_cutoff == bust_cut
    assert 0.05 < projection.boom_probability < 0.5
    assert 0.05 < projection.bust_probability < 0.5


def test_a_wider_spread_raises_both_boom_and_bust_at_the_same_projection():
    steady = project_fantasy_points(_wr(), seed=7, simulations=20000, total_sd=4.0)
    volatile = project_fantasy_points(_wr(), seed=7, simulations=20000, total_sd=9.0)
    assert steady.projected_points == volatile.projected_points
    assert volatile.boom_probability > steady.boom_probability
    assert volatile.bust_probability > steady.bust_probability


def test_half_ppr_cutoffs_follow_the_half_ppr_projection():
    half = project_fantasy_points(_wr(), scoring_mode="half_ppr", simulations=0)
    assert half.boom_cutoff == half.projected_points * BOOM_MULTIPLIER


def test_a_zero_projection_never_booms():
    projection = project_fantasy_points({}, seed=1)
    assert projection.boom_probability == 0.0
    assert projection.bust_probability == 1.0


def test_weather_factors_neutral_without_a_game_id():
    factors = _weather_factors(
        game_id="", recent_team="KC", opponent_team="DEN", position="QB"
    )

    assert len(factors) == 1
    assert factors[0].name == "weather"
    assert factors[0].applied is False
    assert factors[0].multiplier == 1.0
