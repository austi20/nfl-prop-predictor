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


def test_build_eval_cache_smoke(tmp_path, monkeypatch):
    import eval.fantasy_calibration as fc

    monkeypatch.setattr(fc, "_SAMPLE_PER_POSITION", 3)
    p = fc.build_eval_cache(2025, path=tmp_path / "c.pkl")
    data = fc.load_eval_cache(p)
    assert data["score_year"] == 2025 and 4 <= len(data["rows"]) <= 12
    r = data["rows"][0]
    assert {"anchor", "glm", "factors", "actual_fp"} <= set(r)
    assert isinstance(r["actual_fp"], float)


def test_evaluate_is_per_position_balanced_and_blend_monotone(tmp_path, monkeypatch):
    import eval.fantasy_calibration as fc

    monkeypatch.setattr(fc, "_SAMPLE_PER_POSITION", 40)
    cache = fc.load_eval_cache(fc.build_eval_cache(2025, path=tmp_path / "c.pkl"))
    hi = fc.evaluate(fc.default_calibration(), cache)
    lo = fc.evaluate(fc.default_calibration().replace(glm_blend_weight=0.05), cache)

    # every position is scored, not just WR
    assert set(hi["per_position"]) == {"QB", "RB", "WR", "TE"}
    for pos, m in hi["per_position"].items():
        assert m["n"] >= 10 and isinstance(m["mae"], float)
    for k in ("objective", "mae", "bias_abs", "boom_calib_err", "rank_corr"):
        assert isinstance(hi[k], float)
    # trusting the (over-projecting) GLM less -> less over-ceiling
    assert lo["realism_penalty"] <= hi["realism_penalty"] + 1e-6


def test_fit_glm_correction_covers_every_position():
    import eval.fantasy_calibration as fc

    bias, vinf = fc.fit_glm_correction(fit_years=(2023, 2024), n_per_pos=140)
    prefixes = {k.split("/")[0] for k in bias}
    assert {"QB", "RB", "WR", "TE"} <= prefixes  # correction fit for all four
    for v in bias.values():
        assert 0.6 <= v <= 1.4
    for v in vinf.values():
        assert 0.8 <= v <= 2.5
    # the documented WR receiving-yards over-projection -> bias must not inflate
    assert bias.get("WR/receiving_yards", 1.0) <= 1.05


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


def test_depth_chart_knobs_round_trip_through_dict():
    from eval.fantasy_calibration import _from_dict, default_calibration

    base = default_calibration()
    assert base.strength("depth_chart") == 1.0
    assert base.rookie_cv_inflation == 1.35
    assert base.depth_chart_damping == 0.5

    restored = _from_dict(base.to_dict())
    assert restored.rookie_cv_inflation == base.rookie_cv_inflation
    assert restored.depth_chart_damping == base.depth_chart_damping
    assert restored.strength("depth_chart") == 1.0
