"""Score the fantasy model against two naive baselines on the 2025 backtest rows.

  uv run python scripts/baseline_comparison.py

Same 2,741 player-weeks the calibration sweep uses. Baselines:
  trail4  mean of the player's last 4 games before the week
  season  mean of the player's games earlier in the same season
MAE and Spearman rank correlation are computed per position, then averaged
with equal weight, matching eval.fantasy_calibration.evaluate.
Also prints how often the actual score lands inside the floor/ceiling band
(p10 to p90, nominal 80%).
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
from scipy import stats as sps

warnings.simplefilter("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.services.fantasy_service import _player_history
from data.nflverse_loader import load_weekly
from eval.fantasy_calibration import (
    _apply_calib_to_row,
    default_calibration,
    load_calibration,
    load_eval_cache,
)
from eval.fantasy_points import SCORING_PROFILES
from eval.fantasy_spread import player_volatility, target_sd

ARTIFACT = Path("models/fantasy_calibration.json")
POSITIONS = ("QB", "RB", "WR", "TE")
SEASON = 2025
Z90 = 1.2815515655446004  # normal quantile for p10 and p90


def weekly_points(wk) -> dict:
    """player_id -> list of (season, week, fantasy points), oldest first."""
    weights = SCORING_PROFILES["full_ppr"]
    wk = wk.sort_values(["season", "week"])
    games: dict = {}
    for _, r in wk.iterrows():
        pts = 0.0
        for stat, w in weights.items():
            if stat in r.index:
                pts += (r[stat] or 0.0) * w
        games.setdefault(str(r["player_id"]), []).append((int(r["season"]), int(r["week"]), float(pts)))
    return games


def baselines(games: list, season: int, week: int) -> tuple[float | None, float | None]:
    """(trailing 4 game mean, season to date mean) using games before this week."""
    prior = [g for g in games if (g[0], g[1]) < (season, week)]
    if not prior:
        return None, None
    trail4 = float(np.mean([g[2] for g in prior[-4:]]))
    this_season = [g[2] for g in prior if g[0] == season]
    season_avg = float(np.mean(this_season)) if this_season else None
    return trail4, season_avg


def band(mean_fp: float, std_fp: float) -> tuple[float, float]:
    """p10 and p90 of a lognormal with this mean and std."""
    if mean_fp <= 0 or std_fp <= 0:
        return mean_fp, mean_fp
    sigma2 = np.log(1.0 + (std_fp / mean_fp) ** 2)
    sigma = np.sqrt(sigma2)
    mu = np.log(mean_fp) - 0.5 * sigma2
    return float(np.exp(mu - Z90 * sigma)), float(np.exp(mu + Z90 * sigma))


def score(rows: list[dict], preds: dict) -> tuple[float, float]:
    """Position balanced (MAE, Spearman) for rows; preds maps row index -> prediction."""
    maes, ranks = [], []
    for pos in POSITIONS:
        p, a = [], []
        for i, r in enumerate(rows):
            if r["position"] == pos:
                p.append(preds[i])
                a.append(r["actual_fp"])
        maes.append(float(np.mean(np.abs(np.array(p) - np.array(a)))))
        ranks.append(float(sps.spearmanr(p, a).statistic))
    return float(np.mean(maes)), float(np.mean(ranks))


def pair_accuracy(rows: list[dict], preds: dict) -> float:
    """Share of same position, same week pairs where the higher projection scored more.
    Ties in actual points are skipped."""
    right, total = 0, 0
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = rows[i], rows[j]
            if a["position"] != b["position"] or a["week"] != b["week"]:
                continue
            if a["actual_fp"] == b["actual_fp"] or preds[i] == preds[j]:
                continue
            total += 1
            if (preds[i] > preds[j]) == (a["actual_fp"] > b["actual_fp"]):
                right += 1
    return right / total


def main() -> None:
    cache = load_eval_cache()
    rows = cache["rows"]
    wk = load_weekly(list(range(2015, SEASON + 1)))
    games = weekly_points(wk)
    calib = load_calibration(str(ARTIFACT)) if ARTIFACT.exists() else default_calibration()

    model, trail4, season_avg = {}, {}, {}
    fallbacks = 0
    covered = {pos: [0, 0] for pos in POSITIONS}
    covered_shipped = {pos: [0, 0] for pos in POSITIONS}
    for i, r in enumerate(rows):
        mean_fp, std_fp = _apply_calib_to_row(r, calib)
        model[i] = mean_fp
        t4, sa = baselines(games.get(r["player_id"], []), r["season"], r["week"])
        if t4 is None:
            t4 = sa = mean_fp
            fallbacks += 1
        if sa is None:
            sa = t4
            fallbacks += 1
        trail4[i] = t4
        season_avg[i] = sa
        # backtest spread, then the per player spread the app ships
        shipped_sd = target_sd(r["position"], mean_fp, *player_volatility(
            _player_history(wk, r["player_id"], r["season"], r["week"])))
        for table, sd in ((covered, std_fp), (covered_shipped, shipped_sd or std_fp)):
            lo, hi = band(mean_fp, sd)
            table[r["position"]][1] += 1
            if lo <= r["actual_fp"] <= hi:
                table[r["position"]][0] += 1

    print(f"rows: {len(rows)}  baseline fallbacks: {fallbacks}")
    print("| method | MAE | rank corr |")
    print("|---|---|---|")
    for name, preds in (("model", model), ("trailing 4 game avg", trail4), ("season to date avg", season_avg)):
        mae, rank = score(rows, preds)
        print(f"| {name} | {mae:.2f} | {rank:.3f} |")

    print()
    for name, preds in (("model", model), ("trailing 4 game avg", trail4), ("season to date avg", season_avg)):
        print(f"start/sit pair accuracy, {name}: {pair_accuracy(rows, preds):.1%}")

    for label, table in (("backtest spread", covered), ("shipped per player spread", covered_shipped)):
        print(f"\nBand coverage, {label} (nominal 80%):")
        hit = sum(c[0] for c in table.values())
        total = sum(c[1] for c in table.values())
        print(f"  all: {hit}/{total} = {hit / total:.1%}")
        for pos in POSITIONS:
            h, n = table[pos]
            print(f"  {pos}: {h}/{n} = {h / n:.1%}")


if __name__ == "__main__":
    main()
