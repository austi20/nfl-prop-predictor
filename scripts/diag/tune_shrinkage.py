import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import warnings; warnings.filterwarnings("ignore")
import itertools, numpy as np, pandas as pd

d = pd.read_parquet("docs/diag/ingredients_wf.parquet")
d = d[np.isfinite(d[["raw_glm","prior_mean","actual"]]).all(axis=1)].copy()
d["trailing"] = d["trailing"].fillna(0.0)
d["anchor"] = np.where(d["trailing"] > 1e-3, d["trailing"], d["prior_mean"])
d = d[d["actual"].notna()]

TRAIN = d[d.season.isin([2022, 2023, 2024])]
VALID = d[d.season == 2025]
print(f"train rows={len(TRAIN)} valid rows={len(VALID)}")

def predict(g, alpha, c, k, lo, hi):
    target = alpha * g["anchor"] + (1 - alpha) * g["prior_mean"]
    ne = g["n"] + c
    w = ne / (ne + k)
    m = target + w * (g["raw_glm"] - target)
    if lo is not None:
        m = np.clip(m, lo * g["anchor"], hi * g["anchor"])
    return np.asarray(m, dtype=float)

def evaluate(df, alpha, c, k, lo, hi):
    """Scale-normalized MAE + top-form bias, averaged over stats; early-week bias tracked."""
    nmaes, tf_all, tf_early, slopes = [], [], [], []
    for (mo, st), g in df.groupby(["model", "stat"]):
        a = g["actual"].to_numpy(float)
        if a.mean() <= 1e-6 or len(g) < 100: continue
        p = predict(g, alpha, c, k, lo, hi)
        ok = np.isfinite(p) & np.isfinite(a)
        if ok.sum() < 100 or p[ok].std() < 1e-9: continue
        nmaes.append(np.abs(p - a)[ok].mean() / a.mean())
        slopes.append(abs(np.polyfit(p[ok], a[ok], 1)[0] - 1))
        q = pd.qcut(g["anchor"], 5, labels=False, duplicates="drop")
        hi_m = (q == np.nanmax(q)).to_numpy()
        if hi_m.sum() > 30:
            tf_all.append((p[hi_m].mean() - a[hi_m].mean()) / a[hi_m].mean())
            e = hi_m & (g["week"].to_numpy() <= 4)
            if e.sum() > 20:
                tf_early.append((p[e].mean() - a[e].mean()) / a[e].mean())
    return (float(np.mean(nmaes)), float(np.mean(np.abs(tf_all))),
            float(np.mean(np.abs(tf_early))), float(np.mean(slopes)))

GRID = list(itertools.product(
    [0.0, 0.25, 0.5, 0.75, 1.0],      # alpha: shrink target
    [0, 1, 2, 4, 8],                   # c: prior-season credit
    [1.0, 2.0, 4.0],                   # k
    [(None, None), (0.4, 1.8), (0.25, 2.5)]))

rows = []
for alpha, c, k, (lo, hi) in GRID:
    nmae, tf, tfe, sl = evaluate(TRAIN, alpha, c, k, lo, hi)
    rows.append(dict(alpha=alpha, c=c, k=k, clamp=f"{lo}-{hi}",
                     nmae=nmae, tf_bias=tf, tf_early=tfe, slope_err=sl,
                     obj=nmae + 0.5 * tfe + 0.25 * tf))
r = pd.DataFrame(rows).sort_values("obj")
r.to_csv("docs/diag/tune_grid.csv", index=False)
print("\n=== TOP 12 on TRAIN (2022-2024), objective = nMAE + 0.5*|early topform bias| + 0.25*|topform bias| ===")
print(r.head(12).to_string(index=False, float_format=lambda v: f"{v:7.4f}"))
base = r[(r.alpha==0.0)&(r.c==0)&(r.k==2.0)&(r.clamp=="None-None")]
print("\n=== CURRENT PRODUCTION (alpha=0, c=0, k=2, no clamp) ===")
print(base.to_string(index=False, float_format=lambda v: f"{v:7.4f}"))
print(f"\ncurrent rank on train: {r.reset_index(drop=True).index[(r.reset_index(drop=True).alpha==0.0)&(r.reset_index(drop=True).c==0)&(r.reset_index(drop=True).k==2.0)&(r.reset_index(drop=True).clamp=='None-None')].tolist()} of {len(r)}")
