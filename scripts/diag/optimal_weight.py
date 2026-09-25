"""Empirically optimal shrinkage weight per stat, per n.

predict() computes  shrunk = prior + w(n) * (raw_glm - prior)  with w = n/(n+k).
The w that minimises squared error is recoverable by least squares through the
origin on the centred variables -- no objective function to hand-tune:

    (actual - prior) = w * (raw_glm - prior) + eps
    w_hat = sum[(raw-prior)(actual-prior)] / sum[(raw-prior)^2]

Comparing w_hat against the w the code uses says directly, per stat and per
week, whether the model over- or under-shrinks.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import sys
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd

SRC = sys.argv[1] if len(sys.argv) > 1 else "docs/diag/ingredients_wf.parquet"
d = pd.read_parquet(SRC)
d = d[np.isfinite(d[["raw_glm", "prior_mean", "actual"]]).all(axis=1)].copy()
d = d[d.n >= 1]

def w_hat(g):
    x = (g["raw_glm"] - g["prior_mean"]).to_numpy(float)
    y = (g["actual"] - g["prior_mean"]).to_numpy(float)
    den = float((x * x).sum())
    if den <= 1e-12 or len(x) < 40: return np.nan, len(x)
    return float((x * y).sum() / den), len(x)

K_CUR, C_CUR = 2.0, 0.0
print(f"source={SRC}  rows={len(d)}  seasons={sorted(d.season.unique())}\n")
print("w_hat = empirically optimal weight on the GLM's deviation from the league prior")
print("w_cur = what the code uses today, n/(n+2)\n")
rows = []
for (mo, st), g in d.groupby(["model", "stat"]):
    if g["actual"].mean() <= 1e-6: continue
    all_w, n_all = w_hat(g)
    if not np.isfinite(all_w): continue
    line = f"{mo+'/'+st:24s} n={n_all:6d}  w_hat(all)={all_w:6.3f}"
    per_n = {}
    for nb, lab in [((1,1),"n=1"), ((2,3),"n=2-3"), ((4,7),"n=4-7"), ((8,20),"n=8+")]:
        sub = g[(g.n >= nb[0]) & (g.n <= nb[1])]
        wv, cnt = w_hat(sub)
        if np.isfinite(wv):
            nmid = sub["n"].median()
            wcur = nmid / (nmid + K_CUR)
            per_n[lab] = (wv, wcur, cnt)
            line += f"   {lab}: {wv:5.2f} (code {wcur:4.2f})"
    print(line)
    rows.append(dict(model=mo, stat=st, w_all=all_w, n=n_all,
                     **{f"w_{k}": v[0] for k, v in per_n.items()},
                     **{f"code_{k}": v[1] for k, v in per_n.items()}))
res = pd.DataFrame(rows)
res.to_csv("docs/diag/optimal_weight.csv", index=False)

print("\n=== implied k per stat, solving w_hat = n/(n+k) at each n bucket ===")
print("(k < 2 means the code shrinks too hard; k > 2 means not hard enough)\n")
print(f"{'stat':24s} " + "".join(f"{l:>12s}" for l in ["n=1","n=2-3","n=4-7","n=8+"]) + f"{'median k':>11s}")
for _, r in res.iterrows():
    ks, cells = [], []
    for lab, nmid in [("n=1",1),("n=2-3",2.5),("n=4-7",5.5),("n=8+",11)]:
        w = r.get(f"w_{lab}", np.nan)
        if not np.isfinite(w) or w <= 0.01 or w >= 0.999:
            cells.append(f"{'--':>12s}"); continue
        k = nmid * (1 - w) / w
        ks.append(k); cells.append(f"{k:12.2f}")
    med = np.median(ks) if ks else np.nan
    print(f"{r['model']+'/'+r['stat']:24s} " + "".join(cells) + f"{med:11.2f}")
