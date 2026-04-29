"""Walk-forward ablation grid for Phase H2.

144 configs x 7 holdout seasons x 10 stats = 10,080 result rows.
The loop fits 24 unique non-k configs per position/season, then evaluates all
six k-shrinkage variants from the shared fit.
Row-level checkpointing: safe to kill and resume.
Threaded by unique fit task; row-level resume still keys on config_hash/position/stat.

Usage:
    uv run python scripts/train_loop.py
    uv run python scripts/train_loop.py --seasons 2019,2020 --positions qb
    uv run python scripts/train_loop.py --out-dir docs/training/

Optional repo-root `.env`: OMP_NUM_THREADS, MKL_NUM_THREADS, OPENBLAS_NUM_THREADS,
NUMEXPR_NUM_THREADS (loaded before NumPy import — copy `.env.example`).
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


def _load_dotenv_before_numpy() -> None:
    """Load repo `.env` before NumPy/SciPy so BLAS thread env vars apply."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    path = _ROOT / ".env"
    if path.is_file():
        load_dotenv(path, override=False)


_load_dotenv_before_numpy()

import argparse
import hashlib
import itertools
import json
import os
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss as sk_log_loss

from eval.training_dataset import load_synthetic_training_props
from models.dist_family import ConstantResult
from models.qb import QBModel
from models.qb import _TARGET_STATS as QB_STATS
from models.rb import RBModel
from models.rb import _TARGET_STATS as RB_STATS
from models.wr_te import WRTEModel
from models.wr_te import _TARGET_STATS as WRTE_STATS

# ── Grid definition (144 configs) ────────────────────────────────────────────
# Schema-forward: use_opponent_epa / use_rest_days / use_home_away always False
# in H2; H2.1 will append rows to the same CSVs without schema break.
_GRID: dict[str, list[Any]] = {
    "use_weather": [True, False],
    "dist_family": ["legacy", "count_aware", "decomposed"],
    "k": [2, 4, 6, 8, 12, 16],
    "l1_alpha": [0.0, 0.001, 0.01, 0.1],
}
_DEFERRED_FLAGS = {
    "use_opponent_epa": False,
    "use_rest_days": False,
    "use_home_away": False,
}

HOLDOUT_SEASONS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]
TRAINING_START = 2018

_POSITION_MAP: dict[str, tuple[type, list[str]]] = {
    "qb": (QBModel, list(QB_STATS)),
    "rb": (RBModel, list(RB_STATS)),
    "wr_te": (WRTEModel, list(WRTE_STATS)),
}

# Synthetic CSV is keyed on these position labels
_STAT_TO_POSITION: dict[str, str] = {
    "passing_yards": "qb",
    "passing_tds": "qb",
    "interceptions": "qb",
    "completions": "qb",
    "rushing_yards": "rb",
    "carries": "rb",
    "rushing_tds": "rb",
    "receptions": "wr_te",
    "receiving_yards": "wr_te",
    "receiving_tds": "wr_te",
}


# ── Config helpers ────────────────────────────────────────────────────────────

def make_configs() -> list[dict[str, Any]]:
    configs = []
    for use_weather, dist_family, k, l1_alpha in itertools.product(
        _GRID["use_weather"],
        _GRID["dist_family"],
        _GRID["k"],
        _GRID["l1_alpha"],
    ):
        cfg: dict[str, Any] = {
            "use_weather": use_weather,
            **_DEFERRED_FLAGS,
            "dist_family": dist_family,
            "k": k,
            "l1_alpha": l1_alpha,
        }
        configs.append(cfg)
    return configs


def config_hash(cfg: dict[str, Any]) -> str:
    key = json.dumps(
        {c: cfg[c] for c in sorted(cfg)},
        sort_keys=True,
    )
    return hashlib.md5(key.encode()).hexdigest()[:16]


def fit_config_key(cfg: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    """Config identity for model fitting; k is prediction-only shrinkage."""
    return tuple((c, cfg[c]) for c in sorted(cfg) if c != "k")


def load_completed_keys(path: Path) -> set[tuple[str, str, str]]:
    if not path.exists():
        return set()
    try:
        df = pd.read_csv(path, usecols=["config_hash", "position", "stat"])
        return set(zip(df["config_hash"], df["position"], df["stat"]))
    except Exception:
        return set()


# ── Metrics helpers ───────────────────────────────────────────────────────────

def _reliability_dev(probs: np.ndarray, labels: np.ndarray, n_bins: int = 10) -> float:
    """Max |empirical_rate - mean_prob| over 10 equal-width bins on [0, 1]."""
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    max_dev = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (probs >= lo) & (probs < hi)
        if mask.sum() == 0:
            continue
        dev = abs(float(labels[mask].mean()) - float(probs[mask].mean()))
        if dev > max_dev:
            max_dev = dev
    return max_dev


def _extract_aic(model: Any, stat: str) -> float | None:
    result = getattr(model, "_models", {}).get(stat)
    if result is None:
        return None
    if isinstance(result, ConstantResult):
        return None
    aic = getattr(result, "aic", None)
    if aic is None or (isinstance(aic, float) and not np.isfinite(aic)):
        return None
    return float(aic)


def _convergence_flag(model: Any, stat: str) -> str:
    result = getattr(model, "_models", {}).get(stat)
    if result is None:
        return "fit_error"
    if isinstance(result, ConstantResult):
        return "constant_fallback"
    return "ok"


# ── Per-position fit + evaluate ───────────────────────────────────────────────

def _fit_and_evaluate_group(
    position: str,
    model_cls: type,
    target_stats: list[str],
    training_years: list[int],
    holdout_season: int,
    weekly_plain: pd.DataFrame,
    weekly_weather: pd.DataFrame,
    fit_cfg: dict[str, Any],
    eval_items: list[tuple[dict[str, Any], str, list[str]]],
    prop_rows: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Fit one non-k config and return rows for each pending k/config variant."""
    use_weather: bool = fit_cfg["use_weather"]
    weekly = weekly_weather if use_weather else weekly_plain

    t0 = time.perf_counter()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            model = model_cls()
            model.fit(
                training_years,
                weekly=weekly,
                use_weather=use_weather,
                l1_alpha=float(fit_cfg["l1_alpha"]),
                dist_family=str(fit_cfg["dist_family"]),
                k=int(fit_cfg["k"]),
            )
            fit_ok = True
        except Exception:
            model = model_cls()
            fit_ok = False
    fit_seconds = time.perf_counter() - t0

    prop_by_stat = {stat: prop_rows[prop_rows["stat"] == stat] for stat in target_stats}
    rows = []
    for cfg, chash, remaining_stats in eval_items:
        if fit_ok:
            setattr(model, "_k", int(cfg["k"]))
        predict_cache: dict[tuple[str, int, int], dict[str, Any]] = {}

        for stat in remaining_stats:
            stat_rows = prop_by_stat.get(stat, pd.DataFrame())
            n_holdout = len(stat_rows)

            if not fit_ok or n_holdout == 0:
                rows.append(_empty_row(chash, holdout_season, position, stat, cfg, fit_seconds, n_holdout))
                continue

            probs: list[float] = []
            pred_means: list[float] = []
            actual_vals: list[float] = []
            labels: list[float] = []

            for row in stat_rows.itertuples(index=False):
                player_id = str(getattr(row, "player_id"))
                week = int(getattr(row, "week"))
                season = int(getattr(row, "season"))
                line = float(getattr(row, "line"))
                actual_val = float(getattr(row, "actual_value"))
                label = float(getattr(row, "outcome_over"))

                cache_key = (player_id, week, season)
                dists = predict_cache.get(cache_key)
                if dists is None:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        try:
                            dists = model.predict(player_id, week, season)
                        except Exception:
                            dists = {}
                    predict_cache[cache_key] = dists

                dist = dists.get(stat)
                prob = float(np.clip(dist.prob_over(line), 1e-7, 1.0 - 1e-7)) if dist else 0.5
                pred_mean = dist.mean if dist else 0.0

                probs.append(prob)
                pred_means.append(pred_mean)
                actual_vals.append(actual_val)
                labels.append(label)

            probs_arr = np.array(probs, dtype=float)
            pred_means_arr = np.array(pred_means, dtype=float)
            actual_arr = np.array(actual_vals, dtype=float)
            labels_arr = np.array(labels, dtype=float)

            try:
                ll = float(sk_log_loss(labels_arr, probs_arr, labels=[0, 1]))
            except Exception:
                ll = float("nan")
            brier = float(np.mean((probs_arr - labels_arr) ** 2))
            mae = float(np.mean(np.abs(pred_means_arr - actual_arr)))
            rmse = float(np.sqrt(np.mean((pred_means_arr - actual_arr) ** 2)))
            bias = float(np.mean(pred_means_arr - actual_arr))
            max_rel_dev = _reliability_dev(probs_arr, labels_arr)

            convergence = _convergence_flag(model, stat) if fit_ok else "fit_error"
            aic = _extract_aic(model, stat)
            n_train = len(model._player_stats) if hasattr(model, "_player_stats") and model._player_stats is not None else 0

            rows.append({
                "config_hash": chash,
                "holdout_season": holdout_season,
                "position": position,
                "stat": stat,
                "use_weather": cfg["use_weather"],
                "use_opponent_epa": cfg["use_opponent_epa"],
                "use_rest_days": cfg["use_rest_days"],
                "use_home_away": cfg["use_home_away"],
                "dist_family": cfg["dist_family"],
                "k": cfg["k"],
                "l1_alpha": cfg["l1_alpha"],
                "n_train": n_train,
                "n_holdout": n_holdout,
                "log_loss": ll,
                "brier": brier,
                "mae": mae,
                "rmse": rmse,
                "bias": bias,
                "aic": aic,
                "max_reliability_dev": max_rel_dev,
                "fit_seconds": round(fit_seconds, 4),
                "convergence_flag": convergence,
            })

    return rows


def _empty_row(
    chash: str,
    holdout_season: int,
    position: str,
    stat: str,
    cfg: dict[str, Any],
    fit_seconds: float,
    n_holdout: int,
) -> dict[str, Any]:
    return {
        "config_hash": chash,
        "holdout_season": holdout_season,
        "position": position,
        "stat": stat,
        "use_weather": cfg["use_weather"],
        "use_opponent_epa": cfg["use_opponent_epa"],
        "use_rest_days": cfg["use_rest_days"],
        "use_home_away": cfg["use_home_away"],
        "dist_family": cfg["dist_family"],
        "k": cfg["k"],
        "l1_alpha": cfg["l1_alpha"],
        "n_train": 0,
        "n_holdout": n_holdout,
        "log_loss": float("nan"),
        "brier": float("nan"),
        "mae": float("nan"),
        "rmse": float("nan"),
        "bias": float("nan"),
        "aic": None,
        "max_reliability_dev": float("nan"),
        "fit_seconds": round(fit_seconds, 4),
        "convergence_flag": "fit_error",
    }


# ── Main loop ─────────────────────────────────────────────────────────────────

def run(
    seasons: list[int],
    positions: list[str],
    out_dir: Path,
    props_path: Path,
    workers: int = 16,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading synthetic training props from {props_path} ...")
    all_props = load_synthetic_training_props(props_path)
    configs = make_configs()
    print(f"Grid: {len(configs)} configs x {len(seasons)} holdout seasons")

    # Load one wide frame covering all needed years. Each fit() filters internally
    # by training_years, so passing the full frame is safe and avoids per-holdout
    # cache-key misses that trigger network fetches.
    all_years = list(range(TRAINING_START, max(seasons) + 1))
    print(f"Loading weekly data for {all_years[0]}-{all_years[-1]} (single load for all holdouts) ...")
    from data.nflverse_loader import load_weekly, load_weekly_with_weather

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        weekly_plain = load_weekly(all_years)
        weekly_weather = load_weekly_with_weather(all_years)
    print("  Weekly data loaded.")

    for holdout_season in seasons:
        out_path = out_dir / f"season_{holdout_season}_results.csv"
        completed = load_completed_keys(out_path)
        if completed:
            print(f"  [{holdout_season}] Resuming - {len(completed)} rows already done")

        training_years = list(range(TRAINING_START, holdout_season))
        holdout_props = all_props[all_props["season"] == holdout_season].copy()

        # Slice to training + holdout years only so _build_features stays fast.
        # Single load above avoids cache misses; slicing here avoids processing
        # all 7 years on every fit() call.
        fit_years = set(training_years + [holdout_season])
        holdout_weekly_plain = weekly_plain[weekly_plain["season"].isin(fit_years)].copy()
        holdout_weekly_weather = weekly_weather[weekly_weather["season"].isin(fit_years)].copy()

        n_total_slots = len(configs) * len(positions)

        # Pre-filter prop rows per position once — same for every config, read-only.
        pos_prop_cache: dict[str, pd.DataFrame] = {
            pos: holdout_props[holdout_props["stat"].isin(list(stats))].copy()
            for pos, (_, stats) in _POSITION_MAP.items()
            if pos in positions
        }

        # Separate already-done config-position slots from pending unique fit tasks.
        task_groups: dict[tuple[tuple[tuple[str, Any], ...], str], dict[str, Any]] = {}
        n_skipped = 0
        for cfg in configs:
            chash = config_hash(cfg)
            for position in positions:
                model_cls, target_stats = _POSITION_MAP[position]
                remaining_stats = [
                    s for s in target_stats
                    if (chash, position, s) not in completed
                ]
                if not remaining_stats:
                    n_skipped += 1
                else:
                    key = (fit_config_key(cfg), position)
                    group = task_groups.setdefault(
                        key,
                        {
                            "fit_cfg": cfg,
                            "position": position,
                            "model_cls": model_cls,
                            "target_stats": target_stats,
                            "eval_items": [],
                        },
                    )
                    group["eval_items"].append((cfg, chash, remaining_stats))

        n_done = n_skipped
        tasks = list(task_groups.values())
        n_pending_slots = sum(len(task["eval_items"]) for task in tasks)
        if tasks:
            actual_workers = min(workers, len(tasks))
            print(
                f"  [{holdout_season}] {n_skipped} config-position slots already done, "
                f"{n_pending_slots} pending across {len(tasks)} unique fit tasks - "
                f"{actual_workers} workers"
            )
            csv_lock = threading.Lock()
            with ThreadPoolExecutor(max_workers=actual_workers) as executor:
                future_map = {
                    executor.submit(
                        _fit_and_evaluate_group,
                        position=task["position"],
                        model_cls=task["model_cls"],
                        target_stats=task["target_stats"],
                        training_years=training_years,
                        holdout_season=holdout_season,
                        weekly_plain=holdout_weekly_plain,
                        weekly_weather=holdout_weekly_weather,
                        fit_cfg=task["fit_cfg"],
                        eval_items=task["eval_items"],
                        prop_rows=pos_prop_cache[task["position"]],
                    ): (config_hash(task["fit_cfg"]), task["position"], len(task["eval_items"]))
                    for task in tasks
                }
                for future in as_completed(future_map):
                    chash_k, pos_k, slot_count = future_map[future]
                    try:
                        result_rows = future.result()
                    except Exception as exc:
                        print(f"    WARN task ({chash_k[:8]}, {pos_k}) raised: {exc}")
                        result_rows = []
                    with csv_lock:
                        if result_rows:
                            new_df = pd.DataFrame(result_rows)
                            new_df.to_csv(
                                out_path,
                                mode="a",
                                header=not out_path.exists(),
                                index=False,
                            )
                            completed.update(
                                (r["config_hash"], r["position"], r["stat"])
                                for r in result_rows
                            )
                        n_done += slot_count
                        if n_done % 50 == 0:
                            pct = 100.0 * n_done / n_total_slots
                            print(f"    [{holdout_season}] {n_done}/{n_total_slots} ({pct:.1f}%)")

        print(f"  [{holdout_season}] Done -> {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase H2 walk-forward ablation grid")
    parser.add_argument(
        "--seasons",
        default=",".join(str(s) for s in HOLDOUT_SEASONS),
        help="Comma-separated holdout seasons (default: all 7)",
    )
    parser.add_argument(
        "--positions",
        default="qb,rb,wr_te",
        help="Comma-separated positions (default: qb,rb,wr_te)",
    )
    parser.add_argument(
        "--out-dir",
        default="docs/training",
        help="Output directory for season_YYYY_results.csv files",
    )
    parser.add_argument(
        "--props-path",
        default="docs/training/synthetic_props_training.csv",
        help="Path to synthetic training CSV",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Thread-pool workers for parallel config fits (default: min(cpu_count, 16))",
    )
    args = parser.parse_args()

    seasons = [int(s.strip()) for s in args.seasons.split(",")]
    positions = [p.strip() for p in args.positions.split(",")]
    out_dir = Path(args.out_dir)
    props_path = Path(args.props_path)
    workers = args.workers if args.workers is not None else min(os.cpu_count() or 4, 16)

    unknown_positions = set(positions) - set(_POSITION_MAP)
    if unknown_positions:
        parser.error(f"Unknown positions: {unknown_positions}. Valid: {list(_POSITION_MAP)}")

    invalid_seasons = [s for s in seasons if s not in HOLDOUT_SEASONS]
    if invalid_seasons:
        parser.error(f"Seasons outside valid holdout range {HOLDOUT_SEASONS}: {invalid_seasons}")

    run(seasons=seasons, positions=positions, out_dir=out_dir, props_path=props_path, workers=workers)


if __name__ == "__main__":
    main()
