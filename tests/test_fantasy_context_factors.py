from __future__ import annotations

from api.schemas import FantasyContextFactor
from api.services.fantasy_service import (
    _coach_factor,
    _game_script_factors,
    _rest_factor,
    _stat_multipliers,
)


def _by_name(factors: list[FantasyContextFactor]) -> dict[str, FantasyContextFactor]:
    return {f.name: f for f in factors}


def test_game_script_no_line_is_neutral():
    out = _game_script_factors(None, position="RB")
    assert len(out) == 1 and out[0].name == "game_environment" and not out[0].applied


def test_high_total_favourite_boosts_volume_and_run():
    ctx = {"team_implied": 28.25, "team_spread": -7.0}
    fx = _by_name(_game_script_factors(ctx, position="RB"))
    assert fx["game_environment"].multiplier > 1.0 and fx["game_environment"].applied
    assert fx["game_script_run"].multiplier > 1.0
    assert fx["game_script_pass"].multiplier < 1.0
    assert "receptions" in fx["game_script_pass"].affected_stats
    assert "rushing_yards" in fx["game_script_run"].affected_stats


def test_low_total_underdog_trims_volume_and_flips_script():
    ctx = {"team_implied": 17.0, "team_spread": 6.5}
    fx = _by_name(_game_script_factors(ctx, position="WR"))
    assert fx["game_environment"].multiplier < 1.0
    assert fx["game_script_pass"].multiplier > 1.0  # chasing points
    assert fx["game_script_run"].multiplier < 1.0


def test_small_spread_has_no_script_tilt():
    ctx = {"team_implied": 23.0, "team_spread": -1.5}
    names = {f.name for f in _game_script_factors(ctx, position="RB")}
    assert names == {"game_environment"}


def test_coach_factor_neutral_near_average_outlier_moves():
    positive = ["rushing_yards"]
    near_avg = _coach_factor({"coach": "Mid Guy"}, {"Mid Guy": (23.0, 60)}, position="RB")
    assert not near_avg.applied
    elite = _coach_factor({"coach": "Bruce Arians"}, {"Bruce Arians": (29.8, 49)}, position="RB")
    assert elite.applied and 1.0 < elite.multiplier <= 1.05
    thin = _coach_factor({"coach": "Rook"}, {"Rook": (30.0, 4)}, position="RB")
    assert not thin.applied  # < 16 games


def test_rest_factor_bye_and_short_week():
    assert _rest_factor({"rest": 13.0}, position="RB").multiplier > 1.0
    assert _rest_factor({"rest": 4.0}, position="RB").multiplier < 1.0
    assert not _rest_factor({"rest": 7.0}, position="RB").applied
    assert not _rest_factor({"rest": None}, position="RB").applied


def test_stat_multiplier_product_is_clamped_but_injury_escapes():
    stacked = [
        FantasyContextFactor(name="game_environment", label="", multiplier=1.12, applied=True,
                             affected_stats=["rushing_yards"]),
        FantasyContextFactor(name="coaching", label="", multiplier=1.05, applied=True,
                             affected_stats=["rushing_yards"]),
        FantasyContextFactor(name="game_script_run", label="", multiplier=1.04, applied=True,
                             affected_stats=["rushing_yards"]),
        FantasyContextFactor(name="position_group_form", label="", multiplier=1.03, applied=True,
                             affected_stats=["rushing_yards"]),
    ]
    mult = _stat_multipliers(stacked)["rushing_yards"]
    assert mult == 1.25  # 1.12*1.05*1.04*1.03 ~ 1.26 -> clamped to 1.25

    with_out = stacked + [
        FantasyContextFactor(name="injury_status", label="", multiplier=0.20, applied=True,
                             affected_stats=["rushing_yards"]),
    ]
    assert _stat_multipliers(with_out)["rushing_yards"] == 1.25 * 0.20  # injury applied after clamp
