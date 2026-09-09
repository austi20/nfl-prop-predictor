"""Generate and paper-submit model signals for the 2026 Week 1 slate (dry run).

No 2026 games have been played, so there are no outcomes and no real market
lines. This script:

1. builds each ACT skill player's 2026 Week 1 opponent context (data.upcoming),
2. derives a naive synthetic line from the player's 2025 trailing-4 average,
3. prices the model's P(over) against a flat -110 / -110 synthetic book,
4. keeps EV-positive picks and pushes them through the paper execution stack.

It proves the season-open prediction -> pricing -> execution path runs against
the real upcoming schedule. It is NOT a profitability signal: the lines are
synthetic, so "edge" here only measures model vs. 2025 trend.

KNOWN LIMITATION (see docs/season_eve_2026_dryrun.md): the model's
``future_row`` scoring path is not season-ready. With ``use_future_row`` off
(the default) a Week-1 prediction has no same-season prior weeks, so shrinkage
collapses every projection to the position's league prior; and the decomposed
passing-yards path over-projects badly when that collapse is removed. Treat the
signal CSV this writes as a plumbing exercise only, not a slate.

Usage:
  uv run python scripts/dry_run_week1_2026.py
"""
from __future__ import annotations

import math
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from data.nflverse_loader import load_rosters, load_schedules, load_weekly_with_weather
from data.upcoming import build_upcoming_row
from eval.prop_pricer import price_two_sided_prop_decision
from models.qb import QBModel
from models.rb import RBModel
from models.wr_te import WRTEModel

SEASON = 2026
WEEK = 1
FIT_YEARS = list(range(2018, 2026))
HISTORY_YEAR = 2025
_MIN_PRIOR_GAMES = 3
_SYNTH_ODDS = -110
_MIN_EV = 0.02

_POSITION_MODEL = {"QB": QBModel, "RB": RBModel, "WR": WRTEModel, "TE": WRTEModel}
_POSITION_STATS = {
    "QB": ["passing_yards", "passing_tds", "interceptions", "completions"],
    "RB": ["rushing_yards", "carries", "rushing_tds"],
    "WR": ["receptions", "receiving_yards", "receiving_tds"],
    "TE": ["receptions", "receiving_yards", "receiving_tds"],
}

_PICK_COLUMNS = [
    "player_id", "player_name", "position", "season", "week", "stat", "line",
    "recent_team", "opponent_team", "game_id", "model_mean", "selected_side",
    "selected_odds", "selected_book_implied_prob", "selected_fair_american",
    "selected_raw_prob", "selected_prob", "selected_edge", "selected_ev",
]


def _team_context(sched1: pd.DataFrame) -> dict[str, dict]:
    ctx: dict[str, dict] = {}
    for r in sched1.itertuples(index=False):
        ctx[r.home_team] = {"opponent": r.away_team, "is_home": True, "game_id": r.game_id}
        ctx[r.away_team] = {"opponent": r.home_team, "is_home": False, "game_id": r.game_id}
    return ctx


def _trailing_lines(hist: pd.DataFrame, stats: list[str]) -> dict[str, float]:
    """floor(mean of last 4 games) + 0.5 per stat, requiring >= _MIN_PRIOR_GAMES."""
    out: dict[str, float] = {}
    tail = hist.sort_values("week").tail(4)
    for stat in stats:
        if stat not in tail.columns:
            continue
        vals = tail[stat].dropna()
        if len(vals) < _MIN_PRIOR_GAMES:
            continue
        mean = float(vals.mean())
        if mean <= 0:
            continue
        out[stat] = math.floor(mean) + 0.5
    return out


def build_signals() -> pd.DataFrame:
    sched1 = load_schedules([SEASON])
    sched1 = sched1[sched1["week"] == WEEK]
    team_ctx = _team_context(sched1)

    rosters = load_rosters([SEASON])
    roster1 = rosters[
        (rosters["week"] == WEEK)
        & (rosters["position"].isin(_POSITION_MODEL))
        & (rosters["status"] == "ACT")
    ].copy()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        weekly_train = load_weekly_with_weather(FIT_YEARS)
    weekly_hist = weekly_train[weekly_train["season"] == HISTORY_YEAR].copy()
    hist_by_player = {pid: g for pid, g in weekly_hist.groupby("player_id")}

    models: dict[str, object] = {}
    for pos, cls in {"QB": QBModel, "RB": RBModel, "WR": WRTEModel}.items():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m = cls()
            m.fit(FIT_YEARS, weekly=weekly_train)
        models[pos] = m
    model_for = {"QB": models["QB"], "RB": models["RB"], "WR": models["WR"], "TE": models["WR"]}

    rows: list[dict] = []
    skipped = {"no_history": 0, "no_team_ctx": 0, "no_lines": 0, "predict_error": 0}

    for r in roster1.itertuples(index=False):
        player_id = str(r.player_id)
        position = str(r.position)
        team = str(r.team)

        hist = hist_by_player.get(player_id)
        if hist is None or hist.empty:
            skipped["no_history"] += 1
            continue
        ctx = team_ctx.get(team)
        if ctx is None:
            skipped["no_team_ctx"] += 1
            continue

        lines = _trailing_lines(hist, _POSITION_STATS[position])
        if not lines:
            skipped["no_lines"] += 1
            continue

        try:
            future_row = build_upcoming_row(
                player_id, SEASON, WEEK,
                position=position,
                opponent_team=ctx["opponent"],
                recent_team=team,
                is_home=ctx["is_home"],
                weekly=weekly_hist,
            )
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                dists = model_for[position].predict(player_id, WEEK, SEASON, future_row=future_row)
        except Exception:
            skipped["predict_error"] += 1
            continue

        for stat, line in lines.items():
            dist = dists.get(stat)
            if dist is None:
                continue
            # Skip stats with no position-matched trailing signal (e.g. a
            # fullback routed through the RB model): the model would fall back
            # to the league prior, not a player-specific projection.
            if float(future_row.get(f"roll_{stat}", 0.0) or 0.0) <= 0.0:
                skipped["no_trailing_signal"] = skipped.get("no_trailing_signal", 0) + 1
                continue
            p_over = float(dist.prob_over(line))
            decision = price_two_sided_prop_decision(
                raw_prob_over=p_over,
                over_odds=_SYNTH_ODDS,
                under_odds=_SYNTH_ODDS,
                player_id=player_id,
                stat=stat,
                line=line,
                model_mean=float(dist.mean),
                stake=1.0,
                min_ev=_MIN_EV,
            )
            if decision.recommendation == "no_bet":
                continue
            sp = decision.side_payload(decision.recommendation)
            rows.append({
                "player_id": player_id,
                "player_name": str(getattr(r, "player_name", "")),
                "position": position,
                "season": SEASON,
                "week": WEEK,
                "stat": stat,
                "line": line,
                "recent_team": team,
                "opponent_team": ctx["opponent"],
                "game_id": ctx["game_id"],
                "model_mean": round(float(dist.mean), 3),
                "selected_side": decision.recommendation,
                "selected_odds": int(sp["book_odds"]),
                "selected_book_implied_prob": round(float(sp["book_implied_prob"]), 5),
                "selected_fair_american": round(float(sp["fair_american"]), 1),
                "selected_raw_prob": round(float(sp["raw_prob"]), 5),
                "selected_prob": round(float(sp["calibrated_prob"]), 5),
                "selected_edge": round(float(sp["edge"]), 5),
                "selected_ev": round(float(sp["ev"]), 5),
            })

    print(f"roster ACT skill players: {len(roster1)}")
    print(f"skipped: {skipped}")
    print(f"signals kept (EV >= {_MIN_EV}): {len(rows)}")
    return pd.DataFrame(rows, columns=_PICK_COLUMNS)


def main() -> None:
    signals = build_signals()
    out_csv = Path("docs/week1_2026_signals.csv")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    signals.to_csv(out_csv, index=False)
    print(f"wrote {out_csv}")

    if signals.empty:
        print("no signals -> skipping execution submit")
        return

    from scripts.dry_run_execution import run as run_execution

    run_execution(out_csv, "2026-w1", limit=0, fake_adapter=False, out_dir=Path("docs"))


if __name__ == "__main__":
    main()
