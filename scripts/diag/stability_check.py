import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import warnings; warnings.filterwarnings("ignore")
import itertools, numpy as np, pandas as pd

d = pd.read_parquet("docs/diag/ingredients_wf.parquet")
d = d[np.isfinite(d[["raw_glm","prior_mean","actual"]]).all(axis=1)].copy()
d["trailing"] = d["trailing"].fillna(0.0)
d["anchor"] = np.where(d["trailing"]>1e-3, d["trailing"], d["prior_mean"])

def pred(g,a_,c,k):
    t = a_*g["anchor"]+(1-a_)*g["prior_mean"]; ne=g["n"]+c
    return np.asarray(t+(ne/(ne+k))*(g["raw_glm"]-t),dtype=float)
def obj(g,a_,c,k):
    a=g["actual"].to_numpy(float); p=pred(g,a_,c,k); ok=np.isfinite(p)&np.isfinite(a)
    if ok.sum()<80 or p[ok].std()<1e-9: return None
    nmae=np.abs(p-a)[ok].mean()/a.mean(); sl=abs(np.polyfit(p[ok],a[ok],1)[0]-1)
    q=pd.qcut(g["anchor"],5,labels=False,duplicates="drop"); hm=(q==np.nanmax(q)).to_numpy()
    tf=tfe=0.0
    if hm.sum()>25:
        tf=abs((p[hm].mean()-a[hm].mean())/a[hm].mean())
        e=hm&(g["week"].to_numpy()<=4)
        if e.sum()>15: tfe=abs((p[e].mean()-a[e].mean())/a[e].mean())
    return nmae+0.5*tfe+0.25*tf+0.15*sl
GRID=list(itertools.product([0.0,0.25,0.5],[0,1,2,4,8],[0.5,1.0,2.0,4.0,8.0]))
def tune(df):
    out={}
    for (mo,st),g in df.groupby(["model","stat"]):
        if g["actual"].mean()<=1e-6 or len(g)<200: continue
        sc=[(obj(g,*p),p) for p in GRID]; sc=[(s,p) for s,p in sc if s is not None]
        if sc: out[f"{mo}/{st}"]=min(sc,key=lambda x:x[0])[1]
    return out

FOLDS = {"hold2025":[2022,2023,2024], "hold2024":[2022,2023,2025],
         "hold2023":[2022,2024,2025], "hold2022":[2023,2024,2025]}
tuned = {n: tune(d[d.season.isin(ys)]) for n, ys in FOLDS.items()}

print("=== PARAMETER STABILITY across leave-one-season-out folds ===")
print(f"{'stat':26s} " + " ".join(f"{n:>16s}" for n in FOLDS))
keys = sorted(set().union(*[set(t) for t in tuned.values()]))
unstable = 0
for k_ in keys:
    cells = []
    for n in FOLDS:
        v = tuned[n].get(k_)
        cells.append(f"{str(v):>16s}" if v else f"{'--':>16s}")
    vals = {str(tuned[n].get(k_)) for n in FOLDS if tuned[n].get(k_)}
    flag = "" if len(vals) == 1 else "  <-- varies"
    if len(vals) > 1: unstable += 1
    print(f"{k_:26s} " + " ".join(cells) + flag)
print(f"\n{unstable} of {len(keys)} stats have unstable params across folds")

print("\n=== each fold's params scored on ITS held-out season ===")
print(f"{'fold':12s} {'nMAE':>7s} {'|tf|':>7s} {'|tf early|':>11s}  vs current(prod)")
for n, ys in FOLDS.items():
    hold = [s for s in (2022,2023,2024,2025) if s not in ys][0]
    VA = d[d.season==hold]
    def agg(fn):
        nm,tf,tfe=[],[],[]
        for (mo,st),g in VA.groupby(["model","stat"]):
            if g["actual"].mean()<=1e-6 or len(g)<100: continue
            a_,c,k = fn(mo,st)
            a=g["actual"].to_numpy(float); p=pred(g,a_,c,k); ok=np.isfinite(p)&np.isfinite(a)
            if ok.sum()<100: continue
            nm.append(np.abs(p-a)[ok].mean()/a.mean())
            q=pd.qcut(g["anchor"],5,labels=False,duplicates="drop"); hm=(q==np.nanmax(q)).to_numpy()
            if hm.sum()>30:
                tf.append((p[hm].mean()-a[hm].mean())/a[hm].mean())
                e=hm&(g["week"].to_numpy()<=4)
                if e.sum()>20: tfe.append((p[e].mean()-a[e].mean())/a[e].mean())
        return np.mean(nm), np.mean(np.abs(tf)), np.mean(np.abs(tfe))
    ps = agg(lambda mo,st,t=tuned[n]: t.get(f"{mo}/{st}",(0.0,1,1.0)))
    cu = agg(lambda mo,st: (0.0,0,2.0))
    print(f"{n:12s} {ps[0]:7.4f} {ps[1]:6.1%} {ps[2]:10.1%}   current: "
          f"{cu[0]:.4f} / {cu[1]:.1%} / {cu[2]:.1%}")
