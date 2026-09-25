"""Fit the per-stat shrinkage weights that models/shrinkage_weights.json holds.

    shrunk = prior + a * (glm - prior) + b * (trailing - prior)

`a` and `b` are the least-squares solution of

    (actual - prior) ~ a * (glm - prior) + b * (trailing - prior)

i.e. the combination that minimises squared error on held-out seasons. It
replaces the old `n / (n + k)` ramp, whose dependence on same-season games
collapsed every early-season projection onto the league mean.

`b` is usually the larger of the two: a player's own trailing form earns 50-90%
of the weight on most box-score stats. The GLM contributes opponent and team
context that the trailing average cannot see.

Input is the walk-forward ingredient table (for eval season Y the models are fit
on 2015..Y-1), so every row is out of sample:

    uv run python scripts/diag/extract_walkforward.py \
        docs/diag/ingredients_wf8.parquet 2018 2019 2020 2021 2022 2023 2024 2025
    uv run python scripts/diag/fit_shrinkage_weights.py docs/diag/ingredients_wf8.parquet
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import warnings; warnings.filterwarnings("ignore")
import json
import numpy as np
import pandas as pd

SRC = sys.argv[1] if len(sys.argv) > 1 else "docs/diag/ingredients_wf8.parquet"
OUT = _ROOT / "models" / "shrinkage_weights.json"

d = pd.read_parquet(SRC)
d = d[np.isfinite(d[["raw_glm", "prior_mean", "actual"]]).all(axis=1)]
d = d[d.n >= 1]
seasons = sorted(int(s) for s in d.season.unique())


def weight(g: pd.DataFrame) -> float:
    """Weight on the GLM alone, kept for the no-trailing fallback path."""
    x = (g["raw_glm"] - g["prior_mean"]).to_numpy(float)
    y = (g["actual"] - g["prior_mean"]).to_numpy(float)
    den = float((x * x).sum())
    return float((x * y).sum() / den) if den > 1e-12 else 1.0


def blend(g: pd.DataFrame) -> tuple[float, float]:
    """(a, b): weights on the GLM and on the player's trailing form."""
    t = g[g["trailing"] > 1e-3]
    if len(t) < 200:
        return weight(g), 0.0
    X = np.column_stack([(t["raw_glm"] - t["prior_mean"]).to_numpy(float),
                         (t["trailing"] - t["prior_mean"]).to_numpy(float)])
    y = (t["actual"] - t["prior_mean"]).to_numpy(float)
    try:
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        return float(coef[0]), float(coef[1])
    except Exception:
        return weight(g), 0.0


weights: dict[str, float] = {}
blends: dict[str, list[float]] = {}
spread: dict[str, float] = {}
for (model, stat), g in d.groupby(["model", "stat"]):
    if g["actual"].mean() <= 1e-6 or len(g) < 400:
        continue
    key = f"{model}/{stat}"
    weights[key] = round(weight(g), 4)
    a, b = blend(g)
    blends[key] = [round(a, 4), round(b, 4)]
    # leave-one-season-out spread, so an unstable stat is visible in the file
    loo = [weight(g[g.season != s]) for s in seasons]
    spread[key] = round(float(np.std(loo) / max(abs(np.mean(loo)), 1e-9)), 4)

payload = {
    "_source": Path(SRC).name,
    "_seasons": seasons,
    "_fit": "least squares on (actual - prior) ~ w * (glm - prior), walk-forward rows only",
    "default": round(float(np.median(list(weights.values()))), 4),
    "weights": dict(sorted(weights.items())),
    "blend": dict(sorted(blends.items())),
    "loo_cv": dict(sorted(spread.items())),
}
OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(f"wrote {OUT}  ({len(weights)} stats, default={payload['default']})")
unstable = [k for k, v in spread.items() if v > 0.25]
print(f"unstable (LOO cv > 25%): {unstable or 'none'}")
