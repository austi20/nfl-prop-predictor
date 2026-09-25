"""Leave-one-season-out comparison of shrinkage rules on every metric that matters.

nMAE          accuracy
topform bias  bias on the high-usage players Kalshi actually lists
early bias    same, restricted to weeks <= 5 (where the old rule collapsed)
slope err     |calibration slope - 1|; >1 means predictions too compressed
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import warnings; warnings.filterwarnings("ignore")
import json
import numpy as np, pandas as pd

SRC = sys.argv[1] if len(sys.argv) > 1 else "docs/diag/ingredients_wf8.parquet"
PROP_STATS = {"passing_yards","passing_tds","completions","attempts",
              "rushing_yards","carries","receiving_yards","receptions"}
d = pd.read_parquet(SRC)
d = d[np.isfinite(d[["raw_glm","prior_mean","actual"]]).all(axis=1)].copy()
d["trailing"] = d["trailing"].fillna(0.0)
d["anchor"] = np.where(d["trailing"] > 1e-3, d["trailing"], d["prior_mean"])
d = d[d.n >= 1]
seasons = sorted(d.season.unique())

def fit_p1(g):
    x=(g["raw_glm"]-g["prior_mean"]).to_numpy(float); y=(g["actual"]-g["prior_mean"]).to_numpy(float)
    den=float((x*x).sum()); return float((x*y).sum()/den) if den>1e-12 else 1.0
def fit_p2(g):
    x=(g["raw_glm"]-g["anchor"]).to_numpy(float); y=(g["actual"]-g["anchor"]).to_numpy(float)
    den=float((x*x).sum()); return float((x*y).sum()/den) if den>1e-12 else 1.0
def fit_p3(g):
    X=np.column_stack([(g["raw_glm"]-g["prior_mean"]).to_numpy(float),
                       (g["anchor"]-g["prior_mean"]).to_numpy(float)])
    y=(g["actual"]-g["prior_mean"]).to_numpy(float)
    try:
        c,*_=np.linalg.lstsq(X,y,rcond=None); return float(c[0]),float(c[1])
    except Exception:
        return 1.0,0.0

RULES = {
  "P0 current n/(n+2)": lambda g,p: g["prior_mean"]+(g["n"]/(g["n"]+2.0))*(g["raw_glm"]-g["prior_mean"]),
  "c=4 (shipped today)": lambda g,p: g["prior_mean"]+((g["n"]+4)/(g["n"]+6.0))*(g["raw_glm"]-g["prior_mean"]),
  "P1 per-stat w, prior": lambda g,p: g["prior_mean"]+p["p1"]*(g["raw_glm"]-g["prior_mean"]),
  "P2 per-stat w, trail": lambda g,p: g["anchor"]+p["p2"]*(g["raw_glm"]-g["anchor"]),
  "P3 glm+trail blend": lambda g,p: g["prior_mean"]+p["p3"][0]*(g["raw_glm"]-g["prior_mean"])
                                    +p["p3"][1]*(g["anchor"]-g["prior_mean"]),
}

def metrics(p, g):
    a=g["actual"].to_numpy(float); p=np.asarray(p,float); ok=np.isfinite(p)&np.isfinite(a)
    a,p=a[ok],p[ok]
    if len(a)<40 or p.std()<1e-9 or a.mean()<=1e-6: return None
    out={"nmae":np.abs(p-a).mean()/a.mean(),
         "slope_err":abs(np.polyfit(p,a,1)[0]-1)}
    anc=g["anchor"].to_numpy(float)[ok]; wk=g["week"].to_numpy()[ok]
    try: q=pd.qcut(anc,5,labels=False,duplicates="drop")
    except ValueError: return out
    hm=q==np.nanmax(q)
    if hm.sum()>25: out["tf"]=(p[hm].mean()-a[hm].mean())/a[hm].mean()
    e=hm&(wk<=5)
    if e.sum()>20: out["tf_early"]=(p[e].mean()-a[e].mean())/a[e].mean()
    return out

acc={k:{m:[] for m in ("nmae","slope_err","tf","tf_early")} for k in RULES}
acc_prop={k:{m:[] for m in ("nmae","slope_err","tf","tf_early")} for k in RULES}
weights={}
for (mo,st),g in d.groupby(["model","stat"]):
    if g["actual"].mean()<=1e-6 or len(g)<400: continue
    _a3,_b3=fit_p3(g)
    weights[f"{mo}/{st}"]={"p1":fit_p1(g),"p2":fit_p2(g),"p3_glm":_a3,"p3_trail":_b3,"n":len(g)}
    for s in seasons:
        tr,va=g[g.season!=s],g[g.season==s]
        if len(va)<40: continue
        p={"p1":fit_p1(tr),"p2":fit_p2(tr),"p3":fit_p3(tr)}
        for name,fn in RULES.items():
            m=metrics(fn(va,p),va)
            if not m: continue
            for key,val in m.items():
                acc[name][key].append(val)
                if st in PROP_STATS: acc_prop[name][key].append(val)

def show(title, store):
    print(f"\n=== {title} ===")
    print(f"{'rule':24s} {'nMAE':>8s} {'slope err':>10s} {'|topform|':>10s} {'|tf wk<=5|':>11s}")
    for name in RULES:
        s=store[name]
        print(f"{name:24s} {np.mean(s['nmae']):8.4f} {np.mean(s['slope_err']):10.4f} "
              f"{np.mean(np.abs(s['tf'])):9.1%} {np.mean(np.abs(s['tf_early'])):10.1%}")
show(f"ALL STATS, leave-one-season-out over {seasons}", acc)
show("PROP-BOARD STATS ONLY", acc_prop)
json.dump(weights, open("docs/diag/per_stat_weights.json","w"), indent=2)
print(f"\nwrote docs/diag/per_stat_weights.json ({len(weights)} stats)")
