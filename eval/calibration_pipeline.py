"""Step 3 calibration pipeline.

Given a file of closing player prop lines for a holdout season, this module:
- computes raw model over probabilities from the existing position models
- merges actual outcomes from weekly nflverse stats
- fits isotonic and Platt calibrators
- saves the best calibrator plus reliability artifacts

Expected prop-line columns:
- player_id
- season
- week
- stat
- line

Optional columns:
- opp_team
- book
- over_odds
- under_odds
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from data.nflverse_loader import HOLDOUT_YEARS, TRAIN_YEARS, load_weekly
from eval.prop_pricer import PropCalibrator, reliability_diagram
from models.qb import QBModel
from models.rb import RBModel
from models.wr_te import WRTEModel


@dataclass(frozen=True)
class StatSpec:
    stat: str
    model_name: str
    actual_column: str


STAT_SPECS: dict[str, StatSpec] = {
    "passing_yards": StatSpec("passing_yards", "qb", "passing_yards"),
    "passing_tds": StatSpec("passing_tds", "qb", "passing_tds"),
    "interceptions": StatSpec("interceptions", "qb", "interceptions"),
    "completions": StatSpec("completions", "qb", "completions"),
    "rushing_yards": StatSpec("rushing_yards", "rb", "rushing_yards"),
    "carries": StatSpec("carries", "rb", "carries"),
    "rushing_tds": StatSpec("rushing_tds", "rb", "rushing_tds"),
    "receptions": StatSpec("receptions", "wr_te", "receptions"),
    "receiving_yards": StatSpec("receiving_yards", "wr_te", "receiving_yards"),
    "receiving_tds": StatSpec("receiving_tds", "wr_te", "receiving_tds"),
}


def _model_map() -> dict[str, QBModel | RBModel | WRTEModel]:
    return {
        "qb": QBModel(),
        "rb": RBModel(),
        "wr_te": WRTEModel(),
    }


def _brier_score(raw_probs: np.ndarray, outcomes: np.ndarray) -> float:
    if len(raw_probs) == 0:
        return 0.0
    return float(np.mean((raw_probs - outcomes) ** 2))


def _load_props_file(path: Path) -> pd.DataFrame:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(path)
    elif suffix in {".parquet", ".pq"}:
        df = pd.read_parquet(path)
    elif suffix == ".json":
        df = pd.read_json(path)
    else:
        raise ValueError(f"Unsupported props file type: {suffix}")

    required = {"player_id", "season", "week", "stat", "line"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required prop columns: {sorted(missing)}")
    return df.copy()


def _fit_models(
    train_years: list[int],
    holdout_years: list[int],
    weekly: pd.DataFrame,
) -> dict[str, QBModel | RBModel | WRTEModel]:
    models = _model_map()
    fit_and_eval_years = sorted(set(train_years + holdout_years))
    weekly_window = weekly[weekly["season"].isin(fit_and_eval_years)].copy()
    for model in models.values():
        model.fit(train_years, weekly=weekly_window)
    return models


def build_calibration_rows(
    props_df: pd.DataFrame,
    train_years: list[int] | None = None,
    holdout_years: list[int] | None = None,
    weekly: pd.DataFrame | None = None,
) -> pd.DataFrame:
    train_years = list(TRAIN_YEARS if train_years is None else train_years)
    holdout_years = list(HOLDOUT_YEARS if holdout_years is None else holdout_years)

    props = props_df.copy()
    props["stat"] = props["stat"].astype(str)
    unsupported = sorted(set(props["stat"]) - set(STAT_SPECS))
    if unsupported:
        raise ValueError(f"Unsupported prop stats: {unsupported}")

    if weekly is None:
        years = sorted(set(train_years + holdout_years))
        weekly = load_weekly(years)

    actual_columns = sorted({spec.actual_column for spec in STAT_SPECS.values()})
    outcome_cols = ["player_id", "season", "week", *actual_columns]
    weekly_outcomes = weekly[outcome_cols].copy()
    weekly_outcomes = weekly_outcomes.drop_duplicates(subset=["player_id", "season", "week"])

    models = _fit_models(train_years, holdout_years, weekly)
    holdout_props = props[props["season"].isin(holdout_years)].copy()

    rows: list[dict[str, Any]] = []
    for _, row in holdout_props.iterrows():
        spec = STAT_SPECS[str(row["stat"])]
        model = models[spec.model_name]
        opp_team = str(row["opp_team"]) if "opp_team" in row and pd.notna(row["opp_team"]) else ""
        preds = model.predict(
            player_id=str(row["player_id"]),
            week=int(row["week"]),
            season=int(row["season"]),
            opp_team=opp_team,
        )
        raw_prob = float(preds[spec.stat].prob_over(float(row["line"])))

        actual_match = weekly_outcomes[
            (weekly_outcomes["player_id"].astype(str) == str(row["player_id"]))
            & (weekly_outcomes["season"] == int(row["season"]))
            & (weekly_outcomes["week"] == int(row["week"]))
        ]
        if actual_match.empty:
            continue

        actual_value = float(actual_match.iloc[0][spec.actual_column])
        outcome = float(actual_value > float(row["line"]))
        rows.append({
            "player_id": str(row["player_id"]),
            "season": int(row["season"]),
            "week": int(row["week"]),
            "stat": spec.stat,
            "line": float(row["line"]),
            "raw_prob": raw_prob,
            "actual_value": actual_value,
            "outcome": outcome,
            "book": str(row["book"]) if "book" in row and pd.notna(row["book"]) else "",
            "over_odds": float(row["over_odds"]) if "over_odds" in row and pd.notna(row["over_odds"]) else np.nan,
            "under_odds": float(row["under_odds"]) if "under_odds" in row and pd.notna(row["under_odds"]) else np.nan,
        })

    return pd.DataFrame(rows)


def fit_calibrators(
    calibration_rows: pd.DataFrame,
    out_dir: Path,
    season_label: str,
) -> dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if calibration_rows.empty:
        raise ValueError("No calibration rows were produced")

    raw = calibration_rows["raw_prob"].to_numpy(dtype=float)
    outcomes = calibration_rows["outcome"].to_numpy(dtype=float)

    results: dict[str, Any] = {}
    best_method: str | None = None
    best_ece = float("inf")

    for method in ("isotonic", "platt"):
        calibrator = PropCalibrator(method=method).fit(raw, outcomes)
        calibrated = np.asarray(calibrator.calibrate(raw), dtype=float)
        plot_path = out_dir / f"reliability_{season_label}_{method}.png"
        stats = reliability_diagram(calibrated, outcomes, n_bins=10, save_path=plot_path)
        brier = _brier_score(calibrated, outcomes)
        artifact_path = out_dir / f"prop_calibrator_{season_label}_{method}.joblib"
        calibrator.save(artifact_path)

        results[method] = {
            "ece": float(stats["ece"]),
            "brier": brier,
            "artifact_path": str(artifact_path),
            "plot_path": str(plot_path),
        }
        if stats["ece"] < best_ece:
            best_ece = float(stats["ece"])
            best_method = method

    assert best_method is not None
    best_src = Path(results[best_method]["artifact_path"])
    best_plot_src = Path(results[best_method]["plot_path"])
    best_artifact = out_dir / f"prop_calibrator_{season_label}.joblib"
    best_plot = out_dir / f"reliability_{season_label}.png"
    best_artifact.write_bytes(best_src.read_bytes())
    best_plot.write_bytes(best_plot_src.read_bytes())

    return {
        "season_label": season_label,
        "n_rows": int(len(calibration_rows)),
        "best_method": best_method,
        "artifact_path": str(best_artifact),
        "plot_path": str(best_plot),
        "methods": results,
    }


def save_calibration_report(
    report: dict[str, Any],
    rows: pd.DataFrame,
    docs_dir: Path,
    season_label: str,
) -> None:
    docs_dir = Path(docs_dir)
    docs_dir.mkdir(parents=True, exist_ok=True)

    summary_json = docs_dir / f"calibration_report_{season_label}.json"
    summary_md = docs_dir / f"calibration_report_{season_label}.md"
    rows_path = docs_dir / f"calibration_rows_{season_label}.csv"

    summary_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    rows.to_csv(rows_path, index=False)

    lines = [
        f"# Calibration Report {season_label}",
        "",
        f"Rows: {report['n_rows']}",
        f"Best method: {report['best_method']}",
        f"Saved calibrator: `{report['artifact_path']}`",
        f"Reliability plot: `{report['plot_path']}`",
        "",
        "## Method Metrics",
        "",
    ]
    for method, metrics in report["methods"].items():
        lines.append(
            f"- `{method}`: ECE={metrics['ece']:.4f}, "
            f"Brier={metrics['brier']:.4f}, "
            f"artifact=`{metrics['artifact_path']}`"
        )
    lines.append("")
    lines.append(f"Calibration rows exported to `{rows_path}`")
    lines.append("")
    summary_md.write_text("\n".join(lines), encoding="utf-8")


def run_calibration(
    props_path: Path,
    train_years: list[int] | None = None,
    holdout_years: list[int] | None = None,
    docs_dir: Path = Path("docs"),
    model_dir: Path = Path("models") / "calibration",
) -> dict[str, Any]:
    train_years = list(TRAIN_YEARS if train_years is None else train_years)
    holdout_years = list(HOLDOUT_YEARS if holdout_years is None else holdout_years)
    season_label = "-".join(str(year) for year in holdout_years)

    props_df = _load_props_file(Path(props_path))
    rows = build_calibration_rows(
        props_df=props_df,
        train_years=train_years,
        holdout_years=holdout_years,
    )
    report = fit_calibrators(rows, out_dir=Path(model_dir), season_label=season_label)
    save_calibration_report(report, rows, docs_dir=Path(docs_dir), season_label=season_label)
    return report


def _parse_years(raw: str | None) -> list[int] | None:
    if not raw:
        return None
    return [int(part) for part in raw.split(",") if part.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Fit Step 3 prop calibration artifacts")
    parser.add_argument("--props-file", required=True, help="CSV/JSON/Parquet of closing prop lines")
    parser.add_argument("--train-years", default=None, help="Comma-separated training years")
    parser.add_argument("--holdout-years", default=None, help="Comma-separated holdout years")
    parser.add_argument("--docs-dir", default="docs")
    parser.add_argument("--model-dir", default=str(Path("models") / "calibration"))
    args = parser.parse_args()

    report = run_calibration(
        props_path=Path(args.props_file),
        train_years=_parse_years(args.train_years),
        holdout_years=_parse_years(args.holdout_years),
        docs_dir=Path(args.docs_dir),
        model_dir=Path(args.model_dir),
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
