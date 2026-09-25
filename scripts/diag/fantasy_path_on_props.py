"""Price the Kalshi board off the fantasy projection pipeline instead of raw GLM.

The prop path today prices `model.predict()` directly. The fantasy path takes
the same GLM output and adds: a trailing-form blend, depth-chart role context,
opponent/game-script/weather/usage factors, and finally a Kalshi market anchor.

Least squares says trailing form deserves 50-90% of the weight on most box-score
stats, and the board's remaining extreme edges sit on role-change players the
prop path cannot see. So the fantasy pipeline should price the board better.

The market anchor is EXCLUDED: anchoring to the Kalshi price and then grading
edge against it is circular.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from api.settings import AppSettings
from api.services.evaluation_service import scoring_weekly
from api.services.market_lines import player_stat_lines
from api.services.prop_board_service import _week_context, _roster_index
from api.services.evaluation_service import _model_bundle
from api.services.fantasy_service import prop_stat_projection
from eval.calibration_pipeline import STAT_SPECS, spec_for
from data.upcoming import build_upcoming_row

SEASON, WEEK = 2026, 2
s = AppSettings()
weekly = scoring_weekly(s, SEASON)
lines = player_stat_lines(s, SEASON, WEEK)
ctx = _week_context(SEASON, WEEK)
roster = _roster_index(SEASON, set(ctx))
by_id = {p.player_id: p for pl in roster.values() for p in pl}

by_player: dict[str, list] = {}
for key, (strike, mkt_p) in lines.items():
    pid, stat = key.split("|", 1)
    by_player.setdefault(pid, []).append((stat, strike, mkt_p))

MO = {"QB": "qb", "RB": "rb", "WR": "wr_te", "TE": "wr_te"}
models = _model_bundle(tuple(s.default_train_years), SEASON)

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
        glm = models[mname].predict(player_id=pid, season=SEASON, week=WEEK,
                                    opp_team=opp, future_row=fr)
    except Exception:
        continue
    for stat, strike, mkt_p in quotes:
        g = glm.get(stat)
        if g is None or g.mean <= 0:
            continue
        rec = dict(stat=stat, mkt=mkt_p, p_glm=float(g.prob_over(strike)))
        try:
            proj = prop_stat_projection(s, player_id=pid, season=SEASON, week=WEEK,
                                        position=pos, recent_team=pl.team,
                                        opponent_team=opp, stat=stat)
        except Exception:
            proj = None
        if proj is not None:
            d, m = proj
            rec["p_fan"] = float(d.prob_over(strike / m)) if m > 1e-6 else float(d.prob_over(strike))
        else:
            rec["p_fan"] = rec["p_glm"]
        rows.append(rec)

df = pd.DataFrame(rows)
df.to_csv("docs/diag/fantasy_path_on_props.csv", index=False)
print(f"priced {len(df)} rungs\n")
print(f"{'stat':18s} {'n':>5s} {'mkt':>7s} | {'GLM p':>7s} {'gap':>7s} | {'fantasy p':>10s} {'gap':>7s}")
for stat, g in df.groupby("stat"):
    print(f"{stat:18s} {len(g):5d} {g.mkt.mean():7.3f} | {g.p_glm.mean():7.3f} "
          f"{(g.p_glm-g.mkt).mean():+7.3f} | {g.p_fan.mean():10.3f} {(g.p_fan-g.mkt).mean():+7.3f}")
print(f"\nOVERALL gap   GLM {(df.p_glm-df.mkt).mean():+.3f}   fantasy-path {(df.p_fan-df.mkt).mean():+.3f}")
print(f"mean |gap|    GLM {np.abs(df.p_glm-df.mkt).mean():.3f}   fantasy-path {np.abs(df.p_fan-df.mkt).mean():.3f}")
print(f"share of rungs the model calls UNDER:  GLM {(df.p_glm<df.mkt).mean():.1%}  "
      f"fantasy-path {(df.p_fan<df.mkt).mean():.1%}")
