"""Preseason baseline capture.

Computes uncalibrated Brier + log_loss per (position, stat) against the most
recent training year. Output is markdown to docs/preseason_baseline_2026.md.

Roadmap pre-gate item 5: this baseline is what P5 calibration must beat
before flipping use_calibration=True. Defined in
docs/superpowers/specs/2026-06-10-modernization-roadmap-design.md §3.

Run as a script: ``uv run python scripts/capture_preseason_baseline.py``
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from sklearn.metrics import brier_score_loss, log_loss as sk_log_loss

DEFAULT_TRAINING_CSV = Path("docs/training/synthetic_props_training.csv")
DEFAULT_OUTPUT = Path("docs/preseason_baseline_2026.md")
DEFAULT_YEAR = 2025
_TRAINING_START = 2018
_EPS = 1e-6

# Canonical stat -> position model (mirrors scripts/train_loop.py::_STAT_TO_POSITION).
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


@dataclass(frozen=True)
class BaselineRow:
    position: str
    stat: str
    n: int
    brier: float
    log_loss: float


def score_predictions(
    *,
    y_true: np.ndarray,
    y_prob: np.ndarray,
) -> tuple[float, float]:
    """Return (brier, log_loss). Clips probs to [eps, 1-eps] for log_loss stability."""
    if y_true.shape != y_prob.shape:
        raise ValueError(
            f"y_true and y_prob length mismatch: {y_true.shape} vs {y_prob.shape}"
        )
    if y_true.size == 0:
        raise ValueError("cannot score empty prediction arrays")
    if np.any(y_prob < 0.0) or np.any(y_prob > 1.0):
        raise ValueError("y_prob must be in [0, 1]")
    brier = float(brier_score_loss(y_true, y_prob))
    clipped = np.clip(y_prob, _EPS, 1.0 - _EPS)
    log_loss = float(sk_log_loss(y_true, clipped, labels=[0, 1]))
    return brier, log_loss


def format_markdown(rows: list[BaselineRow], *, year: int) -> str:
    lines: list[str] = []
    lines.append("# Preseason Baseline (uncalibrated)")
    lines.append("")
    lines.append(
        "Uncalibrated GLM performance per (position, stat) on the most recent "
        f"training year ({year}). Frozen reference for the preseason activation "
        "gate — see docs/superpowers/specs/2026-06-10-modernization-roadmap-design.md §3."
    )
    lines.append("")
    if not rows:
        lines.append("_no baseline rows — empty dataset or all positions/stats skipped._")
        return "\n".join(lines) + "\n"

    sorted_rows = sorted(rows, key=lambda r: (r.position, r.stat))
    lines.append("| position | stat | n | brier | log_loss |")
    lines.append("|---|---|---:|---:|---:|")
    for r in sorted_rows:
        lines.append(
            f"| {r.position} | {r.stat} | {r.n} | {r.brier:.4f} | {r.log_loss:.4f} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def compute_baseline_rows(
    *,
    training_csv: Path = DEFAULT_TRAINING_CSV,
    year: int = DEFAULT_YEAR,
    train_years: list[int] | None = None,
) -> list[BaselineRow]:
    """Fit the locked-default GLMs and score them against ``year``'s synthetic props.

    Fits QB/RB/WR-TE models on ``train_years`` (default 2018..year-1) with their
    H5-locked ``fit()`` defaults, then for every eligible synthetic prop row in
    ``year`` computes ``dist.prob_over(line)`` and compares to ``outcome_over``.
    Returns one BaselineRow per (position, stat) with uncalibrated Brier + log_loss.

    Returns an empty list when the training CSV is absent (keeps the CI gate,
    which only exercises the metric + formatting helpers, free of model imports).
    """
    import pandas as pd  # local: keeps test-collect fast; not needed at module level

    if not training_csv.exists():
        return []

    df = pd.read_csv(training_csv)
    if "eligible_for_training" in df.columns:
        df = df[df["eligible_for_training"].astype(bool)]
    if "season" in df.columns:
        df = df[df["season"] == year]
    df = df[df["outcome_over"].notna() & df["stat"].isin(_STAT_TO_POSITION)]
    if df.empty:
        return []

    from data.nflverse_loader import load_weekly
    from models.qb import QBModel
    from models.rb import RBModel
    from models.wr_te import WRTEModel

    train_years = train_years or list(range(_TRAINING_START, year))
    weekly = load_weekly(sorted(set(train_years) | {year}))

    model_classes = {"qb": QBModel, "rb": RBModel, "wr_te": WRTEModel}
    rows: list[BaselineRow] = []

    for position, model_cls in model_classes.items():
        stats = [s for s, p in _STAT_TO_POSITION.items() if p == position]
        pos_df = df[df["stat"].isin(stats)]
        if pos_df.empty:
            continue

        model = model_cls()
        model.fit(train_years, weekly=weekly)  # H5-locked defaults

        for stat in stats:
            stat_df = pos_df[pos_df["stat"] == stat]
            if stat_df.empty:
                continue

            predict_cache: dict[tuple[str, int, int], dict] = {}
            y_true: list[float] = []
            y_prob: list[float] = []
            for r in stat_df.itertuples(index=False):
                key = (str(r.player_id), int(r.week), int(r.season))
                dists = predict_cache.get(key)
                if dists is None:
                    try:
                        dists = model.predict(str(r.player_id), int(r.week), int(r.season))
                    except Exception:
                        dists = {}
                    predict_cache[key] = dists
                dist = dists.get(stat)
                prob = float(np.clip(dist.prob_over(float(r.line)), _EPS, 1.0 - _EPS)) if dist else 0.5
                y_prob.append(prob)
                y_true.append(float(r.outcome_over))

            true_arr = np.asarray(y_true, dtype=float)
            prob_arr = np.asarray(y_prob, dtype=float)
            if true_arr.size == 0:
                continue
            brier, ll = score_predictions(y_true=true_arr, y_prob=prob_arr)
            rows.append(
                BaselineRow(position=position, stat=stat, n=int(true_arr.size), brier=brier, log_loss=ll)
            )

    return rows


def main() -> None:
    rows = compute_baseline_rows()
    md = format_markdown(rows, year=DEFAULT_YEAR)
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT.write_text(md, encoding="utf-8")
    print(f"wrote {len(rows)} baseline rows to {DEFAULT_OUTPUT}")
    for r in sorted(rows, key=lambda x: (x.position, x.stat)):
        print(f"  {r.position:>6} {r.stat:<16} n={r.n:>5}  brier={r.brier:.4f}  log_loss={r.log_loss:.4f}")


if __name__ == "__main__":
    main()
