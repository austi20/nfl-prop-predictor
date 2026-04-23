"""Generate synthetic NFL prop lines from trailing player stat averages.

Lines are derived from each player's shifted 4-game rolling average so that
the replay pipeline can be exercised on real nflverse outcomes without requiring
actual historical closing lines.

This is an engineering-gate tool, not a strategy tool. The generated lines
represent a "naive recent-form baseline" - ROI measures whether model signals
(EPA, opponent context, shrinkage) add value over simple trend-following.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd

from data.nflverse_loader import load_weekly
from models.feature_utils import rolling_mean

POSITION_STATS: dict[str, frozenset[str]] = {
    "QB": frozenset({"passing_yards", "passing_tds", "interceptions", "completions", "rushing_yards", "carries", "rushing_tds"}),
    "RB": frozenset({"rushing_yards", "carries", "rushing_tds", "receptions", "receiving_yards", "receiving_tds"}),
    "WR": frozenset({"receptions", "receiving_yards", "receiving_tds", "rushing_yards", "carries"}),
    "TE": frozenset({"receptions", "receiving_yards", "receiving_tds"}),
    "FB": frozenset({"rushing_yards", "carries", "receptions", "receiving_yards"}),
}

ALL_STATS = (
    "passing_yards", "passing_tds", "interceptions", "completions",
    "rushing_yards", "carries", "rushing_tds",
    "receptions", "receiving_yards", "receiving_tds",
)

OUTPUT_COLUMNS = [
    "player_id", "season", "week", "stat", "line",
    "book", "over_odds", "under_odds", "recent_team", "opponent_team", "game_id",
]

_ODDS_OVER = -110
_ODDS_UNDER = -110


def _round_line(value: float) -> float:
    """Round to floor+0.5 - matches sportsbook convention and avoids pushes."""
    return math.floor(value) + 0.5


def _build_rows(
    weekly: pd.DataFrame,
    target_seasons: list[int],
    window: int,
    min_games: int,
) -> pd.DataFrame:
    df = weekly.sort_values(["player_id", "season", "week"]).copy()

    # Compute trailing mean + game count per player for every stat column
    for stat in ALL_STATS:
        if stat not in df.columns:
            continue
        filled = df[stat].fillna(0.0)
        df[f"_mean_{stat}"] = df.groupby("player_id", group_keys=False)[stat].transform(
            lambda s: rolling_mean(s.fillna(0.0), window=window)
        )
        df[f"_cnt_{stat}"] = df.groupby("player_id", group_keys=False)[stat].transform(
            lambda s: s.fillna(0.0).shift(1).rolling(window, min_periods=1).count()
        )

    target = df[df["season"].isin(target_seasons)].copy()

    opp_col = "opponent_team" if "opponent_team" in target.columns else "opp_team"
    team_col = "recent_team" if "recent_team" in target.columns else "posteam"

    stat_frames: list[pd.DataFrame] = []
    for stat in ALL_STATS:
        mean_col = f"_mean_{stat}"
        cnt_col = f"_cnt_{stat}"
        if mean_col not in target.columns:
            continue

        allowed_positions = {pos for pos, stats in POSITION_STATS.items() if stat in stats}
        mask = (
            target["position"].isin(allowed_positions)
            & (target[cnt_col] >= min_games)
            & (target[mean_col] > 0)
        )
        subset = target[mask].copy()
        if subset.empty:
            continue

        recent_team = subset[team_col].fillna("") if team_col in subset.columns else ""
        opponent_team = subset[opp_col].fillna("") if opp_col in subset.columns else ""

        frame = pd.DataFrame({
            "player_id": subset["player_id"].values,
            "season": subset["season"].astype(int).values,
            "week": subset["week"].astype(int).values,
            "stat": stat,
            "line": subset[mean_col].apply(_round_line).values,
            "book": "synthetic",
            "over_odds": _ODDS_OVER,
            "under_odds": _ODDS_UNDER,
            "recent_team": recent_team.values if hasattr(recent_team, "values") else recent_team,
            "opponent_team": opponent_team.values if hasattr(opponent_team, "values") else opponent_team,
        })

        frame["game_id"] = (
            frame["season"].astype(str) + "_"
            + frame["week"].apply(lambda w: f"{w:02d}") + "_"
            + frame["recent_team"].astype(str) + "_"
            + frame["opponent_team"].astype(str)
        )

        stat_frames.append(frame[OUTPUT_COLUMNS])

    if not stat_frames:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    result = (
        pd.concat(stat_frames, ignore_index=True)
        .drop_duplicates(subset=["player_id", "season", "week", "stat"])
        .sort_values(["season", "week", "player_id", "stat"])
        .reset_index(drop=True)
    )
    return result


def generate(
    seasons: list[int],
    window: int = 4,
    min_games: int = 3,
    out_file: Path = Path("docs/synthetic_replay_props.csv"),
) -> pd.DataFrame:
    """Load weekly data, compute synthetic lines, write CSV, return DataFrame."""
    # Load one extra prior season so Week 1 of the earliest target season has history
    load_seasons = sorted({s - 1 for s in seasons} | set(seasons))
    print(f"Loading nflverse weekly data for seasons: {load_seasons}")
    weekly = load_weekly(years=load_seasons)

    print(f"Building synthetic props for target seasons: {seasons}")
    props = _build_rows(weekly, target_seasons=seasons, window=window, min_games=min_games)

    out_path = Path(out_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    props.to_csv(out_path, index=False)

    by_season = props.groupby("season").size()
    print(f"Generated {len(props):,} rows -> {out_path}")
    for season, count in by_season.items():
        print(f"  {season}: {count:,} rows")

    return props


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate synthetic NFL prop lines from trailing player stat averages."
    )
    parser.add_argument("--seasons", default="2024,2025", help="Comma-separated target seasons (default: 2024,2025)")
    parser.add_argument("--window", type=int, default=4, help="Rolling average window (default: 4)")
    parser.add_argument("--min-games", type=int, default=3, help="Minimum prior games required (default: 3)")
    parser.add_argument("--out-file", default="docs/synthetic_replay_props.csv", help="Output CSV path")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    seasons = [int(s.strip()) for s in args.seasons.split(",")]
    generate(
        seasons=seasons,
        window=args.window,
        min_games=args.min_games,
        out_file=Path(args.out_file),
    )
