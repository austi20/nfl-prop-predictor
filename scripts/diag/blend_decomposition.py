"""How much weight does trailing form actually deserve, next to the GLM?

The prop path is 100% GLM. The fantasy path is ~65% trailing form / 35% GLM
(glm_blend_weight) before context factors. They disagree about the same player
because of that, not because of any bug. Least squares can adjudicate:

    actual - prior ~ a*(glm - prior) + b*(trailing - prior)

a is the weight the GLM earns, b the weight trailing form earns, both out of
sample. Fit per stat on walk-forward rows.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd

SRC = sys.argv[1] if len(sys.argv) > 1 else "docs/diag/ingredients_wf8.parquet"
PROP = {"passing_yards","passing_tds","completions","attempts",
        "rushing_yards","carries","receiving_yards","receptions"}
d = pd.read_parquet(SRC)
d = d[np.isfinite(d[["raw_glm","prior_mean","actual"]]).all(axis=1)].copy()
d["trailing"] = d["trailing"].fillna(0.0)
d = d[(d.n >= 1) & (d.trailing > 1e-3)]
seasons = sorted(d.season.unique())

print(f"rows={len(d)} seasons={seasons}\n")
print("optimal weights, out of sample (leave-one-season-out mean)")
print("a = weight on GLM deviation, b = weight on trailing-form deviation\n")
print(f"{'stat':24s} {'a (GLM)':>9s} {'b (trail)':>10s} {'a+b':>7s} {'implied trail share':>20s}")
for (mo, st), g in d.groupby(["model", "stat"]):
    if g["actual"].mean() <= 1e-6 or len(g) < 400: continue
    A, B = [], []
    for s in seasons:
        tr = g[g.season != s]
        X = np.column_stack([(tr["raw_glm"]-tr["prior_mean"]).to_numpy(float),
                             (tr["trailing"]-tr["prior_mean"]).to_numpy(float)])
        y = (tr["actual"]-tr["prior_mean"]).to_numpy(float)
        try:
            c, *_ = np.linalg.lstsq(X, y, rcond=None)
            A.append(c[0]); B.append(c[1])
        except Exception:
            pass
    if not A: continue
    a, b = float(np.mean(A)), float(np.mean(B))
    share = b/(a+b) if abs(a+b) > 1e-9 else np.nan
    tag = "  <- prop stat" if st in PROP else ""
    print(f"{mo+'/'+st:24s} {a:9.3f} {b:10.3f} {a+b:7.3f} {share:19.1%}{tag}")
print("\nfantasy path currently gives trailing ~65% (glm_blend_weight=0.35).")
print("prop path gives trailing 0%.")
