"""Per-stat optimal blend of GLM / trailing form / league prior, by least squares.

    actual ~ a*glm + b*trailing + (1-a-b)*prior

Equivalently, regress (actual - prior) on (glm - prior) and (trailing - prior)
with no intercept. Two free parameters per stat, fit on thousands of rows, so
unlike a grid search over a hand-built objective it does not chase noise.

Compares, out of sample by leave-one-season-out:
  P0  current production          prior + n/(n+2)*(glm-prior)
  P1  per-stat weight on glm      prior + a*(glm-prior)
  P2  per-stat weight on trailing trailing + a*(glm-trailing)
  P3  per-stat full blend         a*glm + b*trailing + (1-a-b)*prior
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import warnings; warnings.filterwarnings("ignore")
import json
import numpy as np, pandas as pd

SRC = sys.argv[1] if len(sys.argv) > 1 else "docs/diag/ingredients_wf.parquet"
d = pd.read_parquet(SRC)
d = d[np.isfinite(d[["raw_glm", "prior_mean", "actual"]]).all(axis=1)].copy()
d["trailing"] = d["trailing"].fillna(0.0)
d["anchor"] = np.where(d["trailing"] > 1e-3, d["trailing"], d["prior_mean"])
d = d[d.n >= 1]
seasons = sorted(d.season.unique())

def fit_p1(g):
    x = (g["raw_glm"]-g["prior_mean"]).to_numpy(float)
    y = (g["actual"]-g["prior_mean"]).to_numpy(float)
    den = float((x*x).sum())
    return float((x*y).sum()/den) if den > 1e-12 else 1.0

def fit_p2(g):
    x = (g["raw_glm"]-g["anchor"]).to_numpy(float)
    y = (g["actual"]-g["anchor"]).to_numpy(float)
    den = float((x*x).sum())
    return float((x*y).sum()/den) if den > 1e-12 else 1.0

def fit_p3(g):
    X = np.column_stack([(g["raw_glm"]-g["prior_mean"]).to_numpy(float),
                         (g["anchor"]-g["prior_mean"]).to_numpy(float)])
    y = (g["actual"]-g["prior_mean"]).to_numpy(float)
    try:
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        return float(coef[0]), float(coef[1])
    except Exception:
        return 1.0, 0.0

def apply(g, kind, par):
    pm, an, gl = g["prior_mean"], g["anchor"], g["raw_glm"]
    if kind == "P0":
        w = g["n"]/(g["n"]+2.0); return np.asarray(pm + w*(gl-pm), float)
    if kind == "P1": return np.asarray(pm + par*(gl-pm), float)
    if kind == "P2": return np.asarray(an + par*(gl-an), float)
    a, b = par;      return np.asarray(pm + a*(gl-pm) + b*(an-pm), float)

print(f"source={SRC}  rows={len(d)}  seasons={seasons}\n")
print("=== leave-one-season-out, scale-normalised MAE (lower better) ===")
print(f"{'stat':24s} {'P0 current':>11s} {'P1 glm/prior':>13s} {'P2 glm/trail':>13s} {'P3 blend':>10s}   best")
wins = {"P0":0,"P1":0,"P2":0,"P3":0}
params = {}
for (mo, st), g in d.groupby(["model","stat"]):
    if g["actual"].mean() <= 1e-6 or len(g) < 400: continue
    sc = {k: [] for k in ("P0","P1","P2","P3")}
    for s in seasons:
        tr, va = g[g.season != s], g[g.season == s]
        if len(va) < 40: continue
        pars = {"P0": None, "P1": fit_p1(tr), "P2": fit_p2(tr), "P3": fit_p3(tr)}
        a = va["actual"].to_numpy(float); scale = max(a.mean(), 1e-6)
        for k in sc:
            p = apply(va, k, pars[k])
            sc[k].append(np.abs(p-a).mean()/scale)
    if not sc["P0"]: continue
    m = {k: float(np.mean(v)) for k, v in sc.items()}
    best = min(m, key=m.get); wins[best] += 1
    print(f"{mo+'/'+st:24s} {m['P0']:11.4f} {m['P1']:13.4f} {m['P2']:13.4f} {m['P3']:10.4f}   {best}")
    a3, b3 = fit_p3(g)
    params[f"{mo}/{st}"] = dict(p1=fit_p1(g), p2=fit_p2(g), p3_glm=a3, p3_trail=b3,
                                n=len(g), loo_nmae={k: m[k] for k in m})
print(f"\nwins: {wins}")
print("\n=== mean LOO nMAE across stats ===")
for k in ("P0","P1","P2","P3"):
    vals = [v["loo_nmae"][k] for v in params.values()]
    print(f"  {k}: {np.mean(vals):.4f}")
json.dump(params, open("docs/diag/blend_params.json","w"), indent=2)
print("\nwrote docs/diag/blend_params.json")
