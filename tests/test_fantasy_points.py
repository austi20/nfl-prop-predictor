from __future__ import annotations

import numpy as np

from api.services.fantasy_service import _weather_factor
from eval.fantasy_points import (
    position_cutoffs,
    project_fantasy_points,
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
        position="QB",
        scoring_mode="full_ppr",
        simulations=0,
    )

    assert projection.projected_points == 36.0
    assert projection.boom_cutoff == 24.0
    assert projection.bust_cutoff == 14.0


def test_half_ppr_keeps_same_interface_with_lower_reception_weight():
    full = project_fantasy_points(
        {"receptions": _dist(6.0), "receiving_yards": _dist(60.0)},
        position="WR",
        scoring_mode="full_ppr",
        simulations=0,
    )
    half = project_fantasy_points(
        {"receptions": _dist(6.0), "receiving_yards": _dist(60.0)},
        position="WR",
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

    first = project_fantasy_points(distributions, position="RB", seed=seed)
    second = project_fantasy_points(distributions, position="RB", seed=seed)

    assert np.isclose(first.boom_probability, second.boom_probability)
    assert np.isclose(first.bust_probability, second.bust_probability)
    assert np.isclose(first.median_points, second.median_points)


def test_position_cutoffs_for_supported_positions():
    assert position_cutoffs("QB") == (24.0, 14.0)
    assert position_cutoffs("RB") == (20.0, 8.0)
    assert position_cutoffs("WR") == (20.0, 7.0)
    assert position_cutoffs("TE") == (14.0, 5.0)


def test_weather_factor_defaults_neutral_without_weather_feed():
    factor = _weather_factor(recent_team="KC", opponent_team="DEN", position="QB")

    assert factor.name == "weather"
    assert factor.applied is False
    assert factor.multiplier == 1.0
    assert "neutral" in factor.reason.lower()
