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

import numpy as np
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

TRAINING_EXTRA_COLUMNS = [
    "actual_value", "outcome_over",
    "prior_games", "line_source", "line_window", "synthetic_source_version",
    "market_source", "market_prob_over_no_vig", "market_prob_under_no_vig", "vig_rate",
    "line_outlier_flag", "odds_outlier_flag", "eligible_for_training", "exclusion_reason",
]

TRAINING_OUTPUT_COLUMNS = OUTPUT_COLUMNS + TRAINING_EXTRA_COLUMNS

_ODDS_OVER = -110
_ODDS_UNDER = -110
_TRAINING_BOOK = "synthetic_surrogate"
_MARKET_SOURCE = "synthetic_surrogate_v1"
_SYNTHETIC_SOURCE_VERSION = "synthetic_props_training_v1"
_LINE_SOURCE = "shifted_trailing_mean_floor_plus_half"
_SHRINKAGE_K = 20.0
_NO_VIG_MIN = 0.08
_NO_VIG_MAX = 0.92
_ODDS_OUTLIER_ABS = 800
_YARDAGE_VOLUME_STATS = frozenset({
    "passing_yards", "rushing_yards", "receiving_yards",
    "receptions", "carries", "completions",
})
_TD_INT_STATS = frozenset({
    "passing_tds", "rushing_tds", "receiving_tds", "interceptions",
})


def _round_line(value: float) -> float:
    """Round to floor+0.5 - matches sportsbook convention and avoids pushes."""
    return math.floor(value) + 0.5


def _round_american_to_nearest_five(odds: float) -> int:
    rounded = int(round(abs(float(odds)) / 5.0) * 5)
    rounded = max(100, rounded)
    return -rounded if odds < 0 else rounded


def _prob_to_american(prob: float) -> int:
    p = float(np.clip(prob, 1e-6, 1.0 - 1e-6))
    if p > 0.5:
        return _round_american_to_nearest_five(-100.0 * p / (1.0 - p))
    return _round_american_to_nearest_five(100.0 * (1.0 - p) / p)


def _vig_rate_for_stat(stat: str) -> float:
    if stat in _TD_INT_STATS:
        return 0.07
    return 0.045


def _chronology_value(season: int, week: int) -> int:
    return int(season) * 100 + int(week)


def _append_reason(existing: object, reason: str) -> str:
    if existing is None or pd.isna(existing) or str(existing) == "":
        return reason
    return f"{existing};{reason}"


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


def _history_by_player_stat(weekly: pd.DataFrame) -> dict[str, dict[str, tuple[np.ndarray, np.ndarray]]]:
    df = weekly.sort_values(["player_id", "season", "week"]).copy()
    df["_chronology"] = [
        _chronology_value(season, week)
        for season, week in zip(df["season"].astype(int), df["week"].astype(int))
    ]

    history: dict[str, dict[str, tuple[np.ndarray, np.ndarray]]] = {}
    for stat in ALL_STATS:
        if stat not in df.columns:
            continue
        stat_history: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for player_id, group in df.groupby("player_id", sort=False):
            ordered = group.sort_values(["season", "week"])
            stat_history[str(player_id)] = (
                ordered["_chronology"].to_numpy(dtype=int),
                ordered[stat].fillna(0.0).to_numpy(dtype=float),
            )
        history[stat] = stat_history
    return history


def _actual_value_lookup(weekly: pd.DataFrame) -> dict[tuple[str, int, int, str], float]:
    lookup: dict[tuple[str, int, int, str], float] = {}
    deduped = weekly.drop_duplicates(subset=["player_id", "season", "week"], keep="first")
    for stat in ALL_STATS:
        if stat not in deduped.columns:
            continue
        for row in deduped[["player_id", "season", "week", stat]].itertuples(index=False):
            value = getattr(row, stat)
            if pd.notna(value):
                lookup[(str(row.player_id), int(row.season), int(row.week), stat)] = float(value)
    return lookup


def _market_probability_from_history(
    history: tuple[np.ndarray, np.ndarray] | None,
    *,
    season: int,
    week: int,
    line: float,
) -> tuple[float, int]:
    if history is None:
        return 0.5, 0

    chronology, values = history
    target_chronology = _chronology_value(season, week)
    prior_values = values[chronology < target_chronology]
    prior_games = int(len(prior_values))
    if prior_games == 0:
        return 0.5, 0

    hits = (prior_values > float(line)).astype(float)
    weights = np.arange(1.0, prior_games + 1.0, dtype=float)
    empirical = float(np.average(hits, weights=weights))
    shrink_weight = prior_games / (prior_games + _SHRINKAGE_K)
    no_vig = 0.5 + shrink_weight * (empirical - 0.5)
    return float(np.clip(no_vig, _NO_VIG_MIN, _NO_VIG_MAX)), prior_games


def _apply_training_exclusions(training: pd.DataFrame) -> pd.DataFrame:
    result = training.copy()
    result["eligible_for_training"] = True
    result["exclusion_reason"] = ""

    unsupported = ~result["stat"].isin(ALL_STATS)
    missing_actual = result["actual_value"].isna() | result["outcome_over"].isna()
    invalid_odds = (
        result["over_odds"].isna()
        | result["under_odds"].isna()
        | (result["over_odds"].astype(float).abs() < 100.0)
        | (result["under_odds"].astype(float).abs() < 100.0)
    )
    duplicate_keys = result.duplicated(subset=["player_id", "season", "week", "stat"], keep=False)

    exclusion_masks = (
        (unsupported, "unsupported_stat"),
        (missing_actual, "missing_actual_outcome"),
        (invalid_odds, "invalid_odds"),
        (duplicate_keys, "duplicate_key"),
    )
    for mask, reason in exclusion_masks:
        result.loc[mask, "eligible_for_training"] = False
        result.loc[mask, "exclusion_reason"] = result.loc[mask, "exclusion_reason"].map(
            lambda existing: _append_reason(existing, reason)
        )

    return result


def _add_line_outlier_flags(training: pd.DataFrame) -> pd.DataFrame:
    result = training.copy()
    result["line_outlier_flag"] = False
    for (_, _), group in result.groupby(["season", "stat"], sort=False):
        q1 = float(group["line"].quantile(0.25))
        q3 = float(group["line"].quantile(0.75))
        iqr = q3 - q1
        low = q1 - 1.5 * iqr
        high = q3 + 1.5 * iqr
        mask = (result.index.isin(group.index)) & ((result["line"] < low) | (result["line"] > high))
        result.loc[mask, "line_outlier_flag"] = True
    return result


def _build_training_rows(
    weekly: pd.DataFrame,
    props: pd.DataFrame,
    *,
    window: int,
) -> pd.DataFrame:
    """Add leakage-safe synthetic market probabilities, odds, outcomes, and flags."""
    if props.empty:
        return pd.DataFrame(columns=TRAINING_OUTPUT_COLUMNS)

    history = _history_by_player_stat(weekly)
    actual_lookup = _actual_value_lookup(weekly)

    rows: list[dict[str, object]] = []
    for record in props.to_dict("records"):
        row = dict(record)
        stat = str(row["stat"])
        player_id = str(row["player_id"])
        season = int(row["season"])
        week = int(row["week"])
        line = float(row["line"])

        no_vig_over, prior_games = _market_probability_from_history(
            history.get(stat, {}).get(player_id),
            season=season,
            week=week,
            line=line,
        )
        no_vig_under = float(1.0 - no_vig_over)
        vig_rate = _vig_rate_for_stat(stat)
        over_odds = _prob_to_american(no_vig_over * (1.0 + vig_rate))
        under_odds = _prob_to_american(no_vig_under * (1.0 + vig_rate))

        actual_value = actual_lookup.get((player_id, season, week, stat), np.nan)
        outcome_over = float(actual_value > line) if pd.notna(actual_value) else np.nan

        row.update({
            "book": _TRAINING_BOOK,
            "over_odds": over_odds,
            "under_odds": under_odds,
            "actual_value": actual_value,
            "outcome_over": outcome_over,
            "prior_games": prior_games,
            "line_source": _LINE_SOURCE,
            "line_window": int(window),
            "synthetic_source_version": _SYNTHETIC_SOURCE_VERSION,
            "market_source": _MARKET_SOURCE,
            "market_prob_over_no_vig": no_vig_over,
            "market_prob_under_no_vig": no_vig_under,
            "vig_rate": vig_rate,
            "odds_outlier_flag": abs(over_odds) > _ODDS_OUTLIER_ABS or abs(under_odds) > _ODDS_OUTLIER_ABS,
        })
        rows.append(row)

    training = pd.DataFrame(rows)
    training = _add_line_outlier_flags(training)
    training = _apply_training_exclusions(training)
    return training[TRAINING_OUTPUT_COLUMNS]


def generate(
    seasons: list[int],
    window: int = 4,
    min_games: int = 3,
    out_file: Path = Path("docs/synthetic_replay_props.csv"),
    *,
    emit_training_dataset: bool = False,
    training_out_file: Path = Path("docs/training/synthetic_props_training.csv"),
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

    if emit_training_dataset:
        training_props = _build_training_rows(weekly, props, window=window)
        training_path = Path(training_out_file)
        training_path.parent.mkdir(parents=True, exist_ok=True)
        training_props.to_csv(training_path, index=False)
        eligible = int(training_props["eligible_for_training"].sum()) if not training_props.empty else 0
        print(
            f"Generated {len(training_props):,} training rows "
            f"({eligible:,} eligible) -> {training_path}"
        )

    return props


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate synthetic NFL prop lines from trailing player stat averages."
    )
    parser.add_argument("--seasons", default="2024,2025", help="Comma-separated target seasons (default: 2024,2025)")
    parser.add_argument("--window", type=int, default=4, help="Rolling average window (default: 4)")
    parser.add_argument("--min-games", type=int, default=3, help="Minimum prior games required (default: 3)")
    parser.add_argument("--out-file", default="docs/synthetic_replay_props.csv", help="Output CSV path")
    parser.add_argument("--emit-training-dataset", action="store_true", help="Also write a training-grade synthetic odds dataset")
    parser.add_argument(
        "--training-out-file",
        default="docs/training/synthetic_props_training.csv",
        help="Training dataset output CSV path",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    seasons = [int(s.strip()) for s in args.seasons.split(",")]
    generate(
        seasons=seasons,
        window=args.window,
        min_games=args.min_games,
        out_file=Path(args.out_file),
        emit_training_dataset=args.emit_training_dataset,
        training_out_file=Path(args.training_out_file),
    )
