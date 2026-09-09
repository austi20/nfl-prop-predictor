from __future__ import annotations

import pytest
import pandas as pd

from api.schemas import FantasyContextFactor
from api.services.fantasy_service import (
    _coach_factor,
    _game_script_factors,
    _injury_factor,
    _opponent_matchup_factor,
    _rest_factor,
    _rows_before,
    _stat_multipliers,
)
from api.settings import AppSettings


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


def _pos_week_frame() -> pd.DataFrame:
    """RB fantasy production: SF defense soft (allows ~25), league ~15."""
    rows = []
    for wk in range(1, 10):
        rows.append(dict(player_id=f"rb{wk}", position="RB", season=2025, week=wk,
                         recent_team="LAR", opponent_team="SF",
                         rushing_yards=140.0, rushing_tds=1.0, receptions=4.0,
                         receiving_yards=30.0, receiving_tds=0.0))
        rows.append(dict(player_id=f"x{wk}", position="RB", season=2025, week=wk,
                         recent_team="DAL", opponent_team="NYG",
                         rushing_yards=70.0, rushing_tds=0.3, receptions=2.0,
                         receiving_yards=12.0, receiving_tds=0.0))
    return pd.DataFrame(rows)


def test_rows_before_spans_prior_season_for_week_one():
    frame = pd.DataFrame(
        [dict(season=2024, week=w, x=1) for w in range(1, 19)]
        + [dict(season=2025, week=w, x=1) for w in range(1, 19)]
    )
    # Week 1 of 2026 -> everything from 2024+2025 (last 2 seasons)
    got = _rows_before(frame, season=2026, week=1)
    assert set(got["season"]) == {2024, 2025} and len(got) == 36
    # Week 5 of 2025 -> 2024 full + 2025 wk1-4
    got2 = _rows_before(frame, season=2025, week=5)
    assert got2[got2.season == 2025]["week"].max() == 4


def test_opponent_matchup_boosts_vs_soft_defense():
    fac = _opponent_matchup_factor(
        _pos_week_frame(), season=2026, week=1, opponent_team="SF",
        position="RB", scoring_mode="full_ppr",
    )
    assert fac.applied and fac.multiplier > 1.0
    assert "SF allows" in fac.reason


def test_injury_factor_catches_did_not_participate(tmp_path, monkeypatch):
    inj = pd.DataFrame([dict(
        gsis_id="00-0038542", season=2026, week=1,
        report_status=None, practice_status="Did Not Participate In Practice",
    )])
    import api.services.fantasy_service as fs
    fs._read_cached_injuries.cache_clear()
    monkeypatch.setattr(fs, "_read_cached_injuries", lambda *_a: inj)
    fac = _injury_factor(AppSettings(), player_id="00-0038542", season=2026, week=1, position="RB")
    assert fac.applied and fac.multiplier == 0.90 and "did not practice" in fac.reason.lower()


def test_injury_factor_out_is_near_zero(monkeypatch):
    inj = pd.DataFrame([dict(gsis_id="p1", season=2026, week=1, report_status="Out", practice_status="Did Not Participate In Practice")])
    import api.services.fantasy_service as fs
    monkeypatch.setattr(fs, "_read_cached_injuries", lambda *_a: inj)
    fac = _injury_factor(AppSettings(), player_id="p1", season=2026, week=1, position="WR")
    assert fac.multiplier == 0.05


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
    assert mult == 1.22  # 1.12*1.05*1.04*1.03 ~ 1.26 -> clamped

    with_out = stacked + [
        FantasyContextFactor(name="injury_status", label="", multiplier=0.20, applied=True,
                             affected_stats=["rushing_yards"]),
    ]
    assert _stat_multipliers(with_out)["rushing_yards"] == pytest.approx(1.22 * 0.20)  # injury after clamp
