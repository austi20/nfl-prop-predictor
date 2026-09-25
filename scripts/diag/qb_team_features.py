"""Do the self-referential team passing features help or hurt the QB model?

`merge_group_context` sums passing stats over the QB-only frame, so
`team_pass_passing_yards` is close to the starter's own line. The fitted
coefficients on the player's own roll and the team duplicate come out nearly
equal and opposite, which cancels most of the level signal.

Refit the passing GLMs with and without those columns, walk-forward.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, statsmodels.api as sm
from models.qb import QBModel, _FAMILIES

EVAL = [2021, 2022, 2023, 2024, 2025]
STATS = ["passing_yards", "passing_tds", "completions", "attempts"]

from data.nflverse_loader import load_weekly
weekly = load_weekly(list(range(2015, 2026)))
m = QBModel(); m.fit(list(range(2015, 2021)), weekly=weekly)   # features only
ps = m._player_stats
cols_all = list(m._feature_cols)
cols_drop = [c for c in cols_all if not c.startswith("team_pass_")]
print(f"features: all={len(cols_all)}  without team_pass_*={len(cols_drop)}")
print(f"dropped: {[c for c in cols_all if c.startswith('team_pass_')]}\n")

def run(cols, fit_years, season, stat):
    tr = ps[ps.season.isin(fit_years)].dropna(subset=cols + [stat])
    ev = ps[ps.season == season].dropna(subset=cols + [stat])
    if len(tr) < 200 or len(ev) < 50: return None
    y = np.clip(tr[stat].to_numpy(float), 1e-2, None)
    X = sm.add_constant(tr[cols].to_numpy(float), has_constant="add")
    try:
        res = sm.GLM(y, X, family=_FAMILIES[stat]).fit()
    except Exception:
        return None
    Xe = sm.add_constant(ev[cols].to_numpy(float), has_constant="add")
    p = np.asarray(res.predict(Xe), float); a = ev[stat].to_numpy(float)
    ok = np.isfinite(p) & np.isfinite(a)
    p, a = p[ok], a[ok]
    if len(a) < 50 or p.std() < 1e-9: return None
    return dict(mae=np.abs(p-a).mean(), corr=float(np.corrcoef(p,a)[0,1]),
                slope=float(np.polyfit(p,a,1)[0]), bias=p.mean()-a.mean(), n=len(a))

print(f"{'stat':16s} {'season':>7s} {'MAE with':>9s} {'MAE w/o':>9s} {'corr with':>10s} {'corr w/o':>9s} {'slope w':>8s} {'slope w/o':>10s}")
tot = {"mae_w": [], "mae_o": [], "corr_w": [], "corr_o": [], "slope_w": [], "slope_o": []}
for stat in STATS:
    for season in EVAL:
        fy = list(range(2015, season))
        rw = run(cols_all, fy, season, stat)
        ro = run(cols_drop, fy, season, stat)
        if not rw or not ro: continue
        print(f"{stat:16s} {season:7d} {rw['mae']:9.2f} {ro['mae']:9.2f} "
              f"{rw['corr']:10.3f} {ro['corr']:9.3f} {rw['slope']:8.3f} {ro['slope']:10.3f}")
        tot["mae_w"].append(rw['mae']); tot["mae_o"].append(ro['mae'])
        tot["corr_w"].append(rw['corr']); tot["corr_o"].append(ro['corr'])
        tot["slope_w"].append(rw['slope']); tot["slope_o"].append(ro['slope'])
    print()
print(f"MEAN  MAE  with {np.mean(tot['mae_w']):7.3f}  without {np.mean(tot['mae_o']):7.3f}")
print(f"MEAN  corr with {np.mean(tot['corr_w']):7.3f}  without {np.mean(tot['corr_o']):7.3f}")
print(f"MEAN |slope-1| with {np.mean(np.abs(np.array(tot['slope_w'])-1)):7.3f}  "
      f"without {np.mean(np.abs(np.array(tot['slope_o'])-1)):7.3f}")
