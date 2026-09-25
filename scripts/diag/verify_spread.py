"""Boom/bust calibration on the locked 2025 backtest: old spread vs per player.

Same rows and same projected means as verify_fantasy_calibration.py; only the
standard deviation changes. Calibration error is the binned |predicted rate -
hit rate|, lower is better. Also reports how much boom varies between players
with about the same projection.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import warnings; warnings.filterwarnings("ignore")
import numpy as np
from data.nflverse_loader import load_weekly
from eval.fantasy_calibration import (
    _BOOM, _BUST, _apply_calib_to_row, _boom_bust_prob, _calibration_error,
    load_calibration, load_eval_cache,
)
from eval.fantasy_spread import player_volatility, target_sd

calib = load_calibration(_ROOT / "models" / "fantasy_calibration.json")
rows = load_eval_cache()["rows"]
weekly = load_weekly(list(range(2015, 2026)))
by_player = {pid: g.sort_values(["season", "week"]) for pid, g in weekly.groupby("player_id")}

out = {"old": {}, "new": {}}
for r in rows:
    m, sd_old = _apply_calib_to_row(r, calib)
    pos = r["position"]
    hist = by_player.get(r["player_id"])
    if hist is not None:
        hist = hist[(hist.season < r["season"]) | ((hist.season == r["season"]) & (hist.week < r["week"]))]
    games, cv, td = player_volatility(hist if hist is not None else weekly.iloc[0:0])
    sd_new = target_sd(pos, m, games, cv, td) or sd_old
    for key, sd in (("old", sd_old), ("new", sd_new)):
        b, u = _boom_bust_prob(m, sd, _BOOM[pos], _BUST[pos])
        out[key].setdefault(pos, []).append((m, b, u, r["actual_fp"] >= _BOOM[pos], r["actual_fp"] <= _BUST[pos]))

for pos in ("QB", "RB", "WR", "TE"):
    line = [pos]
    for key in ("old", "new"):
        a = np.array(out[key][pos], dtype=float)
        be = _calibration_error(a[:, 1], a[:, 3])
        ue = _calibration_error(a[:, 2], a[:, 4])
        # Spread of boom among players within 1 point of the same projection.
        resid = a[:, 1] - np.polyval(np.polyfit(a[:, 0], a[:, 1], 2), a[:, 0])
        line.append(f"{key}: boom_err={be:.3f} bust_err={ue:.3f} boom_resid_sd={resid.std():.3f}")
    print("  ".join(line))
