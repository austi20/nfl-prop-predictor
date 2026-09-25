"""What an injury designation does to an established player's fantasy output.

availability_model.py counts "missed" as "no touches", which also counts healthy
backups who simply never got the ball. That inflates every miss rate. Here the
sample is regulars only (averaging real volume before the week), and the answer
is the expected share of normal output: P(plays) x workload when he plays.

Workload is FP this week over the player's trailing FP, divided by the same
ratio for regulars not on the report, so regression to the mean cancels out.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import warnings; warnings.filterwarnings("ignore")
import pandas as pd
from data.nflverse_loader import load_injuries, load_weekly

SEASONS = [int(a) for a in sys.argv[1:]] or [2022, 2023, 2024, 2025]
MIN_TOUCHES = 8.0   # trailing touches per game to count as a regular
TRAIL = 4           # games in the trailing window
MIN_GAMES = 2

wk = load_weekly(SEASONS)
wk = wk[wk["position"].isin(["QB", "RB", "WR", "TE"])].copy()
wk["touches"] = wk[["attempts", "carries", "targets"]].fillna(0.0).sum(axis=1)
wk["fp"] = wk["fantasy_points_ppr"].fillna(0.0)
wk = wk[wk["touches"] > 0].sort_values(["player_id", "season", "week"])

# Trailing volume and FP from games strictly before this one.
rows = []
for pid, g in wk.groupby("player_id"):
    g = g.reset_index(drop=True)
    for i in range(len(g)):
        prior = g.iloc[max(0, i - TRAIL):i]
        rows.append((pid, g.at[i, "season"], g.at[i, "week"], len(prior),
                     prior["touches"].mean() if len(prior) else 0.0,
                     prior["fp"].mean() if len(prior) else 0.0))
trail = pd.DataFrame(rows, columns=["player_id", "season", "week", "n", "trail_touch", "trail_fp"])

# Every (player, week) a regular could have played: his team's schedule weeks.
games = wk[["player_id", "season", "week", "fp"]]
regular = trail[(trail["n"] >= MIN_GAMES) & (trail["trail_touch"] >= MIN_TOUCHES)]

inj = load_injuries(SEASONS)
inj = inj[inj["position"].isin(["QB", "RB", "WR", "TE"])].copy()
inj["status"] = inj["report_status"].fillna("")
dnp = inj["practice_status"].fillna("").str.contains("Did Not Participate")
rest = inj["practice_primary_injury"].fillna("").str.contains("resting", case=False)
lim = inj["practice_status"].fillna("").str.contains("Limited")
inj.loc[inj.status.eq("") & dnp & ~rest, "status"] = "none: DNP injured"
inj.loc[inj.status.eq("") & dnp & rest, "status"] = "none: DNP rest"
inj.loc[inj.status.eq("") & lim, "status"] = "none: limited"
inj.loc[inj.status.eq(""), "status"] = "none: full/other"
inj = inj.drop_duplicates(["gsis_id", "season", "week"], keep="last")

# The trailing window is only known for weeks he played, so for a missed week
# use his most recent regular row from earlier in the season.
last_reg = regular.sort_values(["season", "week"])
cand = inj.merge(last_reg, left_on=["gsis_id", "season"], right_on=["player_id", "season"],
                 suffixes=("", "_t"))
cand = cand[cand["week_t"] <= cand["week"]]
cand = cand.sort_values("week_t").drop_duplicates(["gsis_id", "season", "week"], keep="last")
cand = cand.merge(games, left_on=["gsis_id", "season", "week"],
                  right_on=["player_id", "season", "week"], how="left", suffixes=("", "_g"))
cand["played"] = cand["fp"].notna()

# Baseline: regulars in weeks they were not on the report at all.
on_report = set(zip(inj["gsis_id"], inj["season"], inj["week"]))
base = regular.merge(games, on=["player_id", "season", "week"])
base = base[[(p, s, w) not in on_report for p, s, w in zip(base.player_id, base.season, base.week)]]
base_ratio = base["fp"].mean() / base["trail_fp"].mean()
print(f"baseline regulars not on report: n={len(base)} fp/trailing={base_ratio:.3f}\n")

out = []
for status, g in cand.groupby("status"):
    p_play = g["played"].mean()
    pl = g[g["played"]]
    workload = (pl["fp"].mean() / pl["trail_fp"].mean() / base_ratio) if len(pl) else float("nan")
    out.append((status, len(g), p_play, len(pl), workload, p_play * (workload if len(pl) else 0.0)))
res = pd.DataFrame(out, columns=["status", "n", "p_play", "n_played", "workload_if_play", "expected_mult"])
print(res.sort_values("n", ascending=False).to_string(index=False, float_format=lambda v: f"{v:.3f}"))
