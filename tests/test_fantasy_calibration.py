from __future__ import annotations

import json

from eval.fantasy_calibration import (
    FantasyCalibration,
    default_calibration,
    load_calibration,
    save_calibration,
)


def test_default_calibration_matches_todays_constants():
    c = default_calibration()
    assert c.glm_blend_weight == 0.35
    assert (c.stat_mean_lo, c.stat_mean_hi) == (0.45, 1.7)
    assert (c.yard_cv, c.count_cv) == (0.55, 0.85)
    assert c.cv_floor_frac == 0.0  # no-op at default -> spread == today
    assert (c.context_clamp_lo, c.context_clamp_hi) == (0.78, 1.22)
    assert c.offense_stack_cap >= 1.22  # no-op at the default
    for f in (
        "game_environment", "coaching", "opponent_matchup", "usage_trend", "rest",
        "news", "qb_support", "position_group_form", "weather", "game_script",
    ):
        assert c.factor_strength[f] == 1.0
    assert c.glm_bias == {} and c.glm_var_inflation == {}


def test_round_trip_json(tmp_path):
    base = default_calibration()
    c = base.replace(
        glm_blend_weight=0.2,
        factor_strength={**base.factor_strength, "coaching": 0.0},
    )
    p = tmp_path / "cal.json"
    save_calibration(c, p)
    back = load_calibration(p)
    assert back == c
    assert json.loads(p.read_text())["glm_blend_weight"] == 0.2


def test_load_missing_file_returns_default(tmp_path):
    assert load_calibration(tmp_path / "nope.json") == default_calibration()


def test_default_calibration_reproduces_current_projection():
    """A player projected under the built-in default must land where it did
    before the calibration refactor (Bijan 2026 W1 was 17.9)."""
    from api.settings import AppSettings
    from api.services.fantasy_service import build_fantasy_summary

    s = AppSettings(default_train_years=tuple(range(2015, 2024)), prewarm_fantasy_slate=False)
    fs = build_fantasy_summary(
        s, player_id="00-0038542", season=2026, week=1, position="RB",
        recent_team="ATL", opponent_team="PIT", game_id="2026_01_ATL_PIT",
        scoring_mode="full_ppr",
    )
    assert 16.5 <= fs.projected_points <= 19.0
