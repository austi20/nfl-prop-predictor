import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
d = pd.read_parquet("docs/diag/ingredients_wf.parquet")
d = d[np.isfinite(d[["raw_glm","prior_mean","actual"]]).all(axis=1)].copy()
d["trailing"]=d["trailing"].fillna(0.0)
d["anchor"]=np.where(d["trailing"]>1e-3,d["trailing"],d["prior_mean"])
d = d[d.n>=1]
def pred(g,c,k):
    ne=g["n"]+c
    return np.asarray(g["prior_mean"]+(ne/(ne+k))*(g["raw_glm"]-g["prior_mean"]),dtype=float)
def agg(VA,c,k):
    nm,tf,tfe,sl,cr=[],[],[],[],[]
    for (mo,st),g in VA.groupby(["model","stat"]):
        if g["actual"].mean()<=1e-6 or len(g)<100: continue
        a=g["actual"].to_numpy(float); p=pred(g,c,k); ok=np.isfinite(p)&np.isfinite(a)
        if ok.sum()<100 or p[ok].std()<1e-9: continue
        nm.append(np.abs(p-a)[ok].mean()/a.mean()); sl.append(abs(np.polyfit(p[ok],a[ok],1)[0]-1))
        cr.append(float(np.corrcoef(p[ok],a[ok])[0,1]))
        q=pd.qcut(g["anchor"],5,labels=False,duplicates="drop"); hm=(q==np.nanmax(q)).to_numpy()
        if hm.sum()>30:
            tf.append((p[hm].mean()-a[hm].mean())/a[hm].mean())
            e=hm&(g["week"].to_numpy()<=5)
            if e.sum()>20: tfe.append((p[e].mean()-a[e].mean())/a[e].mean())
    return np.mean(nm),np.mean(np.abs(tf)),np.mean(np.abs(tfe)),np.mean(sl),np.mean(cr)
CFG={"current c=0,k=2":(0,2.0), "c=1,k=1":(1,1.0), "c=4,k=2 (keeps k)":(4,2.0), "c=3,k=2":(3,2.0)}
print(f"{'config':20s} " + " ".join(f"{s:>9d}" for s in (2022,2023,2024,2025)) + "   metric")
for mi,mn in enumerate(["nMAE","|tf|","|tf wk<=5|","slope err","corr"]):
    for name,(c,k) in CFG.items():
        vals=[agg(d[d.season==s],c,k)[mi] for s in (2022,2023,2024,2025)]
        fmt = (lambda v: f"{v:9.1%}") if mi in (1,2) else (lambda v: f"{v:9.4f}")
        print(f"{name:20s} " + " ".join(fmt(v) for v in vals) + f"   {mn}")
    print()
print("=== week 2 only (n==1), pooled, top-form quintile ===")
w2=d[d.n==1]
for m,s in [("rb","rushing_yards"),("rb","carries"),("wr_te","receiving_yards"),
            ("wr_te","receptions"),("qb","passing_yards"),("qb","passing_tds")]:
    g=w2[(w2.model==m)&(w2.stat==s)]
    if len(g)<50: continue
    q=pd.qcut(g["anchor"],5,labels=False,duplicates="drop"); g=g[q==np.nanmax(q)]
    a=g["actual"].to_numpy(float)
    out=" ".join(f"{name}:{(pred(g,c,k).mean()-a.mean())/a.mean():+6.1%}" for name,(c,k) in CFG.items())
    print(f"  {m}/{s:16s} {out}")
