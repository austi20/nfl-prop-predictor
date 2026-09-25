"""Is the least-squares optimal weight stable across seasons?

The per-stat GRID SEARCH was unstable (18/22 stats). A least-squares estimate on
thousands of rows should not be. This is the test that decides whether per-stat
constants are usable or are just fitting noise again.
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
d = d[np.isfinite(d[["raw_glm","prior_mean","actual"]]).all(axis=1)]
d = d[d.n >= 1]
seasons = sorted(d.season.unique())

def w_hat(g):
    x = (g["raw_glm"]-g["prior_mean"]).to_numpy(float)
    y = (g["actual"]-g["prior_mean"]).to_numpy(float)
    den = float((x*x).sum())
    return float((x*y).sum()/den) if den > 1e-12 and len(x) >= 40 else np.nan

print(f"source={SRC} seasons={seasons}\n")
print("w_hat estimated on ALL-BUT-ONE season, per stat. Stable => usable.\n")
print(f"{'stat':24s} " + "".join(f"{s:>8d}" for s in seasons) + f"{'mean':>8s}{'sd':>7s}{'cv':>7s}")
rows = []
for (mo, st), g in d.groupby(["model", "stat"]):
    if g["actual"].mean() <= 1e-6: continue
    loo = []
    for s in seasons:
        loo.append(w_hat(g[g.season != s]))
    loo = np.array(loo, dtype=float)
    if not np.isfinite(loo).all(): continue
    mu, sd = loo.mean(), loo.std()
    cv = sd/abs(mu) if abs(mu) > 1e-9 else np.nan
    flag = "" if cv < 0.10 else ("  <- noisy" if cv < 0.25 else "  <- UNSTABLE")
    print(f"{mo+'/'+st:24s} " + "".join(f"{v:8.3f}" for v in loo) +
          f"{mu:8.3f}{sd:7.3f}{cv:7.1%}{flag}")
    rows.append(dict(model=mo, stat=st, w_mean=mu, w_sd=sd, cv=cv,
                     w_full=w_hat(g), n=len(g)))
res = pd.DataFrame(rows)
res.to_csv("docs/diag/weight_stability.csv", index=False)
print(f"\nstats with cv < 10%: {(res.cv < 0.10).sum()} of {len(res)}")
print(f"stats with cv < 25%: {(res.cv < 0.25).sum()} of {len(res)}")
