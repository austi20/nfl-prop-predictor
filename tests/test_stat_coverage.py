"""Every position must be able to express every stat it actually accumulates.

A pass-catching back with no receiving model, or a rushing quarterback with no
rushing model, is not a tuning problem — the model structurally cannot say
anything about half that player's box score.
"""
from __future__ import annotations

import pytest

from eval.calibration_pipeline import _MODEL_STATS, STAT_SPECS, spec_for
from models.qb import _TARGET_STATS as QB_TARGETS
from models.rb import _TARGET_STATS as RB_TARGETS
from models.wr_te import _TARGET_STATS as WR_TE_TARGETS

_QB_EXPECTED = {
    "passing_yards", "passing_tds", "interceptions", "completions", "attempts",
    "rushing_yards", "carries", "rushing_tds",
}
_RB_EXPECTED = {
    "rushing_yards", "carries", "rushing_tds",
    "receptions", "receiving_yards", "receiving_tds", "targets",
}
_WR_TE_EXPECTED = {
    "receptions", "receiving_yards", "receiving_tds", "targets",
    "rushing_yards", "carries", "rushing_tds",
}


@pytest.mark.parametrize(
    ("targets", "expected", "label"),
    [
        (QB_TARGETS, _QB_EXPECTED, "QB"),
        (RB_TARGETS, _RB_EXPECTED, "RB"),
        (WR_TE_TARGETS, _WR_TE_EXPECTED, "WR/TE"),
    ],
)
def test_model_covers_every_stat_its_position_accumulates(targets, expected, label):
    assert set(targets) == expected, f"{label} target coverage drifted"


def test_no_duplicate_targets():
    for targets in (QB_TARGETS, RB_TARGETS, WR_TE_TARGETS):
        assert len(targets) == len(set(targets))


def test_every_model_has_a_family_and_dist_type_for_each_target():
    from models.qb import _FAMILIES as QB_FAM
    from models.rb import _DIST_TYPE as RB_DIST
    from models.rb import _FAMILIES as RB_FAM
    from models.wr_te import _DIST_TYPES as WR_DIST
    from models.wr_te import _FAMILIES as WR_FAM

    for stat in QB_TARGETS:
        assert stat in QB_FAM, f"QB missing family for {stat}"
    for stat in RB_TARGETS:
        assert stat in RB_FAM, f"RB missing family for {stat}"
        assert stat in RB_DIST, f"RB missing dist type for {stat}"
    for stat in WR_TE_TARGETS:
        assert stat in WR_FAM, f"WR/TE missing family for {stat}"
        assert stat in WR_DIST, f"WR/TE missing dist type for {stat}"


# --- routing ---------------------------------------------------------------


def test_shared_stats_route_to_the_position_that_owns_the_player():
    """A back's receptions belong to the RB model, not the receiver population."""
    assert spec_for("receptions", "RB").model_name == "rb"
    assert spec_for("receptions", "WR").model_name == "wr_te"
    assert spec_for("receptions", "TE").model_name == "wr_te"
    assert spec_for("rushing_yards", "QB").model_name == "qb"
    assert spec_for("rushing_yards", "RB").model_name == "rb"
    assert spec_for("rushing_yards", "WR").model_name == "wr_te"


def test_fullback_routes_like_a_back():
    assert spec_for("rushing_yards", "FB").model_name == "rb"


def test_unknown_position_falls_back_to_the_stats_natural_owner():
    assert spec_for("receptions", "").model_name == "wr_te"
    assert spec_for("rushing_yards", "").model_name == "rb"
    assert spec_for("passing_yards", "").model_name == "qb"
    assert spec_for("attempts", "").model_name == "qb"
    assert spec_for("targets", "").model_name == "wr_te"


def test_unknown_stat_returns_none():
    assert spec_for("field_goals_made", "QB") is None


def test_position_with_no_model_for_that_stat_falls_back():
    """A QB has no targets model, so the request still resolves somewhere sane."""
    assert spec_for("targets", "QB").model_name == "wr_te"


def test_every_default_spec_is_predictable_by_its_model():
    for stat, spec in STAT_SPECS.items():
        assert stat in _MODEL_STATS[spec.model_name], (
            f"{stat} defaults to {spec.model_name}, which does not predict it"
        )


def test_attempts_and_targets_are_now_supported_props():
    assert "attempts" in STAT_SPECS
    assert "targets" in STAT_SPECS


def test_kalshi_series_map_only_references_predictable_stats():
    from api.services.market_lines import _SERIES_STAT

    for series, stat in _SERIES_STAT.items():
        assert stat in STAT_SPECS, f"{series} maps to unpredictable stat {stat}"
