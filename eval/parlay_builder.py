"""Simple same-week parlay builder for paper-trade replay output.

This is intentionally lightweight. It builds candidate parlays from already
selected paper-trade picks and applies conservative same-game/team penalties
instead of assuming independence outright.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any

import pandas as pd


def american_to_decimal(american_odds: int) -> float:
    if american_odds < 0:
        return 1.0 + (100.0 / abs(float(american_odds)))
    return 1.0 + (float(american_odds) / 100.0)


def settle_parlay(combo: tuple[dict[str, Any], ...], stake: float) -> tuple[str, float]:
    if any(str(item.get("result", "")) == "loss" for item in combo):
        return "loss", -stake

    win_legs = [item for item in combo if str(item.get("result", "")) == "win"]
    if not win_legs:
        return "push", 0.0

    decimal_price = 1.0
    for item in win_legs:
        decimal_price *= american_to_decimal(int(item["selected_odds"]))
    return "win", stake * (decimal_price - 1.0)


def build_parlay_candidates(
    picks: pd.DataFrame,
    legs: int = 2,
    max_candidates: int = 20,
    same_game_penalty: float = 0.97,
    same_team_penalty: float = 0.985,
    stake: float = 1.0,
) -> pd.DataFrame:
    if picks.empty or legs < 2:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for (season, week), week_picks in picks.groupby(["season", "week"]):
        week_picks = week_picks.sort_values("selected_edge", ascending=False).reset_index(drop=True)
        for combo in combinations(week_picks.to_dict("records"), legs):
            player_ids = {str(item["player_id"]) for item in combo}
            if len(player_ids) != legs:
                continue

            joint_prob = 1.0
            decimal_price = 1.0
            penalty = 1.0
            game_ids = [str(item.get("game_id", "")) for item in combo if str(item.get("game_id", ""))]
            teams = [str(item.get("recent_team", "")) for item in combo if str(item.get("recent_team", ""))]
            if len(game_ids) != len(set(game_ids)) and game_ids:
                penalty *= same_game_penalty
            if len(teams) != len(set(teams)) and teams:
                penalty *= same_team_penalty

            for item in combo:
                joint_prob *= float(item["selected_prob"])
                decimal_price *= american_to_decimal(int(item["selected_odds"]))
            joint_prob *= penalty

            result, realized_profit = settle_parlay(combo, stake=stake)
            gross_profit = stake * (decimal_price - 1.0)
            expected_value = (joint_prob * gross_profit) - ((1.0 - joint_prob) * stake)
            rows.append({
                "season": int(season),
                "week": int(week),
                "legs": legs,
                "parlay_label": " | ".join(
                    f"{item['player_id']} {item['stat']} {item['selected_side']}"
                    for item in combo
                ),
                "joint_prob": float(joint_prob),
                "decimal_odds": float(decimal_price),
                "expected_value_units": float(expected_value),
                "same_game_penalty_applied": float(penalty),
                "mean_edge": float(sum(float(item["selected_edge"]) for item in combo) / legs),
                "result": result,
                "stake_units": float(stake),
                "profit_units": float(realized_profit),
                "books": " | ".join(sorted({str(item.get("book", "")) for item in combo if str(item.get("book", ""))})),
            })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    return df.sort_values(["expected_value_units", "joint_prob"], ascending=False).head(max_candidates)


def summarize_parlays(parlays: pd.DataFrame) -> dict[str, float]:
    if parlays.empty:
        return {
            "n_parlays": 0.0,
            "wins": 0.0,
            "losses": 0.0,
            "pushes": 0.0,
            "staked_units": 0.0,
            "profit_units": 0.0,
            "roi": 0.0,
            "win_rate": 0.0,
            "avg_expected_value_units": 0.0,
        }

    wins = float((parlays["result"] == "win").sum())
    losses = float((parlays["result"] == "loss").sum())
    pushes = float((parlays["result"] == "push").sum())
    staked = float(parlays["stake_units"].sum())
    profit = float(parlays["profit_units"].sum())
    graded = wins + losses
    return {
        "n_parlays": float(len(parlays)),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "staked_units": staked,
        "profit_units": profit,
        "roi": (profit / staked) if staked > 0 else 0.0,
        "win_rate": (wins / graded) if graded > 0 else 0.0,
        "avg_expected_value_units": float(parlays["expected_value_units"].mean()),
    }
