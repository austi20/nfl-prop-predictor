"""Unit tests for scripts/synthesize_training.py majority vote and loaders."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.synthesize_training import (
    _EXPECTED_ROWS_PER_SEASON,
    load_all_seasons,
    majority_config_per_stat,
    per_season_stat_winners,
    render_summary_md,
    select_pareto_config,
)


_STATS_BY_POSITION = {
    "qb": ["passing_yards", "passing_tds", "interceptions", "completions"],
    "rb": ["rushing_yards", "carries", "rushing_tds"],
    "wr_te": ["receptions", "receiving_yards", "receiving_tds"],
}


def _row(
    season: int,
    pos: str,
    stat: str,
    cfg: str,
    ll: float,
    *,
    conv: str = "ok",
    dist: str = "legacy",
    k: int = 2,
    l1: float = 0.0,
    weather: bool = True,
    n_holdout: int = 10,
) -> dict:
    return {
        "config_hash": cfg,
        "holdout_season": season,
        "position": pos,
        "stat": stat,
        "use_weather": weather,
        "use_opponent_epa": False,
        "use_rest_days": False,
        "use_home_away": False,
        "dist_family": dist,
        "k": k,
        "l1_alpha": l1,
        "log_loss": ll,
        "brier": 0.25,
        "n_holdout": n_holdout,
        "max_reliability_dev": 0.1,
        "convergence_flag": conv,
    }


def _complete_season(season: int, *, ll: float = 1.0) -> pd.DataFrame:
    rows = []
    for cfg_idx in range(144):
        cfg = f"cfg{cfg_idx:03d}"
        for pos, stats in _STATS_BY_POSITION.items():
            for stat in stats:
                rows.append(_row(season, pos, stat, cfg, ll + cfg_idx * 0.0001))
    assert len(rows) == _EXPECTED_ROWS_PER_SEASON
    return pd.DataFrame(rows)


def test_per_season_stat_winners_argmin(tmp_path: Path) -> None:
    rows = [
        _row(2019, "qb", "passing_yards", "aaa", 0.9),
        _row(2019, "qb", "passing_yards", "bbb", 0.7),
        _row(2020, "qb", "passing_yards", "aaa", 0.6),
        _row(2020, "qb", "passing_yards", "bbb", 0.8),
    ]
    df = pd.DataFrame(rows)
    w = per_season_stat_winners(df)
    assert len(w) == 2
    assert set(zip(w["holdout_season"], w["config_hash"])) == {(2019, "bbb"), (2020, "aaa")}


def test_majority_picks_mode(tmp_path: Path) -> None:
    """bbb wins 2019 and 2020; aaa wins only 2021 => majority is bbb."""
    rows = [
        _row(2019, "qb", "passing_yards", "aaa", 0.9),
        _row(2019, "qb", "passing_yards", "bbb", 0.7),
        _row(2020, "qb", "passing_yards", "aaa", 0.8),
        _row(2020, "qb", "passing_yards", "bbb", 0.6),
        _row(2021, "qb", "passing_yards", "aaa", 0.5),
        _row(2021, "qb", "passing_yards", "bbb", 0.55),
    ]
    df = pd.DataFrame(rows)
    maj = majority_config_per_stat(df)
    assert len(maj) == 1
    assert maj.iloc[0]["config_hash"] == "bbb"
    assert int(maj.iloc[0]["vote_count"]) == 2


def test_majority_tie_break_uses_weighted_pooled_log_loss(tmp_path: Path) -> None:
    """Two configs each win once; tie-break uses n_holdout-weighted pooled log_loss."""
    rows = [
        _row(2019, "qb", "passing_yards", "aaa", 0.1, n_holdout=1),
        _row(2019, "qb", "passing_yards", "bbb", 0.2, n_holdout=1),
        _row(2020, "qb", "passing_yards", "aaa", 0.6, n_holdout=100),
        _row(2020, "qb", "passing_yards", "bbb", 0.5, n_holdout=100),
    ]
    df = pd.DataFrame(rows)
    maj = majority_config_per_stat(df)
    assert maj.iloc[0]["config_hash"] == "bbb"
    assert float(maj.iloc[0]["mean_log_loss_pooled"]) == pytest.approx(50.2 / 101)


def test_load_all_seasons_concat_complete_files(tmp_path: Path) -> None:
    d1 = _complete_season(2019, ll=1.0)
    d2 = _complete_season(2020, ll=1.1)
    d1.to_csv(tmp_path / "season_2019_results.csv", index=False)
    d2.to_csv(tmp_path / "season_2020_results.csv", index=False)
    # seasons 2021-2025 missing — allowed
    combined = load_all_seasons(tmp_path)
    assert len(combined) == 2 * _EXPECTED_ROWS_PER_SEASON
    assert set(combined["holdout_season"].unique()) == {2019, 2020}


def test_load_all_seasons_partial_file_raises_by_default(tmp_path: Path) -> None:
    pd.DataFrame([_row(2019, "qb", "passing_yards", "a", 1.0)]).to_csv(
        tmp_path / "season_2019_results.csv",
        index=False,
    )

    with pytest.raises(ValueError, match="incomplete"):
        load_all_seasons(tmp_path)


def test_load_all_seasons_allow_partial_skips_incomplete(tmp_path: Path) -> None:
    pd.DataFrame([_row(2019, "qb", "passing_yards", "a", 1.0)]).to_csv(
        tmp_path / "season_2019_results.csv",
        index=False,
    )
    _complete_season(2020, ll=1.1).to_csv(tmp_path / "season_2020_results.csv", index=False)

    combined = load_all_seasons(tmp_path, allow_partial=True)

    assert set(combined["holdout_season"].unique()) == {2020}
    assert len(combined) == _EXPECTED_ROWS_PER_SEASON


def test_load_all_seasons_duplicate_keys_raise(tmp_path: Path) -> None:
    rows = [
        _row(2019, "qb", "passing_yards", "dup", 1.0),
        _row(2019, "qb", "passing_yards", "dup", 1.1),
    ]
    pd.DataFrame(rows).to_csv(tmp_path / "season_2019_results.csv", index=False)

    with pytest.raises(ValueError, match="duplicate result keys"):
        load_all_seasons(tmp_path)


def test_select_pareto_smoke() -> None:
    rows = []
    for season in (2019, 2020):
        for cfg, ll in (("x", 1.0), ("y", 1.1)):
            for pos, stat in (("qb", "passing_yards"), ("qb", "passing_tds")):
                rows.append(_row(season, pos, stat, cfg, ll))
    df = pd.DataFrame(rows)
    best_hash, agg = select_pareto_config(df)
    assert best_hash == "x"
    assert len(agg) >= 1


def test_render_summary_md_shows_plain_int_seasons() -> None:
    df = pd.DataFrame([
        _row(2019, "qb", "passing_yards", "x", 1.0),
        _row(2020, "qb", "passing_yards", "x", 1.1),
    ])
    majority_df = pd.DataFrame([{
        "position": "qb",
        "stat": "passing_yards",
        "config_hash": "x",
        "vote_count": 2,
        "holdout_seasons_available": 2,
        "winning_seasons": "2019,2020",
        "mean_log_loss_pooled": 1.05,
        "k": 2,
        "l1_alpha": 0.0,
        "dist_family": "legacy",
        "use_weather": True,
    }])
    agg = pd.DataFrame([{
        "config_hash": "x",
        "use_weather": True,
        "dist_family": "legacy",
        "k": 2,
        "l1_alpha": 0.0,
        "use_opponent_epa": False,
        "use_rest_days": False,
        "use_home_away": False,
        "mean_ll": 1.05,
        "std_ll": 0.01,
        "score": 1.055,
    }])
    pooled = pd.DataFrame([{
        "position": "qb",
        "stat": "passing_yards",
        "dist_family": "legacy",
        "k": 2,
        "l1_alpha": 0.0,
        "use_weather": True,
        "mean_ll": 1.05,
    }])

    md = render_summary_md(
        majority_df=majority_df,
        best_hash="x",
        best_row=agg.iloc[0],
        agg=agg,
        ablation={},
        pooled_stat_winners=pooled,
        df=df,
        rollup_notes="notes",
        png_written=True,
    )

    assert "**Holdout seasons loaded:** [2019, 2020]" in md
    assert "np.int" not in md
    assert "Reliability deviation trend" in md
    assert "Reliability overlay" not in md
