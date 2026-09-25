"""Out-of-sample calibration slope per stat.

Regress actual ~ a + b*pred on held-out seasons.
  b > 1  -> predictions too compressed (over-shrunk / underfit)
  b < 1  -> predictions too spread (overfit)
  b ~ 1  -> correctly scaled
Also reports bias by predicted-quintile, which is where shrinkage shows up.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import warnings; warnings.filterwarnings("ignore")
import json, sys
import numpy as np, pandas as pd
from data.nflverse_loader import load_weekly
from eval.model_backtest import MODEL_SPECS, _predict_for_eval_rows

FIT = list(range(2015, 2025))     # 2015-2024
EVAL = [int(y) for y in sys.argv[1:]] or [2025]

weekly = load_weekly(sorted(set(FIT + EVAL)))
out = {}
for spec in MODEL_SPECS:
    rows = weekly[weekly["position"].isin(spec.positions)].copy()
    rows = rows.sort_values(["season", "week", "player_id"])
    tr = rows[rows["season"].isin(FIT)]
    ev = rows[rows["season"].isin(EVAL)]
    if tr.empty or ev.empty:
        print(f"{spec.name}: no rows (train={len(tr)} eval={len(ev)})"); continue
    both = pd.concat([tr, ev], ignore_index=True)
    preds = _predict_for_eval_rows(spec, FIT, both)
    preds = preds[preds["season"].isin(EVAL)]
    print(f"\n===== {spec.name.upper()}  (eval {EVAL}, n={len(preds)}) =====")
    print(f"{'stat':18s} {'n':>6s} {'mean_act':>9s} {'mean_pred':>9s} {'bias':>8s} "
          f"{'slope':>7s} {'icept':>8s} {'corr':>6s}")
    for stat in spec.target_stats:
        d = preds[[f"actual_{stat}", f"pred_{stat}"]].dropna()
        d = d[np.isfinite(d).all(axis=1)]
        if len(d) < 50: continue
        a = d[f"actual_{stat}"].to_numpy(float); p = d[f"pred_{stat}"].to_numpy(float)
        if p.std() < 1e-9: continue
        b, i0 = np.polyfit(p, a, 1)
        corr = float(np.corrcoef(p, a)[0, 1])
        print(f"{stat:18s} {len(d):6d} {a.mean():9.3f} {p.mean():9.3f} {p.mean()-a.mean():8.3f} "
              f"{b:7.3f} {i0:8.3f} {corr:6.3f}")
        out[f"{spec.name}/{stat}"] = dict(n=len(d), mean_actual=a.mean(), mean_pred=p.mean(),
                                          slope=b, intercept=i0, corr=corr)
        # bias by predicted quintile - shrinkage signature
        q = pd.qcut(p, 5, labels=False, duplicates="drop")
        parts = []
        for k in sorted(pd.unique(q[~pd.isna(q)])):
            m = q == k
            parts.append(f"Q{int(k)+1}: pred {p[m].mean():7.2f} act {a[m].mean():7.2f} "
                         f"bias {p[m].mean()-a[m].mean():+7.2f}")
        print("      " + " | ".join(parts))
json.dump(out, open("docs/diag/calib_slope.json", "w"), indent=2, default=float)
print("\nwrote docs/diag/calib_slope.json")
