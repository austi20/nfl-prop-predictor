"""Does applying the fantasy context factors to the prop path close the gap to market?

The prop path prices the raw GLM distribution. The fantasy path multiplies the
same stat by ten context factors (opponent, game script, weather, coaching,
rest, usage, injury, depth chart, position-group form, QB support) before
scoring it. So the two surfaces answer the same question differently.

The market factor is deliberately EXCLUDED here. Anchoring a projection to the
Kalshi price and then grading edge against that same price is circular; edge
would collapse to zero by construction.
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
from api.services.fantasy_service import (
    _context_factors, _stat_multipliers, _settings_calibration,
)
from data.upcoming import build_upcoming_row

SEASON, WEEK = 2026, 2
s = AppSettings()
weekly = scoring_weekly(s, SEASON)
models = _model_bundle(tuple(s.default_train_years), SEASON)
calib = _settings_calibration(s)
MO = {"QB": "qb", "RB": "rb", "WR": "wr_te", "TE": "wr_te"}

lines = player_stat_lines(s, SEASON, WEEK)
ctx = _week_context(SEASON, WEEK)
roster = _roster_index(SEASON, set(ctx))
by_id = {p.player_id: p for pl in roster.values() for p in pl}

# group the quotes by player so factors are computed once per player
by_player: dict[str, list] = {}
for key, (strike, mkt_p) in lines.items():
    pid, stat = key.split("|", 1)
    by_player.setdefault(pid, []).append((stat, strike, mkt_p))

rows = []
for pid, quotes in by_player.items():
    pl = by_id.get(pid)
    if pl is None or not pl.position:
        continue
    pos = pl.position.upper()
    mname = MO.get(pos)
    if mname is None:
        continue
    opp = ctx.get(pl.team, ("", ""))[0]
    try:
        fr = build_upcoming_row(player_id=pid, season=SEASON, week=WEEK, position=pos,
                                opponent_team=opp, recent_team=pl.team, weekly=weekly)
        dists = models[mname].predict(player_id=pid, season=SEASON, week=WEEK,
                                      opp_team=opp, future_row=fr)
        factors = _context_factors(s, weekly, player_id=pid, season=SEASON, week=WEEK,
                                   position=pos, recent_team=pl.team, opponent_team=opp,
                                   scoring_mode="full_ppr", calib=calib)
        factors = [f for f in factors if f.name != "market"]     # no circularity
        mult = _stat_multipliers(factors, calib)
    except Exception:
        continue
    for stat, strike, mkt_p in quotes:
        d = dists.get(stat)
        if d is None or d.mean <= 0:
            continue
        m = float(mult.get(stat, 1.0))
        # Scale the line, not the distribution: P(m*X > strike) == P(X > strike/m).
        # Rebuilding a StatDistribution from mean/std would silently drop the
        # samples/quantiles the decomposed and count-aware families carry.
        rows.append(dict(stat=stat, mkt=mkt_p, mult=m,
                         p_base=float(d.prob_over(strike)),
                         p_ctx=float(d.prob_over(strike / m)) if m > 1e-6 else float(d.prob_over(strike))))

df = pd.DataFrame(rows)
df.to_csv("docs/diag/context_on_props.csv", index=False)
print(f"priced {len(df)} rungs for {df.shape[0] and len(by_player)} players\n")
print(f"{'stat':18s} {'n':>5s} {'mkt':>7s} {'base':>7s} {'gap':>7s} | {'+ctx':>7s} {'gap':>7s} {'mean mult':>10s}")
for stat, g in df.groupby("stat"):
    print(f"{stat:18s} {len(g):5d} {g.mkt.mean():7.3f} {g.p_base.mean():7.3f} "
          f"{(g.p_base-g.mkt).mean():+7.3f} | {g.p_ctx.mean():7.3f} "
          f"{(g.p_ctx-g.mkt).mean():+7.3f} {g['mult'].mean():10.3f}")
print(f"\nOVERALL base gap {(df.p_base-df.mkt).mean():+.3f}   with context {(df.p_ctx-df.mkt).mean():+.3f}")
print(f"mean |gap| base {np.abs(df.p_base-df.mkt).mean():.3f}   with context {np.abs(df.p_ctx-df.mkt).mean():.3f}")
