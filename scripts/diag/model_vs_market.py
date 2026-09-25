"""Model probability vs Kalshi's, on every coin-flip rung the board would price.

Kalshi's mid is the best pre-game truth proxy available. If the model is
systematically below the market at the same strike, the board will show unders
no matter what the model's own backtest says.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from api.settings import AppSettings
from api.services.evaluation_service import scoring_weekly, _model_bundle
from api.services.market_lines import player_stat_lines
from api.services.prop_board_service import _week_context, _roster_index
from data.upcoming import build_upcoming_row

SEASON = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
WEEK = int(sys.argv[2]) if len(sys.argv) > 2 else 2
s = AppSettings()
weekly = scoring_weekly(s, SEASON)
models = _model_bundle(tuple(s.default_train_years), SEASON)
MO = {"QB": "qb", "RB": "rb", "WR": "wr_te", "TE": "wr_te"}

lines = player_stat_lines(s, SEASON, WEEK)
ctx = _week_context(SEASON, WEEK)
roster = _roster_index(SEASON, set(ctx))
by_id = {p.player_id: p for plist in roster.values() for p in plist}
print(f"kalshi quotes: {len(lines)}  rostered players: {len(by_id)}")

rows = []
for key, (strike, mkt_p) in lines.items():
    pid, stat = key.split("|", 1)
    pl = by_id.get(pid)
    if pl is None or not pl.position:
        continue
    mname = MO.get(pl.position.upper())
    if mname is None:
        continue
    opp = ctx.get(pl.team, ("", ""))[0]
    try:
        fr = build_upcoming_row(player_id=pid, season=SEASON, week=WEEK,
                                position=pl.position.upper(), opponent_team=opp,
                                recent_team=pl.team, weekly=weekly)
        d = models[mname].predict(player_id=pid, season=SEASON, week=WEEK,
                                  opp_team=opp, future_row=fr)[stat]
    except Exception:
        continue
    rows.append(dict(player=pl.player_name, pos=pl.position.upper(), stat=stat,
                     strike=strike, mkt_p=mkt_p, model_p=float(d.prob_over(strike)),
                     model_mean=float(d.mean), trailing=float(fr.get(f"roll_{stat}", 0) or 0)))
df = pd.DataFrame(rows)
df.to_csv("docs/diag/model_vs_market.csv", index=False)
print(f"priced {len(df)} rungs\n")
print("model_p - mkt_p: negative => model says UNDER where market says coin flip\n")
print(f"{'stat':18s} {'n':>5s} {'mean mkt':>9s} {'mean model':>11s} {'gap':>8s} {'%under':>8s}")
for stat, g in df.groupby("stat"):
    gap = (g.model_p - g.mkt_p).mean()
    print(f"{stat:18s} {len(g):5d} {g.mkt_p.mean():9.3f} {g.model_p.mean():11.3f} "
          f"{gap:+8.3f} {(g.model_p < g.mkt_p).mean():7.1%}")
print(f"\nOVERALL gap {(df.model_p - df.mkt_p).mean():+.3f}   "
      f"model below market on {(df.model_p < df.mkt_p).mean():.1%} of rungs")
print(f"\nmodel mean / trailing ratio by stat:")
for stat, g in df.groupby("stat"):
    t = g[g.trailing > 1e-6]
    if len(t): print(f"  {stat:18s} {(t.model_mean/t.trailing).median():.3f}")
