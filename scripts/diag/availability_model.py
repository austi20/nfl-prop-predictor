"""How often does an injury designation actually mean the player misses the game?

The prop board's worst edges sit on backups (Drew Lock, Carson Wentz) whose lines
are high because the starter ahead of them is hurt. The depth chart does not know
that -- it still lists the injured starter at rank 1 -- so the model projects the
backup on his backup usage and screams "under".

Before promoting anyone we need to know what a designation is worth. A Wednesday
DNP is not the same as a Friday "Out", and "Not injury related - resting player"
is not an injury at all.

Ground truth: did the player record a snap that week (a row in the weekly frame
with any usage)?
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from data.nflverse_loader import load_injuries, load_weekly

SEASONS = [int(a) for a in sys.argv[1:]] or [2022, 2023, 2024, 2025]
inj = load_injuries(SEASONS)
wk = load_weekly(SEASONS)

# The injury report covers the whole roster; the weekly box score only covers
# players who touch the ball. A guard or a safety is "missing" from it every
# week, which would read as a 100% miss rate. Restrict to the positions the
# models actually project.
SKILL = {"QB", "RB", "FB", "WR", "TE"}
inj = inj[inj["position"].astype(str).str.upper().isin(SKILL)].copy()

# "played" = appeared in the weekly box score with any usage at all
usage_cols = [c for c in ("attempts", "carries", "targets", "receptions",
                          "passing_yards", "rushing_yards", "receiving_yards")
              if c in wk.columns]
wk = wk.copy()
wk["_used"] = wk[usage_cols].fillna(0.0).abs().sum(axis=1) > 0
played = wk.groupby(["season", "week", "player_id"])["_used"].max().rename("played").reset_index()

df = inj.merge(played, left_on=["season", "week", "gsis_id"],
               right_on=["season", "week", "player_id"], how="left")
df["played"] = df["played"].fillna(False)
# A skill player who never appears in the box score all season was not on an NFL
# field that year (practice squad, IR); counting him as a weekly "miss" would
# swamp the designation signal. Keep only players with at least one game.
active = wk[wk["_used"]].groupby(["season", "player_id"]).size().rename("gp").reset_index()
df = df.merge(active, left_on=["season", "gsis_id"], right_on=["season", "player_id"],
              how="left", suffixes=("", "_a"))
df = df[df["gp"].fillna(0) > 0]
print(f"injury rows {len(inj)}  matched to a box score {int(df['played'].notna().sum())}\n")

df["report_status"] = df["report_status"].fillna("(none filed)")
df["practice_status"] = df["practice_status"].fillna("(no practice row)")
df["resting"] = df["practice_primary_injury"].astype(str).str.contains("resting", case=False, na=False)

print("=== P(misses the game) by final report status ===")
g = df.groupby("report_status").agg(n=("played", "size"), miss=("played", lambda s: 1 - s.mean()))
print(g.sort_values("n", ascending=False).to_string(float_format=lambda v: f"{v:.3f}"))

print("\n=== P(misses the game) by practice status, when NO report status is filed ===")
sub = df[df.report_status == "(none filed)"]
g = sub.groupby("practice_status").agg(n=("played", "size"), miss=("played", lambda s: 1 - s.mean()))
print(g.sort_values("n", ascending=False).to_string(float_format=lambda v: f"{v:.3f}"))

print("\n=== DNP with no report status: real injury vs rest day ===")
dnp = sub[sub.practice_status.str.contains("Did Not Participate", na=False)]
g = dnp.groupby("resting").agg(n=("played", "size"), miss=("played", lambda s: 1 - s.mean()))
print(g.to_string(float_format=lambda v: f"{v:.3f}"))

print("\n=== joint: report status x practice status ===")
j = df.groupby(["report_status", "practice_status"]).agg(
    n=("played", "size"), miss=("played", lambda s: 1 - s.mean()))
print(j[j.n >= 50].sort_values("miss", ascending=False).to_string(float_format=lambda v: f"{v:.3f}"))

print("\n=== P(misses) by injury type, when no game status is filed ===")
sub2 = df[df.report_status == "(none filed)"].copy()
sub2["inj"] = sub2["practice_primary_injury"].fillna("(none)").astype(str)
g = sub2.groupby("inj").agg(n=("played", "size"), miss=("played", lambda s: 1 - s.mean()))
print(g[g.n >= 25].sort_values("miss", ascending=False).to_string(float_format=lambda v: f"{v:.3f}"))

print("\n=== concussion specifically, all statuses x practice ===")
c = df[df["practice_primary_injury"].astype(str).str.contains("oncussion", na=False)]
g = c.groupby(["report_status", "practice_status"]).agg(
    n=("played", "size"), miss=("played", lambda s: 1 - s.mean()))
print(g[g.n >= 10].sort_values("miss", ascending=False).to_string(float_format=lambda v: f"{v:.3f}"))
print(f"\nconcussion overall: n={len(c)} miss={1 - c['played'].mean():.3f}")
