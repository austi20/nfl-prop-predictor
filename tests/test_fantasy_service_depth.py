import pandas as pd

import api.services.fantasy_service as fs


def _weekly() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "player_id": ["A", "B", "C", "D"],
            "season": [2025] * 4,
            "week": [1] * 4,
            "position": ["RB"] * 4,
            "rushing_yards": [100.0, 90.0, 20.0, 10.0],
            "rushing_tds": [1.0, 1.0, 0.0, 0.0],
            "receptions": [3.0, 2.0, 1.0, 0.0],
            "receiving_yards": [30.0, 20.0, 5.0, 0.0],
            "receiving_tds": [0.0, 0.0, 0.0, 0.0],
        }
    )


def _ranks() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "gsis_id": ["A", "B", "C", "D"],
            "season": [2025] * 4,
            "week": [1] * 4,
            "team": ["X"] * 4,
            "position": ["RB"] * 4,
            "rank": [1, 1, 3, 3],
        }
    )


def test_rank_conditioned_baseline_separates_rb1_from_rb3(monkeypatch):
    monkeypatch.setattr(fs, "_rank_lookup", lambda weekly: _ranks())
    fs._BASELINE_CACHE.clear()

    baselines = fs._baselines_for(_weekly())

    assert baselines[("RB", 1, "rushing_yards")] == 95.0
    assert baselines[("RB", 3, "rushing_yards")] == 15.0
    assert baselines[("RB", None, "rushing_yards")] == 55.0


def test_baseline_falls_back_to_position_wide_when_ranks_missing(monkeypatch):
    monkeypatch.setattr(fs, "_rank_lookup", lambda weekly: pd.DataFrame())
    fs._BASELINE_CACHE.clear()

    baselines = fs._baselines_for(_weekly())

    assert baselines[("RB", None, "rushing_yards")] == 55.0
    assert fs._baseline(baselines, "RB", 1, "rushing_yards") == 55.0


def test_baseline_lookup_prefers_exact_bucket():
    baselines = {("RB", 1, "rushing_yards"): 95.0, ("RB", None, "rushing_yards"): 55.0}
    assert fs._baseline(baselines, "RB", 1, "rushing_yards") == 95.0
    assert fs._baseline(baselines, "RB", None, "rushing_yards") == 55.0
    assert fs._baseline(baselines, "RB", 2, "rushing_yards") == 55.0
    assert fs._baseline(baselines, "QB", 1, "passing_yards") == 0.0


def test_promoted_player_regresses_toward_the_new_role(monkeypatch):
    """Same trailing games, different depth rank -> higher projection."""
    monkeypatch.setattr(fs, "_rank_lookup", lambda weekly: _ranks())
    fs._BASELINE_CACHE.clear()

    weekly = pd.concat([_weekly(), _weekly().assign(week=2)], ignore_index=True)

    def project(depth_rank):
        return fs._trailing_fantasy_distributions(
            weekly,
            player_id="C",
            season=2026,
            week=1,
            position="RB",
            model_distributions={},
            depth_rank=depth_rank,
        )["rushing_yards"].mean

    assert project(1) > project(3), (
        "an RB3's own history regressed to the RB1 archetype must project higher"
    )


def test_rookie_with_no_history_uses_rank_baseline_and_widens_spread(monkeypatch):
    monkeypatch.setattr(fs, "_rank_lookup", lambda weekly: _ranks())
    monkeypatch.setattr(fs, "_rookie_capital_multiplier", lambda pid, weekly: 1.15)
    fs._BASELINE_CACHE.clear()

    dist = fs._trailing_fantasy_distributions(
        _weekly(),
        player_id="ROOKIE",
        season=2026,
        week=1,
        position="RB",
        model_distributions={},
        depth_rank=1,
    )["rushing_yards"]

    assert dist.mean == 95.0 * 1.15, "RB1 baseline scaled by first-round capital"
    veteran_cv = fs.default_calibration().yard_cv
    assert dist.std > veteran_cv * dist.mean, "rookie spread must be inflated"


_BASELINES = {
    ("RB", 1, "rushing_yards"): 95.0,
    ("RB", 3, "rushing_yards"): 15.0,
    ("RB", None, "rushing_yards"): 55.0,
}


def test_depth_chart_factor_fires_on_promotion_and_is_bounded():
    calib = fs.default_calibration()
    factor = fs._depth_chart_factor(
        _BASELINES, position="RB", current=1, prior=3, calib=calib
    )
    assert factor.applied
    assert factor.multiplier > 1.0
    assert factor.multiplier <= calib.context_clamp_hi, "must stay bounded"
    assert "RB3" in factor.reason and "RB1" in factor.reason


def test_depth_chart_factor_neutral_when_rank_unchanged():
    factor = fs._depth_chart_factor(
        _BASELINES, position="RB", current=2, prior=2, calib=fs.default_calibration()
    )
    assert not factor.applied
    assert factor.multiplier == 1.0


def test_depth_chart_factor_neutral_when_rank_unknown():
    calib = fs.default_calibration()
    assert not fs._depth_chart_factor(
        _BASELINES, position="RB", current=None, prior=3, calib=calib
    ).applied
    assert not fs._depth_chart_factor(
        _BASELINES, position="RB", current=1, prior=None, calib=calib
    ).applied


def _factor(name, multiplier, applied):
    return fs.FantasyContextFactor(
        name=name, label=name, multiplier=multiplier, applied=applied,
        affected_stats=["rushing_yards"], reason="x",
    )


def test_usage_trend_is_suppressed_when_depth_chart_fires():
    resolved = fs._resolve_role_precedence(
        [_factor("depth_chart", 1.2, True), _factor("usage_trend", 1.1, True)]
    )
    by_name = {f.name: f for f in resolved}
    assert by_name["depth_chart"].applied
    assert not by_name["usage_trend"].applied, "a role change must not be priced twice"
    assert "superseded" in by_name["usage_trend"].reason


def test_usage_trend_survives_when_depth_chart_is_neutral():
    resolved = fs._resolve_role_precedence(
        [_factor("depth_chart", 1.0, False), _factor("usage_trend", 1.1, True)]
    )
    assert {f.name: f.applied for f in resolved}["usage_trend"]
