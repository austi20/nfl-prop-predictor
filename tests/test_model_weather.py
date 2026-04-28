"""H1 tests: statsmodels migration parity + weather feature gating.

TDD RED: all tests fail until H1 implementation lands.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_qb_df(n_players: int = 6, n_seasons: int = 3, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for pid in range(n_players):
        for season in range(2020, 2020 + n_seasons):
            for week in range(1, 18):
                rows.append({
                    "player_id": f"qb_{pid:02d}",
                    "player_name": f"QB{pid}",
                    "position": "QB",
                    "season": season,
                    "week": week,
                    "recent_team": ["KC", "BUF", "SF", "DAL", "PHI", "MIA"][pid % 6],
                    "opponent_team": ["NYG", "NE", "LAR", "SEA", "CHI", "DET"][pid % 6],
                    "passing_yards": float(rng.gamma(shape=3, scale=80)),
                    "passing_tds": float(rng.poisson(1.8)),
                    "interceptions": float(rng.poisson(0.7)),
                    "completions": float(rng.gamma(shape=4, scale=6)),
                    "attempts": float(rng.gamma(shape=4, scale=9)),
                    "sacks": float(rng.poisson(2.0)),
                    "passing_air_yards": float(rng.gamma(shape=2, scale=100)),
                    "passing_epa": float(rng.normal(0, 5)),
                    "dakota": float(rng.normal(0, 0.5)),
                    "is_home": float(rng.integers(0, 2)),
                    # weather columns (present in load_weekly_with_weather output)
                    "temp_f": float(rng.uniform(20, 90)),
                    "wind_mph": float(rng.uniform(0, 25)),
                    "precip_in": float(rng.uniform(0, 0.5)),
                    "weather_code": 0,
                    "indoor": False,
                })
    return pd.DataFrame(rows)


def _make_rb_df(n_players: int = 6, n_seasons: int = 3, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for pid in range(n_players):
        for season in range(2020, 2020 + n_seasons):
            for week in range(1, 18):
                rows.append({
                    "player_id": f"rb_{pid:02d}",
                    "player_name": f"RB{pid}",
                    "position": "RB",
                    "season": season,
                    "week": week,
                    "recent_team": ["KC", "BUF", "SF", "DAL", "PHI", "MIA"][pid % 6],
                    "opponent_team": ["NYG", "NE", "LAR", "SEA", "CHI", "DET"][pid % 6],
                    "rushing_yards": float(rng.gamma(shape=2, scale=30)),
                    "carries": float(rng.poisson(12)),
                    "rushing_tds": float(rng.poisson(0.5)),
                    "rushing_epa": float(rng.normal(0, 3)),
                    "is_home": float(rng.integers(0, 2)),
                    "temp_f": float(rng.uniform(20, 90)),
                    "wind_mph": float(rng.uniform(0, 25)),
                    "precip_in": float(rng.uniform(0, 0.5)),
                    "weather_code": 0,
                    "indoor": False,
                })
    return pd.DataFrame(rows)


def _make_wr_te_df(n_players: int = 6, n_seasons: int = 3, seed: int = 13) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for pid in range(n_players):
        for season in range(2020, 2020 + n_seasons):
            for week in range(1, 18):
                rows.append({
                    "player_id": f"wr_{pid:02d}",
                    "player_name": f"WR{pid}",
                    "position": "WR",
                    "season": season,
                    "week": week,
                    "recent_team": ["KC", "BUF", "SF", "DAL", "PHI", "MIA"][pid % 6],
                    "opponent_team": ["NYG", "NE", "LAR", "SEA", "CHI", "DET"][pid % 6],
                    "receptions": float(rng.poisson(5)),
                    "receiving_yards": float(rng.gamma(shape=2, scale=30)),
                    "receiving_tds": float(rng.poisson(0.4)),
                    "targets": float(rng.poisson(7)),
                    "target_share": float(rng.uniform(0.05, 0.30)),
                    "air_yards_share": float(rng.uniform(0.05, 0.25)),
                    "wopr": float(rng.uniform(0.05, 0.50)),
                    "receiving_epa": float(rng.normal(0, 3)),
                    "is_home": float(rng.integers(0, 2)),
                    "temp_f": float(rng.uniform(20, 90)),
                    "wind_mph": float(rng.uniform(0, 25)),
                    "precip_in": float(rng.uniform(0, 0.5)),
                    "weather_code": 0,
                    "indoor": False,
                })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Weather feature presence tests
# ---------------------------------------------------------------------------

def test_qb_weather_features_in_feature_cols_when_enabled():
    from models.qb import QBModel
    df = _make_qb_df()
    model = QBModel()
    model.fit([2020, 2021], weekly=df, use_weather=True)
    assert "wind_mph" in model._feature_cols
    assert "precip_in" in model._feature_cols
    assert "temp_f_minus_60" in model._feature_cols
    assert "wind_x_pass_attempt_rate" in model._feature_cols


def test_qb_weather_features_absent_by_default():
    from models.qb import QBModel
    df = _make_qb_df()
    model = QBModel()
    model.fit([2020, 2021], weekly=df)
    assert "wind_mph" not in model._feature_cols
    assert "temp_f_minus_60" not in model._feature_cols


def test_rb_weather_features_in_feature_cols_when_enabled():
    from models.rb import RBModel
    df = _make_rb_df()
    model = RBModel()
    model.fit([2020, 2021], weekly=df, use_weather=True)
    assert "wind_mph" in model._feature_cols
    assert "precip_in" in model._feature_cols
    assert "temp_f_minus_60" in model._feature_cols


def test_rb_has_no_wind_interaction_term():
    from models.rb import RBModel
    df = _make_rb_df()
    model = RBModel()
    model.fit([2020, 2021], weekly=df, use_weather=True)
    assert "wind_x_pass_attempt_rate" not in model._feature_cols


def test_wr_te_weather_features_in_feature_cols_when_enabled():
    from models.wr_te import WRTEModel
    df = _make_wr_te_df()
    model = WRTEModel()
    model.fit([2020, 2021], weekly=df, use_weather=True)
    assert "wind_mph" in model._feature_cols
    assert "precip_in" in model._feature_cols
    assert "temp_f_minus_60" in model._feature_cols
    assert "wind_x_pass_attempt_rate" not in model._feature_cols


def test_qb_fit_uses_weather_loader_when_flag_enabled(monkeypatch):
    from data import nflverse_loader
    from models.qb import QBModel

    df = _make_qb_df()
    calls = {"plain": 0, "weather": 0}

    def fake_load_weekly(years):
        calls["plain"] += 1
        return df.copy()

    def fake_load_weekly_with_weather(years):
        calls["weather"] += 1
        return df.copy()

    monkeypatch.setattr(nflverse_loader, "load_weekly", fake_load_weekly)
    monkeypatch.setattr(nflverse_loader, "load_weekly_with_weather", fake_load_weekly_with_weather)

    model = QBModel()
    model.fit([2020, 2021], use_weather=True)

    assert calls == {"plain": 0, "weather": 1}


# ---------------------------------------------------------------------------
# Indoor masking test
# ---------------------------------------------------------------------------

def test_weather_features_zero_for_indoor_game():
    """Indoor=True rows should have zero weather values in the feature matrix."""
    from models.qb import _build_features
    df = _make_qb_df(n_players=2, n_seasons=1)
    # Force all rows indoor
    df["indoor"] = True
    df_feat, feat_cols = _build_features(df, use_weather=True)
    for col in ("wind_mph", "precip_in", "temp_f_minus_60", "wind_x_pass_attempt_rate"):
        assert (df_feat[col] == 0.0).all(), f"{col} should be 0 for indoor games"


def test_weather_features_nonzero_for_outdoor_game():
    """Outdoor games with wind > 0 should have nonzero wind_mph feature."""
    from models.qb import _build_features
    df = _make_qb_df(n_players=2, n_seasons=1)
    df["indoor"] = False
    df["wind_mph"] = 15.0
    df_feat, feat_cols = _build_features(df, use_weather=True)
    assert (df_feat["wind_mph"] > 0).any()


# ---------------------------------------------------------------------------
# Statsmodels parity test
# ---------------------------------------------------------------------------

def test_statsmodels_qb_predictions_in_reasonable_range():
    """After migration, QB passing_yards predictions are positive and in realistic range."""
    from models.qb import QBModel
    df = _make_qb_df()
    model = QBModel()
    model.fit([2020, 2021], weekly=df)
    pred = model.predict("qb_00", week=10, season=2022)
    assert "passing_yards" in pred
    dist = pred["passing_yards"]
    assert dist.mean > 0, "mean should be positive"
    assert dist.std > 0, "std should be positive"
    # Passing yards should be in plausible NFL range
    assert 50 < dist.mean < 600, f"mean {dist.mean} outside plausible QB passing yards range"


def test_statsmodels_rb_predictions_in_reasonable_range():
    from models.rb import RBModel
    df = _make_rb_df()
    model = RBModel()
    model.fit([2020, 2021], weekly=df)
    pred = model.predict("rb_00", week=10, season=2022)
    assert pred["rushing_yards"].mean > 0
    assert 10 < pred["rushing_yards"].mean < 300


def test_statsmodels_wr_te_predictions_in_reasonable_range():
    from models.wr_te import WRTEModel
    df = _make_wr_te_df()
    model = WRTEModel()
    model.fit([2020, 2021], weekly=df)
    pred = model.predict("wr_00", week=10, season=2022)
    assert pred["receiving_yards"].mean > 0


# ---------------------------------------------------------------------------
# AIC availability test
# ---------------------------------------------------------------------------

def test_aic_accessible_after_qb_fit():
    """Statsmodels GLM result exposes AIC for H3 narration."""
    from models.qb import QBModel
    df = _make_qb_df()
    model = QBModel()
    model.fit([2020, 2021], weekly=df)
    for stat, result in model._models.items():
        assert hasattr(result, "aic"), f"statsmodels result for {stat} should have .aic"
        assert np.isfinite(result.aic), f"AIC for {stat} should be finite"


def test_regularized_fit_preserves_finite_aic():
    from models.qb import QBModel

    df = _make_qb_df()
    model = QBModel()
    model.fit([2020, 2021], weekly=df, l1_alpha=0.01)

    for stat, result in model._models.items():
        assert hasattr(result, "aic"), f"regularized result for {stat} should expose .aic"
        assert np.isfinite(result.aic), f"regularized AIC for {stat} should be finite"


def test_weather_toggle_keeps_aic_delta_bounded():
    from models.qb import QBModel

    df = _make_qb_df()
    model_plain = QBModel()
    model_plain.fit([2020, 2021], weekly=df, use_weather=False)

    model_weather = QBModel()
    model_weather.fit([2020, 2021], weekly=df, use_weather=True)

    delta = abs(
        model_weather._models["passing_yards"].aic - model_plain._models["passing_yards"].aic
    )
    assert np.isfinite(delta)
    assert delta < 200.0


def test_statsmodels_gamma_matches_sklearn_baseline():
    from sklearn.linear_model import GammaRegressor
    import statsmodels.api as sm

    rng = np.random.default_rng(123)
    X = rng.normal(size=(400, 4))
    beta = np.array([0.12, -0.08, 0.05, 0.09])
    intercept = 5.4
    mu = np.exp(intercept + (X @ beta))
    y = rng.gamma(shape=20.0, scale=mu / 20.0)

    sklearn_model = GammaRegressor(alpha=0.0, max_iter=1000)
    sklearn_model.fit(X, y)

    sm_model = sm.GLM(
        y,
        sm.add_constant(X, has_constant="add"),
        family=sm.families.Gamma(sm.families.links.Log()),
    ).fit(maxiter=500)

    pred_sklearn = sklearn_model.predict(X[:50])
    pred_statsmodels = sm_model.predict(sm.add_constant(X[:50], has_constant="add"))

    assert np.allclose(pred_statsmodels, pred_sklearn, rtol=1e-2, atol=1e-2)
