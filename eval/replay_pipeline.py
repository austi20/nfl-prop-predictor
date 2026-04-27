"""Step 4 paper-trade replay pipeline from local historical prop lines."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from data.nflverse_loader import TRAIN_YEARS
from data.weather import archive_available
from eval.calibration_pipeline import assert_disjoint_years, build_calibration_rows, load_props_file
from eval.parlay_builder import build_parlay_candidates, summarize_parlays
from eval.prop_pricer import PropCalibrator, build_paper_trade_picks, summarize_paper_trade

DEFAULT_SAME_GAME_PENALTY = 0.97
DEFAULT_SAME_TEAM_PENALTY = 0.985


def _parse_csv_ints(raw: str | None) -> list[int] | None:
    if not raw:
        return None
    return [int(part) for part in raw.split(",") if part.strip()]


def _parse_csv_strings(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [part.strip() for part in raw.split(",") if part.strip()]


def _apply_replay_filters(
    props_df: pd.DataFrame,
    *,
    replay_years: list[int] | None = None,
    weeks: list[int] | None = None,
    stats: list[str] | None = None,
    books: list[str] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    filtered = props_df.copy()
    metadata: dict[str, Any] = {
        "input_rows": int(len(filtered)),
        "applied_filters": {},
    }

    if replay_years:
        filtered = filtered[filtered["season"].isin(replay_years)].copy()
        metadata["applied_filters"]["replay_years"] = replay_years
    if weeks:
        filtered = filtered[filtered["week"].isin(weeks)].copy()
        metadata["applied_filters"]["weeks"] = weeks
    if stats:
        stat_values = {str(stat).strip() for stat in stats}
        filtered = filtered[filtered["stat"].astype(str).isin(stat_values)].copy()
        metadata["applied_filters"]["stats"] = sorted(stat_values)
    if books:
        book_values = {str(book).strip() for book in books}
        filtered = filtered[filtered["book"].astype(str).isin(book_values)].copy()
        metadata["applied_filters"]["books"] = sorted(book_values)

    metadata["rows_after_filters"] = int(len(filtered))
    return filtered, metadata


def _edge_bucket(edge_value: float) -> str:
    if edge_value < 0.05:
        return "<0.05"
    if edge_value < 0.10:
        return "0.05-0.10"
    if edge_value < 0.15:
        return "0.10-0.15"
    return "0.15+"


def _build_breakdown(picks: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    columns = group_cols + [
        "n_bets",
        "wins",
        "losses",
        "pushes",
        "staked_units",
        "profit_units",
        "roi",
        "win_rate",
    ]
    if picks.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, Any]] = []
    for key, group in picks.groupby(group_cols, dropna=False, sort=True):
        values = key if isinstance(key, tuple) else (key,)
        row = {col: value for col, value in zip(group_cols, values)}
        for col in group_cols:
            if row[col] == "" or pd.isna(row[col]):
                row[col] = "(unknown)"
        row.update(summarize_paper_trade(group))
        rows.append(row)

    breakdown = pd.DataFrame(rows)
    if group_cols == ["season", "week"]:
        return breakdown.sort_values(["season", "week"]).reset_index(drop=True)
    return breakdown.sort_values(["profit_units", "roi", "n_bets"], ascending=[False, False, False]).reset_index(drop=True)


def _build_breakdowns(picks: pd.DataFrame) -> dict[str, pd.DataFrame]:
    picks_with_edges = picks.copy()
    if picks_with_edges.empty:
        picks_with_edges["edge_bucket"] = pd.Series(dtype=object)
    else:
        picks_with_edges["edge_bucket"] = picks_with_edges["selected_edge"].map(_edge_bucket)

    return {
        "season": _build_breakdown(picks_with_edges, ["season"]),
        "week": _build_breakdown(picks_with_edges, ["season", "week"]),
        "stat": _build_breakdown(picks_with_edges, ["stat"]),
        "book": _build_breakdown(picks_with_edges, ["book"]),
        "selected_side": _build_breakdown(picks_with_edges, ["selected_side"]),
        "edge_bucket": _build_breakdown(picks_with_edges, ["edge_bucket"]),
    }


def _top_by_expected_value_per_week(parlays: pd.DataFrame) -> pd.DataFrame:
    if parlays.empty:
        return parlays.copy()
    return (
        parlays.sort_values(
            ["season", "week", "expected_value_units", "joint_prob"],
            ascending=[True, True, False, False],
        )
        .groupby(["season", "week"], as_index=False, sort=False)
        .head(1)
        .reset_index(drop=True)
    )


def _combine_trade_frames(*frames: pd.DataFrame) -> pd.DataFrame:
    valid_frames = [
        frame[["result", "stake_units", "profit_units"]].copy()
        for frame in frames
        if not frame.empty
    ]
    if not valid_frames:
        return pd.DataFrame(columns=["result", "stake_units", "profit_units"])
    return pd.concat(valid_frames, ignore_index=True)


def _extract_best_and_worst(breakdown: pd.DataFrame, label_col: str) -> dict[str, Any]:
    if breakdown.empty:
        return {"best": None, "worst": None}

    ranked = breakdown.sort_values(["roi", "profit_units", "n_bets"], ascending=[False, False, False]).reset_index(drop=True)
    worst = breakdown.sort_values(["roi", "profit_units", "n_bets"], ascending=[True, True, False]).reset_index(drop=True)
    columns = [label_col, "profit_units", "roi", "n_bets"]
    return {
        "best": ranked.iloc[0][columns].to_dict(),
        "worst": worst.iloc[0][columns].to_dict(),
    }


def _interpret_replay(summary: dict[str, Any]) -> str:
    bets = float(summary["singles"]["n_bets"])
    roi = float(summary["singles"]["roi"])
    if bets < 25:
        return "Result looks noisy because the replay sample is still small. Treat it as a pipeline verification run more than a strategy verdict."
    if roi < 0.0:
        return "Result is not ready for live confidence yet. The replay pipeline may be stable, but the current selection policy or model stack still needs iteration."
    if roi < 0.03:
        return "Result looks usable for further review but still fairly noisy. The pipeline is behaving, yet the edge is thin enough that policy sensitivity should be checked."
    return "Result looks usable enough to keep moving, with positive replay economics after vig on this slice. It still deserves stress checks across seasons, books, and edge buckets before relying on it."


def _build_summary_payload(
    *,
    season_label: str,
    replay_years: list[int],
    weeks: list[int] | None,
    stats: list[str] | None,
    books: list[str] | None,
    min_edge: float,
    min_ev: float,
    stake: float,
    calibrator_path: Path | None,
    filter_metadata: dict[str, Any],
    row_metadata: dict[str, Any],
    pick_metadata: dict[str, Any],
    singles_summary: dict[str, float],
    parlay_summary: dict[str, float],
    baselines: dict[str, Any],
    breakdowns: dict[str, pd.DataFrame],
    same_game_penalty: float,
    same_team_penalty: float,
    max_picks_per_week: int | None,
    max_picks_per_player: int | None,
    max_picks_per_game: int | None,
    weather_archive_available: bool,
) -> dict[str, Any]:
    skipped_rows = {
        "unsupported_stat": int(row_metadata["skipped_rows"]["unsupported_stat"]),
        "missing_odds": int(row_metadata["skipped_rows"]["missing_odds"] + pick_metadata["skipped_rows"]["missing_odds"]),
        "missing_actual_outcome": int(row_metadata["skipped_rows"]["missing_actual_outcome"]),
        "no_selection_edge_threshold": int(pick_metadata["skipped_rows"]["edge_threshold"]),
        "no_bet": int(pick_metadata["skipped_rows"].get("no_bet", 0)),
        "max_picks_per_week": int(pick_metadata["skipped_rows"]["max_picks_per_week"]),
        "max_picks_per_player": int(pick_metadata["skipped_rows"]["max_picks_per_player"]),
        "max_picks_per_game": int(pick_metadata["skipped_rows"]["max_picks_per_game"]),
    }

    book_breakdown = breakdowns["book"]
    if not book_breakdown.empty:
        book_breakdown = book_breakdown[book_breakdown["book"] != "(unknown)"].reset_index(drop=True)

    payload: dict[str, Any] = {
        "season_label": season_label,
        "context": {
            "replay_years": replay_years,
            "weeks": weeks or [],
            "stats": stats or [],
            "books": books or [],
            "calibrator_path": str(calibrator_path) if calibrator_path else "",
        },
        "policy": {
            "min_edge": float(min_edge),
            "min_ev": float(min_ev),
            "stake": float(stake),
            "singles_evaluated_separately_from_parlays": True,
            "same_game_penalty": float(same_game_penalty),
            "same_team_penalty": float(same_team_penalty),
            "max_picks_per_week": max_picks_per_week,
            "max_picks_per_player": max_picks_per_player,
            "max_picks_per_game": max_picks_per_game,
        },
        "validation": {
            "input_rows": int(filter_metadata["input_rows"]),
            "rows_after_filters": int(filter_metadata["rows_after_filters"]),
            "rows_priced": int(row_metadata["output_rows"]),
            "selected_rows": int(pick_metadata["selected_rows"]),
            "weather_archive_available": bool(weather_archive_available),
            "applied_filters": filter_metadata["applied_filters"],
            "unsupported_stats_seen": row_metadata.get("unsupported_stats", []),
            "skipped_rows": skipped_rows,
        },
        "singles": singles_summary,
        "parlays": parlay_summary,
        "baselines": baselines,
        "leaders": {
            "stats": _extract_best_and_worst(breakdowns["stat"], "stat"),
            "books": _extract_best_and_worst(book_breakdown, "book"),
        },
    }
    payload["interpretation"] = _interpret_replay(payload)
    return payload


def run_replay(
    props_path: Path,
    *,
    calibrator_path: Path | None = None,
    min_edge: float = 0.05,
    min_ev: float | None = None,
    stake: float = 1.0,
    train_years: list[int] | None = None,
    replay_years: list[int] | None = None,
    weeks: list[int] | None = None,
    stats: list[str] | None = None,
    books: list[str] | None = None,
    max_picks_per_week: int | None = None,
    max_picks_per_player: int | None = None,
    max_picks_per_game: int | None = None,
    same_game_penalty: float = DEFAULT_SAME_GAME_PENALTY,
    same_team_penalty: float = DEFAULT_SAME_TEAM_PENALTY,
    parlay_legs: int = 2,
    max_parlay_candidates: int = 20,
    weekly: pd.DataFrame | None = None,
    use_future_row: bool = False,
) -> dict[str, Any]:
    props_df = load_props_file(Path(props_path), require_odds=True)
    replay_years = replay_years or sorted(set(int(x) for x in props_df["season"].unique().tolist()))
    if train_years is None:
        train_years = [int(year) for year in TRAIN_YEARS if int(year) not in set(replay_years)]
    assert_disjoint_years(list(train_years), list(replay_years))
    filtered_props, filter_metadata = _apply_replay_filters(
        props_df,
        replay_years=replay_years,
        weeks=weeks,
        stats=stats,
        books=books,
    )
    calibration_rows, row_metadata = build_calibration_rows(
        props_df=filtered_props,
        train_years=train_years,
        holdout_years=replay_years,
        weekly=weekly,
        strict_stats=False,
        require_odds=True,
        use_future_row=use_future_row,
        return_metadata=True,
    )

    calibrator = PropCalibrator.load(calibrator_path) if calibrator_path else None
    effective_min_ev = float(min_ev if min_ev is not None else min_edge)
    picks, pick_metadata = build_paper_trade_picks(
        calibration_rows,
        calibrator=calibrator,
        min_edge=min_edge,
        min_ev=effective_min_ev,
        stake=stake,
        max_picks_per_week=max_picks_per_week,
        max_picks_per_player=max_picks_per_player,
        max_picks_per_game=max_picks_per_game,
        return_metadata=True,
    )
    singles_summary = summarize_paper_trade(picks)
    parlays = build_parlay_candidates(
        picks,
        legs=parlay_legs,
        max_candidates=max_parlay_candidates,
        same_game_penalty=same_game_penalty,
        same_team_penalty=same_team_penalty,
        stake=stake,
    )
    parlay_summary = summarize_parlays(parlays)
    breakdowns = _build_breakdowns(picks)

    no_threshold_picks = build_paper_trade_picks(
        calibration_rows,
        calibrator=calibrator,
        min_edge=0.0,
        min_ev=0.0,
        stake=stake,
        max_picks_per_week=max_picks_per_week,
        max_picks_per_player=max_picks_per_player,
        max_picks_per_game=max_picks_per_game,
    )
    top_edge_only_picks = build_paper_trade_picks(
        calibration_rows,
        calibrator=calibrator,
        min_edge=min_edge,
        min_ev=effective_min_ev,
        stake=stake,
        max_picks_per_week=1,
        max_picks_per_player=max_picks_per_player,
        max_picks_per_game=max_picks_per_game,
    )
    top_parlay_per_week = _top_by_expected_value_per_week(parlays)
    combined_top_parlay_summary = summarize_paper_trade(_combine_trade_frames(picks, top_parlay_per_week))
    summary_payload = _build_summary_payload(
        season_label="-".join(str(year) for year in replay_years),
        replay_years=replay_years,
        weeks=weeks,
        stats=stats,
        books=books,
        min_edge=min_edge,
        min_ev=effective_min_ev,
        stake=stake,
        calibrator_path=calibrator_path,
        filter_metadata=filter_metadata,
        row_metadata=row_metadata,
        pick_metadata=pick_metadata,
        singles_summary=singles_summary,
        parlay_summary=parlay_summary,
        baselines={
            "current_policy_singles": singles_summary,
            "no_threshold_singles": summarize_paper_trade(no_threshold_picks),
            "top_edge_only_singles": summarize_paper_trade(top_edge_only_picks),
            "singles_plus_top_parlay_per_week": combined_top_parlay_summary,
        },
        breakdowns=breakdowns,
        same_game_penalty=same_game_penalty,
        same_team_penalty=same_team_penalty,
        max_picks_per_week=max_picks_per_week,
        max_picks_per_player=max_picks_per_player,
        max_picks_per_game=max_picks_per_game,
        weather_archive_available=archive_available(replay_years),
    )
    return {
        "rows": calibration_rows,
        "picks": picks,
        "parlays": parlays,
        "summary": singles_summary,
        "summary_payload": summary_payload,
        "singles_summary": singles_summary,
        "parlay_summary": parlay_summary,
        "breakdowns": breakdowns,
        "validation": summary_payload["validation"],
        "policy": summary_payload["policy"],
        "baselines": summary_payload["baselines"],
        "replay_years": replay_years,
        "weeks": weeks or [],
        "stats": stats or [],
        "books": books or [],
        "min_edge": min_edge,
        "min_ev": effective_min_ev,
        "stake": stake,
        "calibrator_path": str(calibrator_path) if calibrator_path else "",
    }


def _format_markdown_table(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return ["No rows."]

    display = df.copy()
    for col in display.columns:
        if pd.api.types.is_float_dtype(display[col]):
            if col in {"roi", "win_rate"}:
                display[col] = display[col].map(lambda value: f"{value:.2%}")
            else:
                display[col] = display[col].map(lambda value: f"{value:.3f}")

    headers = [str(col) for col in display.columns]
    rows = [headers, ["---"] * len(headers)]
    for record in display.astype(str).to_dict("records"):
        rows.append([record[col] for col in headers])
    return ["| " + " | ".join(row) + " |" for row in rows]


def save_replay_report(report: dict[str, Any], out_dir: Path, season_label: str) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    picks: pd.DataFrame = report["picks"]
    parlays: pd.DataFrame = report["parlays"]
    summary: dict[str, Any] = report["summary_payload"]
    breakdowns: dict[str, pd.DataFrame] = report["breakdowns"]

    (out_dir / f"paper_trade_picks_{season_label}.csv").write_text(
        picks.to_csv(index=False),
        encoding="utf-8",
    )
    (out_dir / f"paper_trade_parlays_{season_label}.csv").write_text(
        parlays.to_csv(index=False),
        encoding="utf-8",
    )
    (out_dir / f"paper_trade_summary_{season_label}.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    for name, breakdown in breakdowns.items():
        (out_dir / f"paper_trade_breakdown_by_{name}_{season_label}.csv").write_text(
            breakdown.to_csv(index=False),
            encoding="utf-8",
        )
        (out_dir / f"paper_trade_breakdown_by_{name}_{season_label}.json").write_text(
            json.dumps(breakdown.to_dict("records"), indent=2),
            encoding="utf-8",
        )

    validation = summary["validation"]
    policy = summary["policy"]
    singles = summary["singles"]
    parlay_summary = summary["parlays"]
    leaders = summary["leaders"]

    md_lines = [
        f"# Paper Trade Replay {season_label}",
        "",
        f"Replay years: {', '.join(str(year) for year in summary['context']['replay_years'])}",
        f"Minimum edge: {policy['min_edge']:.3f}",
        f"Stake per bet: {policy['stake']:.2f} units",
        "",
        "## Validation",
        "",
        f"- Input rows: {validation['input_rows']}",
        f"- Rows after filters: {validation['rows_after_filters']}",
        f"- Rows priced: {validation['rows_priced']}",
        f"- Selected rows: {validation['selected_rows']}",
        f"- Skipped unsupported stat: {validation['skipped_rows']['unsupported_stat']}",
        f"- Skipped missing odds: {validation['skipped_rows']['missing_odds']}",
        f"- Skipped missing actual outcome: {validation['skipped_rows']['missing_actual_outcome']}",
        f"- No selection because edge threshold not met: {validation['skipped_rows']['no_selection_edge_threshold']}",
        "",
        "## Singles",
        "",
        f"- Bets: {int(singles['n_bets'])}",
        f"- Wins: {int(singles['wins'])}",
        f"- Losses: {int(singles['losses'])}",
        f"- Pushes: {int(singles['pushes'])}",
        f"- Profit: {singles['profit_units']:.3f} units",
        f"- ROI: {singles['roi']:.3%}",
        f"- Win rate: {singles['win_rate']:.3%}",
        "",
        "## Parlays",
        "",
        f"- Candidates: {int(parlay_summary['n_parlays'])}",
        f"- Wins: {int(parlay_summary['wins'])}",
        f"- Losses: {int(parlay_summary['losses'])}",
        f"- Pushes: {int(parlay_summary['pushes'])}",
        f"- Profit: {parlay_summary['profit_units']:.3f} units",
        f"- ROI: {parlay_summary['roi']:.3%}",
        f"- Average expected value: {parlay_summary['avg_expected_value_units']:.3f} units",
        "",
        "## Baselines",
        "",
        f"- Current policy singles ROI: {summary['baselines']['current_policy_singles']['roi']:.3%}",
        f"- No-threshold singles ROI: {summary['baselines']['no_threshold_singles']['roi']:.3%}",
        f"- Top-edge-only singles ROI: {summary['baselines']['top_edge_only_singles']['roi']:.3%}",
        f"- Singles plus top parlay per week ROI: {summary['baselines']['singles_plus_top_parlay_per_week']['roi']:.3%}",
        "",
        "## Diagnostics",
        "",
    ]

    if leaders["stats"]["best"] is not None:
        md_lines.append(
            f"- Best stat: `{leaders['stats']['best']['stat']}` "
            f"(ROI={leaders['stats']['best']['roi']:.3%}, profit={leaders['stats']['best']['profit_units']:.3f})"
        )
        md_lines.append(
            f"- Worst stat: `{leaders['stats']['worst']['stat']}` "
            f"(ROI={leaders['stats']['worst']['roi']:.3%}, profit={leaders['stats']['worst']['profit_units']:.3f})"
        )
    if leaders["books"]["best"] is not None:
        md_lines.append(
            f"- Best book: `{leaders['books']['best']['book']}` "
            f"(ROI={leaders['books']['best']['roi']:.3%}, profit={leaders['books']['best']['profit_units']:.3f})"
        )
        md_lines.append(
            f"- Worst book: `{leaders['books']['worst']['book']}` "
            f"(ROI={leaders['books']['worst']['roi']:.3%}, profit={leaders['books']['worst']['profit_units']:.3f})"
        )

    md_lines.extend(["", "## Weekly Breakdown", ""])
    md_lines.extend(_format_markdown_table(breakdowns["week"].head(12)))
    md_lines.extend(["", "## Stat Breakdown", ""])
    md_lines.extend(_format_markdown_table(breakdowns["stat"].head(12)))
    md_lines.extend(["", "## Book Breakdown", ""])
    md_lines.extend(_format_markdown_table(breakdowns["book"].head(12)))
    md_lines.extend(["", "## Interpretation", "", summary["interpretation"], ""])

    if not parlays.empty:
        top = parlays.head(5)
        md_lines.append("## Top Parlays")
        md_lines.append("")
        for _, row in top.iterrows():
            md_lines.append(
                f"- {int(row['season'])} Week {int(row['week'])}: `{row['parlay_label']}` "
                f"(EV={row['expected_value_units']:.3f}, joint_prob={row['joint_prob']:.3f}, result={row['result']})"
            )
        md_lines.append("")

    (out_dir / f"paper_trade_summary_{season_label}.md").write_text(
        "\n".join(md_lines),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run paper-trade replay from a local prop-lines file")
    parser.add_argument("--props-file", required=True)
    parser.add_argument("--calibrator-path", default=None)
    parser.add_argument("--min-edge", type=float, default=0.05)
    parser.add_argument("--min-ev", type=float, default=None)
    parser.add_argument("--stake", type=float, default=1.0)
    parser.add_argument("--train-years", default=None)
    parser.add_argument("--replay-years", default=None)
    parser.add_argument("--weeks", default=None)
    parser.add_argument("--stats", default=None)
    parser.add_argument("--books", default=None)
    parser.add_argument("--max-picks-per-week", type=int, default=None)
    parser.add_argument("--max-picks-per-player", type=int, default=None)
    parser.add_argument("--max-picks-per-game", type=int, default=None)
    parser.add_argument("--same-game-penalty", type=float, default=DEFAULT_SAME_GAME_PENALTY)
    parser.add_argument("--same-team-penalty", type=float, default=DEFAULT_SAME_TEAM_PENALTY)
    parser.add_argument("--parlay-legs", type=int, default=2)
    parser.add_argument("--max-parlay-candidates", type=int, default=20)
    parser.add_argument("--out-dir", default="docs")
    args = parser.parse_args()

    replay_years = _parse_csv_ints(args.replay_years)
    report = run_replay(
        props_path=Path(args.props_file),
        calibrator_path=Path(args.calibrator_path) if args.calibrator_path else None,
        min_edge=args.min_edge,
        min_ev=args.min_ev,
        stake=args.stake,
        train_years=_parse_csv_ints(args.train_years),
        replay_years=replay_years,
        weeks=_parse_csv_ints(args.weeks),
        stats=_parse_csv_strings(args.stats),
        books=_parse_csv_strings(args.books),
        max_picks_per_week=args.max_picks_per_week,
        max_picks_per_player=args.max_picks_per_player,
        max_picks_per_game=args.max_picks_per_game,
        same_game_penalty=args.same_game_penalty,
        same_team_penalty=args.same_team_penalty,
        parlay_legs=args.parlay_legs,
        max_parlay_candidates=args.max_parlay_candidates,
    )
    season_label = "-".join(str(year) for year in report["replay_years"])
    save_replay_report(report, Path(args.out_dir), season_label)
    print(json.dumps(report["summary_payload"], indent=2))


if __name__ == "__main__":
    main()
