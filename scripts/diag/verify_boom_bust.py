"""Live path boom/bust calibration check on 2025 games.

Runs the live build_fantasy_summary for every player who played each week
(the 2025 board itself is thin for past weeks), joins to actual
fantasy_points_ppr, and reports predicted vs hit rate for boom
(actual >= boom_cutoff) and bust (actual <= bust_cutoff), by position and by
projection bucket. Players who did not play are not scored, so bust here
excludes DNP weeks.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

import os

os.environ["NFL_APP_PREWARM_PROP_BOARD"] = "0"
os.environ["NFL_APP_PREWARM_FANTASY_SLATE"] = "0"
os.environ["NFL_APP_REFRESH_FEEDS_ON_START"] = "0"
os.environ["NFL_APP_USE_MARKET_ANCHOR"] = "0"
os.environ["NFL_APP_USE_LIVE_FORECAST"] = "0"

import argparse

from api.services.fantasy_service import build_fantasy_summary
from api.settings import AppSettings
from data.nflverse_loader import load_weekly

SEASON = 2025
POSITIONS = ("QB", "RB", "WR", "TE")
BUCKETS = [(0.0, 8.0, "<8"), (8.0, 14.0, "8-14"), (14.0, float("inf"), "14+")]
MIN_PROJECTION = 3.0
N_BINS = 10

OUT_PATH = _ROOT / "docs" / "diag" / "boom_bust_validation.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--weeks", type=str, default="4-17", help="e.g. 4-17 or 4-17:2")
    return parser.parse_args()


def parse_weeks(spec: str) -> list[int]:
    step = 1
    if ":" in spec:
        spec, step_str = spec.split(":")
        step = int(step_str)
    lo, hi = spec.split("-")
    return list(range(int(lo), int(hi) + 1, step))


def bucket_for(points: float) -> str:
    for lo, hi, label in BUCKETS:
        if lo <= points < hi:
            return label
    return BUCKETS[-1][2]


def collect_rows(weeks: list[int]) -> tuple[list[dict], dict[str, int]]:
    """Project every player who played each week through the live
    build_fantasy_summary and join to his actual points. Returns rows and a
    per position count of rows dropped for a projection under 3."""
    settings = AppSettings()
    weekly = load_weekly([SEASON])
    weekly = weekly[weekly["position"].isin(POSITIONS)]

    rows: list[dict] = []
    dropped_by_position: dict[str, int] = {p: 0 for p in POSITIONS}

    for week in weeks:
        played = weekly[weekly["week"] == week]
        print(f"week {week}: {len(played)} players", flush=True)
        for _, r in played.iterrows():
            try:
                summary = build_fantasy_summary(
                    settings,
                    player_id=str(r["player_id"]),
                    season=SEASON,
                    week=week,
                    position=r["position"],
                    recent_team=r["recent_team"],
                    opponent_team=r["opponent_team"],
                    game_id=str(r.get("game_id") or ""),
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  skip {r['player_id']}: {exc}")
                continue
            if summary.projected_points < MIN_PROJECTION:
                dropped_by_position[r["position"]] += 1
                continue
            rows.append(
                {
                    "position": r["position"],
                    "week": week,
                    "projected_points": summary.projected_points,
                    "boom_probability": summary.boom_probability,
                    "bust_probability": summary.bust_probability,
                    "boom_cutoff": summary.boom_cutoff,
                    "bust_cutoff": summary.bust_cutoff,
                    "actual": float(r["fantasy_points_ppr"] or 0.0),
                }
            )
    return rows, dropped_by_position


def binned_calibration_error(rows: list[dict], prob_key: str, hit_fn) -> float:
    """10 equal width bins over predicted probability [0,1]; |mean pred - hit
    rate| per bin, weighted by bin count."""
    if not rows:
        return 0.0
    bins: list[list[dict]] = [[] for _ in range(N_BINS)]
    for row in rows:
        p = row[prob_key]
        idx = min(int(p * N_BINS), N_BINS - 1)
        bins[idx].append(row)
    total_n = len(rows)
    weighted_error = 0.0
    for bin_rows in bins:
        if not bin_rows:
            continue
        mean_pred = sum(r[prob_key] for r in bin_rows) / len(bin_rows)
        hit_rate = sum(1.0 for r in bin_rows if hit_fn(r)) / len(bin_rows)
        weighted_error += (len(bin_rows) / total_n) * abs(mean_pred - hit_rate)
    return weighted_error


def hit_boom(row: dict) -> bool:
    return row["actual"] >= row["boom_cutoff"]


def hit_bust(row: dict) -> bool:
    return row["actual"] <= row["bust_cutoff"]


def build_table(rows: list[dict]) -> list[str]:
    lines = []
    header = (
        "| position | bucket | n | pred boom | actual boom | pred bust | actual bust |"
    )
    sep = "|---|---|---|---|---|---|---|"
    lines.append(header)
    lines.append(sep)
    for position in POSITIONS:
        pos_rows = [r for r in rows if r["position"] == position]
        for _, _, label in BUCKETS:
            bucket_rows = [r for r in pos_rows if bucket_for(r["projected_points"]) == label]
            n = len(bucket_rows)
            if n == 0:
                lines.append(f"| {position} | {label} | 0 | - | - | - | - |")
                continue
            pred_boom = sum(r["boom_probability"] for r in bucket_rows) / n
            actual_boom = sum(1.0 for r in bucket_rows if hit_boom(r)) / n
            pred_bust = sum(r["bust_probability"] for r in bucket_rows) / n
            actual_bust = sum(1.0 for r in bucket_rows if hit_bust(r)) / n
            lines.append(
                f"| {position} | {label} | {n} | {pred_boom:.3f} | {actual_boom:.3f} "
                f"| {pred_bust:.3f} | {actual_bust:.3f} |"
            )
    lines.append("")
    lines.append("| position | pooled binned calib error (boom) | pooled binned calib error (bust) |")
    lines.append("|---|---|---|")
    for position in POSITIONS:
        pos_rows = [r for r in rows if r["position"] == position]
        boom_err = binned_calibration_error(pos_rows, "boom_probability", hit_boom)
        bust_err = binned_calibration_error(pos_rows, "bust_probability", hit_bust)
        lines.append(f"| {position} | {boom_err:.4f} | {bust_err:.4f} |")
    return lines


def main() -> None:
    args = parse_args()
    weeks = parse_weeks(args.weeks)
    print(f"weeks: {weeks}")

    rows, dropped_by_position = collect_rows(weeks)

    print(f"\nscored rows: {len(rows)}")
    print("dropped rows by position (projection < 3):")
    for position in POSITIONS:
        print(f"  {position}: {dropped_by_position[position]}")

    table_lines = build_table(rows)
    print()
    for line in table_lines:
        print(line)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("# Boom/bust live path validation\n\n")
        f.write(f"Season {SEASON}, weeks {weeks[0]}-{weeks[-1]}. ")
        f.write(f"{len(rows)} scored rows, projection >= {MIN_PROJECTION}.\n\n")
        f.write("Players who played, projected through the live path. DNP weeks excluded. "
                "Dropped for projection < 3:\n\n")
        f.write("| position | dropped |\n|---|---|\n")
        for position in POSITIONS:
            f.write(f"| {position} | {dropped_by_position[position]} |\n")
        f.write("\n")
        f.write("\n".join(table_lines))
        f.write("\n")
    print(f"\nwritten -> {OUT_PATH}")


if __name__ == "__main__":
    main()
