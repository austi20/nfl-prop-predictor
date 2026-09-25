"""Walk-forward ingredient extraction: for eval season Y, fit on 2015..Y-1.

Anything else evaluates in-sample and would make every rule look good.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, statsmodels.api as sm
from data.nflverse_loader import load_weekly
from eval.model_backtest import MODEL_SPECS

import sys
EVAL_SEASONS = [int(a) for a in sys.argv[2:]] or [2022, 2023, 2024, 2025]
OUT = sys.argv[1] if len(sys.argv) > 1 else "docs/diag/ingredients_wf.parquet"
weekly = load_weekly(list(range(2015, max(EVAL_SEASONS) + 1)))
frames = []
for season in EVAL_SEASONS:
    fit_years = list(range(2015, season))
    for spec in MODEL_SPECS:
        m = spec.model_cls()
        m.fit(fit_years, weekly=weekly)
        ps = m._player_stats
        ev = ps[ps["season"] == season].copy()
        if ev.empty: continue
        ev = ev.sort_values(["player_id", "week"])
        ev["n_same_season"] = ev.groupby("player_id").cumcount()
        Xc = sm.add_constant(ev[m._feature_cols].values.astype(float), has_constant="add")
        for stat in spec.target_stats:
            mr = m._models.get(stat)
            if mr is None: continue
            try: raw = np.asarray(mr.predict(Xc), dtype=float)
            except Exception: continue
            pm, psd = m._prior_means.get(stat, 0.0), m._prior_stds.get(stat, 1.0)
            raw = np.clip(raw, 1e-3, max(pm + 6*psd, pm*5, 1.0))
            frames.append(pd.DataFrame({
                "model": spec.name, "stat": stat, "season": season,
                "week": ev["week"].to_numpy(), "player_id": ev["player_id"].astype(str).to_numpy(),
                "raw_glm": raw, "prior_mean": pm,
                "trailing": ev.get(f"roll_{stat}", pd.Series(np.nan, index=ev.index)).to_numpy(float),
                "n": ev["n_same_season"].to_numpy(), "actual": ev[stat].to_numpy(float)}))
        print(f"  {season} {spec.name} done", flush=True)
out = pd.concat(frames, ignore_index=True)
out.to_parquet(OUT, index=False)
print(f"wrote {OUT} rows={len(out)}")
print(out.groupby("season").size().to_string())
