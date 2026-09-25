"""Does the optimal shrinkage weight differ by usage tier within a stat?

A single per-stat weight minimises squared error over every player, and most
players are low-usage backups. Kalshi only lists starters, so the board is drawn
from the top of the usage distribution -- where the right weight may differ.

Tiers are cut on the player's own trailing form, which is known before kickoff,
so this is a usable split rather than hindsight.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import warnings; warnings.filterwarnings("ignore")
import json
import numpy as np, pandas as pd

SRC = sys.argv[1] if len(sys.argv) > 1 else "docs/diag/ingredients_wf8.parquet"
NT = int(sys.argv[2]) if len(sys.argv) > 2 else 3
d = pd.read_parquet(SRC)
d = d[np.isfinite(d[["raw_glm","prior_mean","actual"]]).all(axis=1)].copy()
d["trailing"] = d["trailing"].fillna(0.0)
d["anchor"] = np.where(d["trailing"] > 1e-3, d["trailing"], d["prior_mean"])
d = d[d.n >= 1]
seasons = sorted(d.season.unique())
PROP = {"passing_yards","passing_tds","completions","attempts",
        "rushing_yards","carries","receiving_yards","receptions"}

def fit(g):
    x=(g["raw_glm"]-g["prior_mean"]).to_numpy(float); y=(g["actual"]-g["prior_mean"]).to_numpy(float)
    den=float((x*x).sum()); return float((x*y).sum()/den) if den>1e-12 else 1.0

# tier is assigned within (model,stat) on trailing form
d["tier"] = -1
for (mo,st), g in d.groupby(["model","stat"]):
    try:
        d.loc[g.index, "tier"] = pd.qcut(g["anchor"], NT, labels=False, duplicates="drop")
    except ValueError:
        d.loc[g.index, "tier"] = 0

print(f"tiers={NT}  rows={len(d)}  seasons={seasons}\n")
print("fitted weight per stat per usage tier (tier 0 = lowest usage)\n")
print(f"{'stat':24s} " + "".join(f"{'tier'+str(t):>9s}" for t in range(NT)) + f"{'flat':>9s}")
tiered = {}
for (mo,st), g in d.groupby(["model","stat"]):
    if g["actual"].mean()<=1e-6 or len(g)<400: continue
    ws=[]
    for t in range(NT):
        sub=g[g.tier==t]
        ws.append(fit(sub) if len(sub)>=150 else np.nan)
    tiered[f"{mo}/{st}"]=ws
    print(f"{mo+'/'+st:24s} " + "".join(f"{w:9.3f}" if np.isfinite(w) else f"{'--':>9s}" for w in ws)
          + f"{fit(g):9.3f}")

# LOO comparison: flat per-stat vs tiered per-stat, scored on the TOP tier only
print("\n=== leave-one-season-out, scored on the TOP usage tier (what Kalshi lists) ===")
print(f"{'':24s} {'nMAE flat':>10s} {'nMAE tier':>10s} {'bias flat':>10s} {'bias tier':>10s}")
agg={k:[] for k in ("nf","nt","bf","bt")}
aggp={k:[] for k in ("nf","nt","bf","bt")}
for (mo,st), g in d.groupby(["model","stat"]):
    if g["actual"].mean()<=1e-6 or len(g)<400: continue
    rf,rt,bf,bt=[],[],[],[]
    for s in seasons:
        tr,va=g[g.season!=s],g[g.season==s]
        top=va[va.tier==NT-1]
        if len(top)<40: continue
        wf=fit(tr)
        trtop=tr[tr.tier==NT-1]
        wt=fit(trtop) if len(trtop)>=150 else wf
        a=top["actual"].to_numpy(float); sc=max(a.mean(),1e-6)
        pf=(top["prior_mean"]+wf*(top["raw_glm"]-top["prior_mean"])).to_numpy(float)
        pt=(top["prior_mean"]+wt*(top["raw_glm"]-top["prior_mean"])).to_numpy(float)
        rf.append(np.abs(pf-a).mean()/sc); rt.append(np.abs(pt-a).mean()/sc)
        bf.append((pf.mean()-a.mean())/sc); bt.append((pt.mean()-a.mean())/sc)
    if not rf: continue
    print(f"{mo+'/'+st:24s} {np.mean(rf):10.4f} {np.mean(rt):10.4f} {np.mean(bf):+10.1%} {np.mean(bt):+10.1%}")
    for k,v in (("nf",rf),("nt",rt),("bf",bf),("bt",bt)):
        agg[k].append(np.mean(v))
        if st in PROP: aggp[k].append(np.mean(v))
print(f"\nALL  mean nMAE flat {np.mean(agg['nf']):.4f} tiered {np.mean(agg['nt']):.4f} | "
      f"|bias| flat {np.mean(np.abs(agg['bf'])):.1%} tiered {np.mean(np.abs(agg['bt'])):.1%}")
print(f"PROP mean nMAE flat {np.mean(aggp['nf']):.4f} tiered {np.mean(aggp['nt']):.4f} | "
      f"|bias| flat {np.mean(np.abs(aggp['bf'])):.1%} tiered {np.mean(np.abs(aggp['bt'])):.1%}")
json.dump({k:[None if not np.isfinite(x) else round(x,4) for x in v] for k,v in tiered.items()},
          open("docs/diag/tiered_weights.json","w"), indent=2)
