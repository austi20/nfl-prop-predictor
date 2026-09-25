"""What sets a player's week to week spread, beyond his projection?

The board's boom rate was a function of the projection alone (corr 0.92-0.98),
because every player got the same coefficient of variation. This checks which
per player and per game inputs actually predict how far a week lands from the
player's trailing mean, and whether using them improves boom/bust calibration
out of sample.

Proxy projection: recency weighted trailing mean of the last 8 games.
Fit on 2018-2023, score on 2024-2025. Brier score, lower is better.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import json
import warnings; warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
from scipy.stats import norm
from data.game_context import game_context_frame
from data.nflverse_loader import load_weekly
from eval.fantasy_points import POSITION_CUTOFFS

SEASONS = list(range(2017, 2026))
TRAIL = 8
K_SHRINK = 8.0  # pseudo games pulling a player's own CV to the position CV

wk = load_weekly(SEASONS)
wk = wk[wk["position"].isin(["QB", "RB", "WR", "TE"])].copy()
wk["fp"] = wk["fantasy_points_ppr"].fillna(0.0)
td_cols = [c for c in ("passing_tds", "rushing_tds", "receiving_tds") if c in wk.columns]
wk["td_pts"] = (wk.get("passing_tds", 0).fillna(0) * 4 + wk.get("rushing_tds", 0).fillna(0) * 6
                + wk.get("receiving_tds", 0).fillna(0) * 6)
wk = wk.sort_values(["player_id", "season", "week"]).reset_index(drop=True)

rows = []
for pid, g in wk.groupby("player_id", sort=False):
    fp = g["fp"].to_numpy(); td = g["td_pts"].to_numpy()
    for i in range(3, len(g)):
        lo = max(0, i - TRAIL)
        past, past_td = fp[lo:i], td[lo:i]
        w = np.linspace(0.5, 1.0, len(past))
        m = float(np.average(past, weights=w))
        if m < 3.0:
            continue
        rows.append((pid, g["position"].iat[i], g["season"].iat[i], g["week"].iat[i],
                     g["recent_team"].iat[i] if "recent_team" in g else g["team"].iat[i],
                     len(past), m, float(past.std(ddof=1)), float(past_td.sum() / max(past.sum(), 1e-6)),
                     fp[i]))
df = pd.DataFrame(rows, columns=["player_id", "pos", "season", "week", "team", "n", "m", "s", "td_share", "actual"])
df = df[df["season"] >= 2018]

ctx = game_context_frame(tuple(SEASONS))[["season", "week", "team", "team_implied", "team_spread", "roof"]]
df = df.merge(ctx, on=["season", "week", "team"], how="left")
df["team_implied"] = df["team_implied"].fillna(df["team_implied"].median())
df["abs_spread"] = df["team_spread"].abs().fillna(3.0)
df["dome"] = df["roof"].isin(["dome", "closed"]).astype(float)

train = df[df.season <= 2023].copy()
test = df[df.season >= 2024].copy()

# Position CV: pooled |resid| / m on train.
pos_cv = (train.assign(r=(train.actual - train.m).abs() / train.m).groupby("pos")["r"].mean()
          * np.sqrt(np.pi / 2))
print("position CV:", pos_cv.round(3).to_dict())

for d in (train, test):
    d["own_cv"] = (d.s / d.m).clip(0.05, 3.0)
    d["cv_shrunk"] = (d.n * d.own_cv + K_SHRINK * d.pos.map(pos_cv)) / (d.n + K_SHRINK)

# Which inputs predict log dispersion, holding the mean fixed?
feats = ["log_m", "log_cv_shrunk", "td_share", "team_implied", "abs_spread", "dome"]
for d in (train, test):
    d["log_m"] = np.log(d.m)
    d["log_cv_shrunk"] = np.log(d.cv_shrunk)
    d["y"] = np.log(np.abs(d.actual - d.m) + 0.5)
coef = {}
for pos, g in train.groupby("pos"):
    X = np.column_stack([np.ones(len(g))] + [g[f] for f in feats])
    beta, *_ = np.linalg.lstsq(X, g["y"].to_numpy(), rcond=None)
    coef[pos] = beta
    se = np.sqrt(np.diag(np.linalg.inv(X.T @ X)) * np.var(g["y"] - X @ beta))
    print(f"\n{pos} n={len(g)}  log|resid| ~")
    for name, b, e in zip(["const"] + feats, beta, se):
        print(f"   {name:14} {b:+.4f}  t={b / e:+.1f}")


def brier(d: pd.DataFrame, sd: np.ndarray) -> tuple[float, float]:
    boom_cut = d.pos.map(lambda p: POSITION_CUTOFFS[p][0]).to_numpy()
    bust_cut = d.pos.map(lambda p: POSITION_CUTOFFS[p][1]).to_numpy()
    p_boom = 1 - norm.cdf(boom_cut, d.m, sd)
    p_bust = norm.cdf(bust_cut, d.m, sd)
    hit_boom = (d.actual >= boom_cut).astype(float)
    hit_bust = (d.actual <= bust_cut).astype(float)
    return float(np.mean((p_boom - hit_boom) ** 2)), float(np.mean((p_bust - hit_bust) ** 2))


def fitted_sd(d: pd.DataFrame) -> np.ndarray:
    out = np.zeros(len(d))
    for pos, beta in coef.items():
        mask = (d.pos == pos).to_numpy()
        X = np.column_stack([np.ones(mask.sum())] + [d.loc[mask, f] for f in feats])
        pred = np.exp(X @ beta)
        # Rescale so the average sd matches the pooled one on train.
        tr = train[train.pos == pos]
        Xt = np.column_stack([np.ones(len(tr))] + [tr[f] for f in feats])
        scale = (np.abs(tr.actual - tr.m).mean() * np.sqrt(np.pi / 2)) / np.exp(Xt @ beta).mean()
        out[mask] = pred * scale
    return out


print("\nOut of sample 2024-2025 Brier (boom, bust):")
print("  A same CV for every player  ", brier(test, (test.pos.map(pos_cv) * test.m).to_numpy()))
print("  B player's own CV, shrunk    ", brier(test, (test.cv_shrunk * test.m).to_numpy()))
print("  C own CV + game situation    ", brier(test, fitted_sd(test)))
base_boom = np.mean(test.actual >= test.pos.map(lambda p: POSITION_CUTOFFS[p][0]))
base_bust = np.mean(test.actual <= test.pos.map(lambda p: POSITION_CUTOFFS[p][1]))
print(f"  base rates boom={base_boom:.3f} bust={base_bust:.3f}")


# Game situation adds nothing to the spread (t < 2 everywhere), so the shipped
# model keeps only the player's projection, own volatility and TD share.
SHIP = ["log_m", "log_cv_shrunk", "td_share"]
out = {"_fit": "log(|actual - mean| + 0.5) ~ log mean + log shrunk CV + TD share, 2018-2023",
       "k_shrink": K_SHRINK, "position_cv": {p: round(float(v), 4) for p, v in pos_cv.items()},
       "positions": {}}
sd_ship = np.zeros(len(test))
sd_pow = np.zeros(len(test))
for pos, g in train.groupby("pos"):
    X = np.column_stack([np.ones(len(g))] + [g[f] for f in SHIP])
    beta, *_ = np.linalg.lstsq(X, g["y"].to_numpy(), rcond=None)
    scale = (np.abs(g.actual - g.m).mean() * np.sqrt(np.pi / 2)) / np.exp(X @ beta).mean()
    out["positions"][pos] = {"const": round(float(beta[0] + np.log(scale)), 4),
                             "log_mean": round(float(beta[1]), 4),
                             "log_cv": round(float(beta[2]), 4),
                             "td_share": round(float(beta[3]), 4)}
    mask = (test.pos == pos).to_numpy()
    Xs = np.column_stack([np.ones(mask.sum())] + [test.loc[mask, f] for f in SHIP])
    sd_ship[mask] = np.exp(Xs @ beta) * scale
    # Mean only power law, to separate the exponent from the player terms.
    Xp = np.column_stack([np.ones(len(g)), g["log_m"]])
    bp, *_ = np.linalg.lstsq(Xp, g["y"].to_numpy(), rcond=None)
    sp = (np.abs(g.actual - g.m).mean() * np.sqrt(np.pi / 2)) / np.exp(Xp @ bp).mean()
    sd_pow[mask] = np.exp(bp[0] + bp[1] * test.loc[mask, "log_m"]) * sp

print("  D sd = a * mean^b only       ", brier(test, sd_pow))
print("  E shipped (mean, CV, TD)     ", brier(test, sd_ship))
target = _ROOT / "models" / "fantasy_spread.json"
target.write_text(json.dumps(out, indent=2), encoding="utf-8")
print("written ->", target)

