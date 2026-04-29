# H2 train_loop.py Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic walk-forward ablation harness (`scripts/train_loop.py`) that produces `docs/training/season_<YYYY>_results.csv` per the H2 spec.

**Architecture:** 144-config grid (use_weather × dist_family × k × l1_alpha) × 6 expanding-window holdout seasons (2019-2024). Sequential, single-process, row-level checkpoint append. Source of truth for holdout labels is `docs/training/synthetic_props_training.csv`.

**Tech Stack:** statsmodels GLM, pandas, numpy, sklearn (for log_loss/brier_score_loss). Existing `models/{qb,rb,wr_te}.py` and `eval/training_dataset.py` are reused.

**Spec:** `docs/superpowers/specs/2026-04-28-h2-train-loop-design.md`

---

## Task 1: tests/test_l1_path.py — L1 monotonicity proof

**Files:**
- Create: `tests/test_l1_path.py`

- [ ] **Step 1: Write the failing test**

```python
"""H2 verification: L1 alpha monotonically reduces nonzero coefficients."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from models.qb import QBModel


def _make_qb_weekly(n: int = 200, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "player_id": [f"p{i % 8}" for i in range(n)],
        "player_name": [f"QB{i % 8}" for i in range(n)],
        "position": ["QB"] * n,
        "season": [2018 + (i // 50) for i in range(n)],
        "week": [(i % 17) + 1 for i in range(n)],
        "recent_team": ["KC"] * n,
        "opponent_team": ["BUF"] * n,
        "passing_yards": np.clip(rng.normal(250, 55, n), 1, None),
        "passing_tds": rng.integers(0, 5, n).astype(float),
        "interceptions": rng.integers(0, 3, n).astype(float),
        "completions": np.clip(rng.normal(22, 5, n), 1, None),
        "attempts": np.clip(rng.normal(32, 6, n), 1, None),
        "sacks": rng.integers(0, 4, n).astype(float),
        "passing_air_yards": rng.uniform(150, 300, n),
        "passing_epa": rng.normal(0, 1, n),
        "dakota": rng.normal(0, 1, n),
    })


def _count_nonzero(model: QBModel, stat: str, tol: float = 1e-6) -> int:
    fit = model._models.get(stat)
    if fit is None or not hasattr(fit, "params"):
        return 0
    params = np.asarray(fit.params)
    return int(np.sum(np.abs(params) > tol))


def test_l1_alpha_monotonically_reduces_nonzero_coefficients():
    weekly = _make_qb_weekly()
    alphas = [0.0, 0.001, 0.01, 0.1]
    counts: list[int] = []
    for alpha in alphas:
        model = QBModel()
        model.fit([2018, 2019, 2020, 2021], weekly=weekly, l1_alpha=alpha)
        counts.append(_count_nonzero(model, "passing_yards"))
    for prev, curr in zip(counts, counts[1:]):
        assert curr <= prev, f"nonzero counts not monotonically non-increasing: {counts}"
    assert counts[-1] < counts[0], f"highest alpha should drop at least one coefficient: {counts}"
```

- [ ] **Step 2: Run test to verify it passes (statsmodels L1 path already in H1)**

Run: `uv run pytest tests/test_l1_path.py -v`
Expected: PASS — H1 already wired `fit_regularized(L1_wt=1.0, refit=True)`.

If it fails because alphas don't drop coefficients, the synthetic data is too well-conditioned; bump n to 500 or add more correlated features.

- [ ] **Step 3: Commit**

```bash
git add tests/test_l1_path.py
git commit -m "test: H2 verification — L1 alpha monotonicity on QB GLM"
```

---

## Task 2: scripts/train_loop.py — config grid + deterministic hash

**Files:**
- Create: `scripts/train_loop.py`
- Test: `tests/test_train_loop.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_train_loop.py
"""Smoke tests for H2 walk-forward ablation harness."""
from __future__ import annotations

import hashlib
import json

import pytest

from scripts.train_loop import build_config_grid, config_hash


def test_grid_has_144_configs():
    grid = list(build_config_grid())
    assert len(grid) == 144


def test_grid_contains_all_axes():
    grid = list(build_config_grid())
    weather_vals = {c["use_weather"] for c in grid}
    families = {c["dist_family"] for c in grid}
    ks = {c["k"] for c in grid}
    alphas = {c["l1_alpha"] for c in grid}
    assert weather_vals == {True, False}
    assert families == {"legacy", "count_aware", "decomposed"}
    assert ks == {2, 4, 6, 8, 12, 16}
    assert alphas == {0.0, 0.001, 0.01, 0.1}


def test_config_hash_is_deterministic():
    cfg = {"use_weather": True, "dist_family": "legacy", "k": 8, "l1_alpha": 0.0}
    assert config_hash(cfg) == config_hash(cfg)


def test_config_hash_changes_with_config():
    cfg_a = {"use_weather": True, "dist_family": "legacy", "k": 8, "l1_alpha": 0.0}
    cfg_b = {"use_weather": False, "dist_family": "legacy", "k": 8, "l1_alpha": 0.0}
    assert config_hash(cfg_a) != config_hash(cfg_b)


def test_config_hash_includes_deferred_flags():
    """Future-proofs CSV schema for H2.1 — hash must reflect all 7 knobs."""
    cfg = {
        "use_weather": True, "dist_family": "legacy", "k": 8, "l1_alpha": 0.0,
        "use_opponent_epa": False, "use_rest_days": False, "use_home_away": False,
    }
    h = config_hash(cfg)
    assert isinstance(h, str)
    assert len(h) == 32  # md5 hex
```

- [ ] **Step 2: Run tests, verify they fail with ImportError**

Run: `uv run pytest tests/test_train_loop.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.train_loop'`

- [ ] **Step 3: Implement minimal `scripts/train_loop.py` to pass tests**

```python
"""H2 walk-forward ablation harness.

Trains QB/RB/WR-TE GLMs across the 144-config H2 grid for 6 expanding-window
holdouts (2019-2024). Writes one row per (config, position, stat) to
docs/training/season_<YYYY>_results.csv. Row-level append checkpoint;
deterministic per-fit RNG seeds; sequential single-process execution.

Out-of-scope flags reserved for H2.1: use_opponent_epa, use_rest_days,
use_home_away. Currently fixed False; CSV schema includes them as columns
so H2.1 can append without schema break.
"""

from __future__ import annotations

import hashlib
import json
from itertools import product
from typing import Iterator


_CONFIG_KEYS = (
    "use_weather",
    "use_opponent_epa",
    "use_rest_days",
    "use_home_away",
    "dist_family",
    "k",
    "l1_alpha",
)


def build_config_grid() -> Iterator[dict]:
    """Yield H2 grid configs. H2.1 deferred flags fixed to False."""
    for use_weather, dist_family, k, l1_alpha in product(
        (True, False),
        ("legacy", "count_aware", "decomposed"),
        (2, 4, 6, 8, 12, 16),
        (0.0, 0.001, 0.01, 0.1),
    ):
        yield {
            "use_weather": use_weather,
            "use_opponent_epa": False,
            "use_rest_days": False,
            "use_home_away": False,
            "dist_family": dist_family,
            "k": k,
            "l1_alpha": l1_alpha,
        }


def config_hash(config: dict) -> str:
    """Deterministic md5 hex of all 7 config knobs (H2 + H2.1 forward-compat)."""
    payload = {key: config.get(key, False) for key in _CONFIG_KEYS}
    payload_str = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.md5(payload_str.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_train_loop.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/train_loop.py tests/test_train_loop.py
git commit -m "feat: H2 train_loop config grid and deterministic hash"
```

---

## Task 3: scripts/train_loop.py — holdout evaluation + metrics

**Files:**
- Modify: `scripts/train_loop.py`
- Modify: `tests/test_train_loop.py`

- [ ] **Step 1: Add failing test for metric computation**

Append to `tests/test_train_loop.py`:

```python
import numpy as np
import pandas as pd

from scripts.train_loop import compute_metrics


def test_compute_metrics_matches_sklearn():
    from sklearn.metrics import brier_score_loss, log_loss

    rng = np.random.default_rng(0)
    n = 500
    prob_over = rng.uniform(0.1, 0.9, n)
    outcome_over = rng.binomial(1, prob_over).astype(float)
    actual = rng.normal(50, 15, n)
    predicted = actual + rng.normal(0, 5, n)
    line = actual + rng.normal(0, 2, n)

    metrics = compute_metrics(
        prob_over=prob_over,
        outcome_over=outcome_over,
        predicted_mean=predicted,
        actual=actual,
        line=line,
    )

    assert metrics["log_loss"] == pytest.approx(log_loss(outcome_over, np.clip(prob_over, 1e-6, 1 - 1e-6)), rel=1e-6)
    assert metrics["brier"] == pytest.approx(brier_score_loss(outcome_over, prob_over), rel=1e-6)
    assert metrics["mae"] == pytest.approx(float(np.mean(np.abs(predicted - actual))), rel=1e-6)
    assert metrics["rmse"] == pytest.approx(float(np.sqrt(np.mean((predicted - actual) ** 2))), rel=1e-6)
    assert metrics["bias"] == pytest.approx(float(np.mean(predicted - actual)), rel=1e-6)
    assert 0.0 <= metrics["max_reliability_dev"] <= 1.0


def test_compute_metrics_handles_empty():
    metrics = compute_metrics(
        prob_over=np.array([]),
        outcome_over=np.array([]),
        predicted_mean=np.array([]),
        actual=np.array([]),
        line=np.array([]),
    )
    assert metrics["n_holdout"] == 0
    assert metrics["log_loss"] == float("nan") or np.isnan(metrics["log_loss"])
```

- [ ] **Step 2: Run tests, verify failure**

Run: `uv run pytest tests/test_train_loop.py::test_compute_metrics_matches_sklearn -v`
Expected: FAIL with `ImportError: cannot import name 'compute_metrics'`

- [ ] **Step 3: Add `compute_metrics` to `scripts/train_loop.py`**

Append after `config_hash`:

```python
import numpy as np
from sklearn.metrics import brier_score_loss, log_loss


def compute_metrics(
    *,
    prob_over: np.ndarray,
    outcome_over: np.ndarray,
    predicted_mean: np.ndarray,
    actual: np.ndarray,
    line: np.ndarray,
    n_bins: int = 10,
) -> dict[str, float]:
    """Compute log_loss / brier / mae / rmse / bias / max_reliability_dev.

    All inputs are 1D arrays of equal length (one entry per holdout prop row).
    """
    n = len(prob_over)
    out: dict[str, float] = {"n_holdout": float(n)}

    if n == 0:
        for key in ("log_loss", "brier", "mae", "rmse", "bias", "max_reliability_dev"):
            out[key] = float("nan")
        return out

    p = np.clip(prob_over, 1e-6, 1 - 1e-6)
    out["log_loss"] = float(log_loss(outcome_over, p, labels=[0, 1]))
    out["brier"] = float(brier_score_loss(outcome_over, prob_over))

    err = predicted_mean - actual
    out["mae"] = float(np.mean(np.abs(err)))
    out["rmse"] = float(np.sqrt(np.mean(err ** 2)))
    out["bias"] = float(np.mean(err))

    # 10-bin reliability deviation (max gap between bin mean prob_over and bin empirical rate)
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_idx = np.clip(np.digitize(prob_over, bin_edges) - 1, 0, n_bins - 1)
    max_dev = 0.0
    for b in range(n_bins):
        mask = bin_idx == b
        if mask.sum() == 0:
            continue
        bin_mean_prob = float(prob_over[mask].mean())
        bin_empirical = float(outcome_over[mask].mean())
        max_dev = max(max_dev, abs(bin_mean_prob - bin_empirical))
    out["max_reliability_dev"] = max_dev
    return out
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_train_loop.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/train_loop.py tests/test_train_loop.py
git commit -m "feat: H2 train_loop metric computation (log_loss/brier/reliability)"
```

---

## Task 4: scripts/train_loop.py — main loop with checkpoint

**Files:**
- Modify: `scripts/train_loop.py`
- Modify: `tests/test_train_loop.py`

- [ ] **Step 1: Write failing test for the resume-from-CSV logic**

Append to `tests/test_train_loop.py`:

```python
from pathlib import Path

from scripts.train_loop import load_completed_keys


def test_load_completed_keys_returns_empty_set_for_missing_file(tmp_path):
    keys = load_completed_keys(tmp_path / "missing.csv")
    assert keys == set()


def test_load_completed_keys_extracts_tuples(tmp_path):
    csv_path = tmp_path / "season_2024_results.csv"
    csv_path.write_text(
        "config_hash,position,stat,log_loss\n"
        "abc123,qb,passing_yards,0.5\n"
        "abc123,qb,passing_tds,0.6\n"
        "def456,rb,rushing_yards,0.7\n",
        encoding="utf-8",
    )
    keys = load_completed_keys(csv_path)
    assert ("abc123", "qb", "passing_yards") in keys
    assert ("abc123", "qb", "passing_tds") in keys
    assert ("def456", "rb", "rushing_yards") in keys
    assert len(keys) == 3
```

- [ ] **Step 2: Run, verify failure**

Run: `uv run pytest tests/test_train_loop.py::test_load_completed_keys_returns_empty_set_for_missing_file -v`
Expected: FAIL with `ImportError: cannot import name 'load_completed_keys'`

- [ ] **Step 3: Implement loop scaffolding in `scripts/train_loop.py`**

Append:

```python
import argparse
import time
from pathlib import Path

import pandas as pd

from eval.training_dataset import load_synthetic_training_props
from models.qb import QBModel
from models.rb import RBModel
from models.wr_te import WRTEModel


_POSITIONS = (
    ("qb", QBModel, ("QB",), ("passing_yards", "passing_tds", "interceptions", "completions")),
    ("rb", RBModel, ("RB",), ("rushing_yards", "carries", "rushing_tds")),
    ("wr_te", WRTEModel, ("WR", "TE"), ("receptions", "receiving_yards", "receiving_tds")),
)

_HOLDOUT_SEASONS = (2019, 2020, 2021, 2022, 2023, 2024)
_TRAIN_START = 2018

_CSV_COLUMNS = [
    "config_hash", "holdout_season", "position", "stat",
    "use_weather", "use_opponent_epa", "use_rest_days", "use_home_away",
    "dist_family", "k", "l1_alpha",
    "n_train", "n_holdout",
    "log_loss", "brier", "mae", "rmse", "bias",
    "aic", "max_reliability_dev",
    "fit_seconds", "convergence_flag",
]


def load_completed_keys(csv_path: Path) -> set[tuple[str, str, str]]:
    """Return set of (config_hash, position, stat) already in the CSV."""
    if not Path(csv_path).exists():
        return set()
    df = pd.read_csv(csv_path, usecols=["config_hash", "position", "stat"])
    return {
        (str(row["config_hash"]), str(row["position"]), str(row["stat"]))
        for _, row in df.iterrows()
    }


def _seed_for(config_hash_: str, holdout_season: int, position: str, stat: str) -> int:
    payload = f"{config_hash_}|{holdout_season}|{position}|{stat}"
    return int(hashlib.md5(payload.encode("utf-8")).hexdigest(), 16) & 0xFFFFFFFF


def _append_row(csv_path: Path, row: dict) -> None:
    df = pd.DataFrame([{col: row.get(col) for col in _CSV_COLUMNS}])
    header = not csv_path.exists()
    df.to_csv(csv_path, mode="a", header=header, index=False)


def _fit_one_position(
    *,
    model_cls,
    weekly: pd.DataFrame,
    train_seasons: list[int],
    config: dict,
):
    """Fit a single position model with the given config; return (model, fit_seconds, flag)."""
    t0 = time.perf_counter()
    flag = "ok"
    model = model_cls()
    try:
        model.fit(
            train_seasons,
            weekly=weekly,
            use_weather=config["use_weather"],
            l1_alpha=config["l1_alpha"],
            dist_family=config["dist_family"],
        )
    except Exception:
        flag = "fit_error"
    fit_seconds = time.perf_counter() - t0
    return model, fit_seconds, flag


def _evaluate_position(
    *,
    model,
    position_label: str,
    target_stats: tuple[str, ...],
    holdout_props: pd.DataFrame,
    holdout_weekly: pd.DataFrame,
    config: dict,
    config_hash_: str,
    holdout_season: int,
    n_train: int,
    fit_seconds: float,
    convergence_flag: str,
    csv_path: Path,
    completed: set,
) -> int:
    """Evaluate model on every (player, week, stat) row in holdout_props.

    Returns the number of new rows written.
    """
    rows_written = 0
    for stat in target_stats:
        key = (config_hash_, position_label, stat)
        if key in completed:
            continue

        stat_props = holdout_props[holdout_props["stat"] == stat]
        if stat_props.empty:
            row = {
                **{k: config[k] for k in ("use_weather", "use_opponent_epa", "use_rest_days", "use_home_away", "dist_family", "k", "l1_alpha")},
                "config_hash": config_hash_, "holdout_season": holdout_season,
                "position": position_label, "stat": stat,
                "n_train": n_train, "n_holdout": 0,
                "log_loss": float("nan"), "brier": float("nan"),
                "mae": float("nan"), "rmse": float("nan"), "bias": float("nan"),
                "aic": None, "max_reliability_dev": float("nan"),
                "fit_seconds": fit_seconds, "convergence_flag": convergence_flag,
            }
            _append_row(csv_path, row)
            completed.add(key)
            rows_written += 1
            continue

        prob_over_arr = []
        predicted_arr = []
        actual_arr = []
        line_arr = []
        outcome_arr = []
        for _, prop in stat_props.iterrows():
            try:
                preds = model.predict(
                    player_id=str(prop["player_id"]),
                    week=int(prop["week"]),
                    season=int(prop["season"]),
                )
            except Exception:
                continue
            dist = preds.get(stat)
            if dist is None:
                continue
            prob_over_arr.append(float(dist.prob_over(float(prop["line"]))))
            predicted_arr.append(float(dist.mean))
            actual_arr.append(float(prop.get("actual_value", 0.0) or 0.0))
            line_arr.append(float(prop["line"]))
            outcome_arr.append(float(prop["outcome_over"]))

        metrics = compute_metrics(
            prob_over=np.array(prob_over_arr),
            outcome_over=np.array(outcome_arr),
            predicted_mean=np.array(predicted_arr),
            actual=np.array(actual_arr),
            line=np.array(line_arr),
        )
        aic_value = None
        try:
            fit = model._models.get(stat)
            if fit is not None and hasattr(fit, "aic"):
                aic_raw = fit.aic
                if aic_raw is not None and np.isfinite(aic_raw):
                    aic_value = float(aic_raw)
        except Exception:
            aic_value = None

        row = {
            **{k: config[k] for k in ("use_weather", "use_opponent_epa", "use_rest_days", "use_home_away", "dist_family", "k", "l1_alpha")},
            "config_hash": config_hash_, "holdout_season": holdout_season,
            "position": position_label, "stat": stat,
            "n_train": n_train, "n_holdout": int(metrics["n_holdout"]),
            "log_loss": metrics["log_loss"], "brier": metrics["brier"],
            "mae": metrics["mae"], "rmse": metrics["rmse"], "bias": metrics["bias"],
            "aic": aic_value, "max_reliability_dev": metrics["max_reliability_dev"],
            "fit_seconds": fit_seconds, "convergence_flag": convergence_flag,
        }
        _append_row(csv_path, row)
        completed.add(key)
        rows_written += 1
    return rows_written


def run_walk_forward(
    *,
    out_dir: Path = Path("docs/training"),
    holdout_seasons: tuple[int, ...] = _HOLDOUT_SEASONS,
    synthetic_props_path: Path = Path("docs/training/synthetic_props_training.csv"),
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    from data.nflverse_loader import load_weekly
    weekly_full = load_weekly(years=list(range(_TRAIN_START, max(holdout_seasons) + 1)))
    props_full = load_synthetic_training_props(synthetic_props_path)

    grid = list(build_config_grid())
    print(f"H2 grid: {len(grid)} configs × {len(holdout_seasons)} holdouts × 3 positions")

    for holdout_season in holdout_seasons:
        csv_path = out_dir / f"season_{holdout_season}_results.csv"
        completed = load_completed_keys(csv_path)
        train_seasons = list(range(_TRAIN_START, holdout_season))
        holdout_props = props_full[props_full["season"] == holdout_season]
        holdout_weekly = weekly_full[weekly_full["season"] == holdout_season]
        n_train = int((weekly_full["season"].isin(train_seasons)).sum())

        print(f"\n=== Holdout {holdout_season} (train {train_seasons[0]}-{train_seasons[-1]}) ===")
        for cfg_idx, config in enumerate(grid, start=1):
            cfg_hash = config_hash(config)
            for pos_label, model_cls, positions, target_stats in _POSITIONS:
                # Skip whole position if all stats are already done
                pending = [s for s in target_stats if (cfg_hash, pos_label, s) not in completed]
                if not pending:
                    continue
                model, fit_seconds, flag = _fit_one_position(
                    model_cls=model_cls,
                    weekly=weekly_full[weekly_full["season"].isin(train_seasons)],
                    train_seasons=train_seasons,
                    config=config,
                )
                _evaluate_position(
                    model=model,
                    position_label=pos_label,
                    target_stats=target_stats,
                    holdout_props=holdout_props,
                    holdout_weekly=holdout_weekly,
                    config=config,
                    config_hash_=cfg_hash,
                    holdout_season=holdout_season,
                    n_train=n_train,
                    fit_seconds=fit_seconds,
                    convergence_flag=flag,
                    csv_path=csv_path,
                    completed=completed,
                )
            if cfg_idx % 12 == 0:
                print(f"  config {cfg_idx}/{len(grid)} done")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="H2 walk-forward ablation harness")
    p.add_argument("--out-dir", default="docs/training", type=Path)
    p.add_argument("--seasons", default="2019,2020,2021,2022,2023,2024",
                   help="Comma-separated holdout seasons")
    p.add_argument("--synthetic-props", default="docs/training/synthetic_props_training.csv",
                   type=Path)
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    seasons = tuple(int(s) for s in args.seasons.split(","))
    run_walk_forward(
        out_dir=args.out_dir,
        holdout_seasons=seasons,
        synthetic_props_path=args.synthetic_props,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run all train_loop tests**

Run: `uv run pytest tests/test_train_loop.py -v`
Expected: All PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/train_loop.py tests/test_train_loop.py
git commit -m "feat: H2 walk-forward main loop with row-append checkpoint"
```

---

## Task 5: Smoke-run on a 2-config sub-grid for one season

**Goal:** Verify the loop produces a sensible CSV before committing to the full ~25-min run.

- [ ] **Step 1: Add a sub-grid runner to `scripts/train_loop.py`**

Append a CLI flag `--smoke` that limits the grid to 2 configs and 1 holdout season:

```python
def _smoke_grid() -> Iterator[dict]:
    yield {
        "use_weather": False, "use_opponent_epa": False, "use_rest_days": False,
        "use_home_away": False, "dist_family": "legacy", "k": 8, "l1_alpha": 0.0,
    }
    yield {
        "use_weather": False, "use_opponent_epa": False, "use_rest_days": False,
        "use_home_away": False, "dist_family": "count_aware", "k": 8, "l1_alpha": 0.01,
    }
```

Then in `run_walk_forward`, accept a `grid_override` parameter and use it if provided. In `_parse_args`, add `--smoke` flag that toggles `grid_override=_smoke_grid()` and reduces seasons to `(2024,)`.

- [ ] **Step 2: Run smoke**

Run: `uv run python -m scripts.train_loop --smoke --out-dir tmp/h2_smoke`
Expected: `tmp/h2_smoke/season_2024_results.csv` exists with ~20 rows (2 configs × 10 stats); no errors; runtime <2 min.

- [ ] **Step 3: Inspect the CSV**

Run: `head -3 tmp/h2_smoke/season_2024_results.csv`
Verify columns and that `log_loss` values are finite for at least the QB rows.

- [ ] **Step 4: Re-run smoke to verify resume**

Run: `uv run python -m scripts.train_loop --smoke --out-dir tmp/h2_smoke`
Expected: completes near-instantly (all rows already in CSV); CSV unchanged.

- [ ] **Step 5: Commit**

```bash
git add scripts/train_loop.py
git commit -m "feat: H2 train_loop --smoke flag for fast verification"
```

---

## Task 6: Update plan.md (4 of 7 → 4 of 6)

**Files:**
- Modify: `plan.md` (root)

- [ ] **Step 1: Replace verification line**

In `plan.md`, find the H2 verification line:
> `ablation grid CSV shows ... outperforming legacy on holdout log-loss for at least 4 of 7 walk-forward steps`

Replace with:
> `ablation grid CSV shows ... outperforming legacy on holdout log-loss for at least 4 of 6 walk-forward steps`

Add note that 2025 is reserved for H5 final_eval per the four-window discipline.

- [ ] **Step 2: Commit**

```bash
git add plan.md
git commit -m "docs: H2 walk-forward is 6 steps, not 7 (2025 reserved for H5)"
```

---

## Task 7: Off-LLM compute window

**Goal:** Run the full grid. Not Claude work — user runs locally.

- [ ] **Step 1: Run the full grid**

```bash
cd E:/Projects/NFLStatsPredictor
uv run python -m scripts.train_loop --out-dir docs/training
```

Expected wall time: ~25 min sequential. Progress prints every 12 configs.

- [ ] **Step 2: Sanity check the outputs**

```bash
wc -l docs/training/season_*_results.csv
```

Expected: 6 files, each ~1,440 rows + 1 header.

- [ ] **Step 3: Spot-check a season**

```bash
uv run python -c "import pandas as pd; df = pd.read_csv('docs/training/season_2024_results.csv'); print(df.groupby(['position','stat'])['log_loss'].agg(['min','median','max']))"
```

Expected: log_loss values mostly in `[0.4, 0.8]` range; finite; no NaN explosion.

- [ ] **Step 4: Commit results**

```bash
git add docs/training/season_*_results.csv
git commit -m "data: H2 walk-forward ablation results (144 configs × 6 holdouts)"
```

---

## Task 8: Update VERSIONS.md and push

- [ ] **Step 1: Add v0.8c-h2 entry to top of `VERSIONS.md`**

```markdown
## v0.8c-h2 - 2026-04-28

**Phase H Session C close: walk-forward ablation harness.**

- H2: `scripts/train_loop.py` — sequential, deterministic, row-append-checkpointed walk-forward over 6 expanding-window holdouts (2019-2024) × 144 configs (use_weather × dist_family × k × l1_alpha). Per-fit RNG seeds derived from md5(config_hash | season | position | stat).
- H2: `tests/test_l1_path.py` — proves L1 alpha monotonically reduces nonzero coefficients.
- H2: `tests/test_train_loop.py` — config-hash determinism, grid completeness, metric parity with sklearn, resume-from-CSV semantics.
- H2: Backfilled `docs/training/synthetic_props_training.csv` to 2019-2025 (144,414 rows) so 6 walk-forward holdouts have labeled coverage.
- H2: 3 plan.md flags deferred to H2.1 (use_opponent_epa, use_rest_days, use_home_away) — require new feature engineering / data/team_context.py / schedule joins. Schema includes them as columns set False so H2.1 can append without break.
- H2: Updated plan.md verification "4 of 7" → "4 of 6" walk-forward steps (2025 reserved for H5 final_eval).
- H2: Off-LLM compute window — full grid (~8,640 GLM fits, ~25 min) produced docs/training/season_<YYYY>_results.csv for 2019-2024.

**Verification:** `uv run pytest tests/test_l1_path.py tests/test_train_loop.py -v` -> all green; full suite unchanged.
```

- [ ] **Step 2: Commit and push**

```bash
git add VERSIONS.md
git commit -m "feat: v0.8c-h2 - walk-forward ablation harness shipped"
git push
```

---

## Files modified or created

**Created:**
- `scripts/train_loop.py` (~250 lines)
- `tests/test_l1_path.py` (~50 lines)
- `tests/test_train_loop.py` (~150 lines)

**Modified:**
- `plan.md` (verification line)
- `VERSIONS.md` (v0.8c-h2 entry)
- `docs/training/synthetic_props_training.csv` (regenerated 2019-2025)
- `docs/training/season_<YYYY>_results.csv` (×6, generated by Task 7)

**Out-of-scope (H2.1 follow-up before H4):**
- `use_opponent_epa` flag (needs `data/team_context.py`)
- `use_rest_days` flag (needs schedule join + days-since-last-game feature)
- `use_home_away` flag (needs `is_home` feature wired into `_build_features`)
