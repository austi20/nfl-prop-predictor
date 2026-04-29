"""Phase H3 tests: narrate_season.py template rendering and Qwen mock.

Verifies:
- All template slots are filled with deterministic numeric values
- Qwen freeform section is replaced (not left as placeholder)
- Freeform token limit is respected (80 tokens)
- Missing results CSV raises FileNotFoundError
"""

from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from scripts.narrate_season import (
    _FREEFORM_MAX_TOKENS,
    best_config,
    build_template_context,
    fill_freeform,
    load_results,
    render_scaffold,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_canned_results(holdout_season: int = 2019, n_configs: int = 4) -> pd.DataFrame:
    """Minimal season_YYYY_results.csv with known values for slot verification."""
    rng = np.random.default_rng(42)
    rows = []
    dist_families = ["legacy", "count_aware", "decomposed", "legacy"]
    for i in range(n_configs):
        chash = f"hash{i:04d}"
        for position, stat in [
            ("qb", "passing_yards"),
            ("qb", "passing_tds"),
            ("rb", "rushing_yards"),
            ("wr_te", "receptions"),
        ]:
            rows.append({
                "config_hash": chash,
                "holdout_season": holdout_season,
                "position": position,
                "stat": stat,
                "use_weather": i % 2 == 0,
                "use_opponent_epa": False,
                "use_rest_days": False,
                "use_home_away": False,
                "dist_family": dist_families[i],
                "k": [2, 4, 8, 16][i],
                "l1_alpha": [0.0, 0.001, 0.01, 0.1][i],
                "n_train": 1000 + i * 100,
                "n_holdout": 200 + i * 20,
                "log_loss": round(0.65 + rng.uniform(-0.05, 0.05), 4),
                "brier": round(0.22 + rng.uniform(-0.02, 0.02), 4),
                "mae": round(20.0 + rng.uniform(-5, 5), 2),
                "rmse": round(30.0 + rng.uniform(-5, 5), 2),
                "bias": round(rng.uniform(-2, 2), 2),
                "aic": round(1500.0 + rng.uniform(-100, 100), 1),
                "max_reliability_dev": round(0.05 + rng.uniform(0, 0.05), 4),
                "fit_seconds": round(rng.uniform(0.1, 2.0), 3),
                "convergence_flag": "ok",
            })
    return pd.DataFrame(rows)


@pytest.fixture()
def canned_results() -> pd.DataFrame:
    return _make_canned_results()


@pytest.fixture()
def canned_results_path(tmp_path, canned_results) -> Path:
    path = tmp_path / "season_2019_results.csv"
    canned_results.to_csv(path, index=False)
    return path


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_load_results_missing_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="Results CSV not found"):
        load_results(2019, tmp_path)


def test_load_results_reads_csv(canned_results_path) -> None:
    df = load_results(2019, canned_results_path.parent)
    assert len(df) > 0
    assert "log_loss" in df.columns


def test_best_config_returns_row(canned_results) -> None:
    row = best_config(canned_results)
    assert "config_hash" in row.index
    assert "dist_family" in row.index


def test_build_template_context_all_slots_filled(canned_results) -> None:
    ctx = build_template_context(canned_results, 2019)
    required_slots = [
        "season", "holdout_season", "best_k", "best_l1_alpha", "best_dist_family",
        "feature_flags", "log_loss", "log_loss_delta", "brier", "max_reliability_dev",
        "top_3_features_table", "weather_delta", "opp_epa_delta",
        "rest_days_delta", "dist_family_table",
    ]
    for slot in required_slots:
        assert slot in ctx, f"Missing slot: {slot}"
        assert ctx[slot] is not None, f"Slot is None: {slot}"
        assert str(ctx[slot]) != "", f"Slot is empty string: {slot}"


def test_render_scaffold_contains_numeric_values(canned_results) -> None:
    ctx = build_template_context(canned_results, 2019)
    ctx["qwen_freeform_notes"] = "{{ qwen_freeform_notes }}"
    scaffold = render_scaffold(ctx)
    # All numeric slots must appear verbatim in the rendered output
    assert str(ctx["best_k"]) in scaffold
    assert str(ctx["best_l1_alpha"]) in scaffold
    assert ctx["log_loss"] in scaffold
    assert ctx["brier"] in scaffold
    assert "2019" in scaffold


def test_render_scaffold_has_placeholder_before_fill(canned_results) -> None:
    ctx = build_template_context(canned_results, 2019)
    ctx["qwen_freeform_notes"] = "{{ qwen_freeform_notes }}"
    scaffold = render_scaffold(ctx)
    assert "{{ qwen_freeform_notes }}" in scaffold


def test_fill_freeform_replaces_placeholder(canned_results) -> None:
    ctx = build_template_context(canned_results, 2019)
    scaffold = render_scaffold(ctx)

    mock_text = "The model showed stable calibration across positions."
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"choices": [{"text": mock_text}]}
    mock_resp.raise_for_status = MagicMock()

    with patch("scripts.narrate_season.requests.post", return_value=mock_resp):
        result = fill_freeform(scaffold, "http://localhost:8080")

    assert "{{ qwen_freeform_notes }}" not in result
    assert mock_text in result


def test_fill_freeform_handles_llm_failure(canned_results) -> None:
    ctx = build_template_context(canned_results, 2019)
    scaffold = render_scaffold(ctx)

    with patch("scripts.narrate_season.requests.post", side_effect=Exception("connection refused")):
        result = fill_freeform(scaffold, "http://localhost:8080")

    assert "{{ qwen_freeform_notes }}" not in result
    assert "LLM unavailable" in result


def test_freeform_max_tokens_constant() -> None:
    assert _FREEFORM_MAX_TOKENS == 80


def test_dist_family_table_contains_all_families(canned_results) -> None:
    ctx = build_template_context(canned_results, 2019)
    table = ctx["dist_family_table"]
    assert "legacy" in table
    assert "count_aware" in table
    assert "decomposed" in table


def test_log_loss_delta_vs_naive(canned_results) -> None:
    ctx = build_template_context(canned_results, 2019)
    delta_str = ctx["log_loss_delta"]
    # Should be a numeric string with sign
    assert any(c.isdigit() for c in delta_str)
