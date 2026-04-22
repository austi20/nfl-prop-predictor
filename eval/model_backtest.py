"""Walk-forward regression backtests for the Step 2 model milestone.

Keeps evaluation intentionally simple:
- fit each model on all prior train seasons
- predict every player-week in the evaluation season
- log MAE / RMSE / bias per stat and per season
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from data.nflverse_loader import HOLDOUT_YEARS, TRAIN_YEARS, load_weekly
from models.qb import QBModel
from models.rb import RBModel
from models.wr_te import WRTEModel


@dataclass(frozen=True)
class ModelSpec:
    name: str
    model_cls: type[QBModel] | type[RBModel] | type[WRTEModel]
    positions: tuple[str, ...]
    target_stats: tuple[str, ...]


MODEL_SPECS: tuple[ModelSpec, ...] = (
    ModelSpec(
        name="qb",
        model_cls=QBModel,
        positions=("QB",),
        target_stats=("passing_yards", "passing_tds", "interceptions", "completions"),
    ),
    ModelSpec(
        name="rb",
        model_cls=RBModel,
        positions=("RB",),
        target_stats=("rushing_yards", "carries", "rushing_tds"),
    ),
    ModelSpec(
        name="wr_te",
        model_cls=WRTEModel,
        positions=("WR", "TE"),
        target_stats=("receptions", "receiving_yards", "receiving_tds"),
    ),
)


def _default_eval_years(train_years: list[int]) -> list[int]:
    if len(train_years) < 2:
        raise ValueError("walk-forward backtests need at least two training seasons")
    return train_years[1:]


def _opponent_team(row: pd.Series) -> str:
    for col in ("opponent_team", "opponent", "opp_team"):
        value = row.get(col)
        if isinstance(value, str) and value:
            return value
    return ""


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    if len(actual) == 0:
        return {"n": 0.0, "mae": 0.0, "rmse": 0.0, "bias": 0.0}

    err = predicted - actual
    return {
        "n": float(len(actual)),
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err ** 2))),
        "bias": float(np.mean(err)),
    }


def _load_existing_report(path: Path) -> dict[str, Any] | None:
    path = Path(path)
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict) or "reports" not in payload:
        return None
    return payload


def compare_report_revisions(
    previous_report: dict[str, Any],
    current_report: dict[str, Any],
    *,
    previous_label: str = "previous",
    current_label: str = "current",
    report_name: str = "walk_forward",
) -> dict[str, Any]:
    comparison: dict[str, Any] = {
        "report_name": report_name,
        "previous_label": previous_label,
        "current_label": current_label,
        "models": {},
    }

    for model_name, current_model_report in current_report.get("reports", {}).items():
        previous_model_report = previous_report.get("reports", {}).get(model_name, {})
        stat_comparison: dict[str, Any] = {}

        for stat_name, current_stat_report in current_model_report.get("per_stat", {}).items():
            previous_stat_report = (
                previous_model_report.get("per_stat", {}).get(stat_name, {}).get("overall")
            )
            current_overall = current_stat_report.get("overall", {})
            if not previous_stat_report:
                continue

            prev_bias = float(previous_stat_report.get("bias", 0.0))
            curr_bias = float(current_overall.get("bias", 0.0))
            stat_comparison[stat_name] = {
                "previous": {
                    "n": float(previous_stat_report.get("n", 0.0)),
                    "mae": float(previous_stat_report.get("mae", 0.0)),
                    "rmse": float(previous_stat_report.get("rmse", 0.0)),
                    "bias": prev_bias,
                },
                "current": {
                    "n": float(current_overall.get("n", 0.0)),
                    "mae": float(current_overall.get("mae", 0.0)),
                    "rmse": float(current_overall.get("rmse", 0.0)),
                    "bias": curr_bias,
                },
                "delta": {
                    "mae": float(current_overall.get("mae", 0.0) - previous_stat_report.get("mae", 0.0)),
                    "rmse": float(current_overall.get("rmse", 0.0) - previous_stat_report.get("rmse", 0.0)),
                    "bias": float(curr_bias - prev_bias),
                    "abs_bias": float(abs(curr_bias) - abs(prev_bias)),
                },
            }

        comparison["models"][model_name] = stat_comparison

    return comparison


def _predict_for_eval_rows(
    spec: ModelSpec,
    fit_years: list[int],
    eval_rows: pd.DataFrame,
) -> pd.DataFrame:
    if eval_rows.empty:
        return pd.DataFrame()

    model = spec.model_cls()
    model.fit(fit_years, weekly=eval_rows)

    prediction_rows: list[dict[str, Any]] = []
    for _, row in eval_rows.iterrows():
        preds = model.predict(
            player_id=str(row["player_id"]),
            week=int(row["week"]),
            season=int(row["season"]),
            opp_team=_opponent_team(row),
        )
        record: dict[str, Any] = {
            "season": int(row["season"]),
            "week": int(row["week"]),
            "player_id": str(row["player_id"]),
        }
        for stat in spec.target_stats:
            record[f"actual_{stat}"] = float(row.get(stat, np.nan))
            record[f"pred_{stat}"] = float(preds[stat].mean)
        prediction_rows.append(record)

    return pd.DataFrame(prediction_rows)


def _build_stat_report(
    predictions: pd.DataFrame,
    target_stats: tuple[str, ...],
    seasons: list[int],
) -> dict[str, Any]:
    per_stat: dict[str, Any] = {}
    for stat in target_stats:
        stat_rows = predictions[["season", f"actual_{stat}", f"pred_{stat}"]].dropna()
        overall = _metrics(
            stat_rows[f"actual_{stat}"].to_numpy(dtype=float),
            stat_rows[f"pred_{stat}"].to_numpy(dtype=float),
        )

        by_season: list[dict[str, Any]] = []
        for season in seasons:
            season_rows = stat_rows[stat_rows["season"] == season]
            season_metrics = _metrics(
                season_rows[f"actual_{stat}"].to_numpy(dtype=float),
                season_rows[f"pred_{stat}"].to_numpy(dtype=float),
            )
            by_season.append({"season": season, **season_metrics})

        per_stat[stat] = {
            "overall": overall,
            "by_season": by_season,
        }
    return per_stat


def walk_forward_backtest(
    spec: ModelSpec,
    train_years: list[int] | None = None,
    eval_years: list[int] | None = None,
    weekly: pd.DataFrame | None = None,
) -> dict[str, Any]:
    train_years = list(TRAIN_YEARS if train_years is None else train_years)
    eval_years = list(_default_eval_years(train_years) if eval_years is None else eval_years)

    if weekly is None:
        weekly = load_weekly(sorted(set(train_years)))

    weekly = weekly.copy()
    if "position" not in weekly.columns:
        raise ValueError("weekly data must include a 'position' column")

    position_rows = weekly[weekly["position"].isin(spec.positions)].copy()
    position_rows = position_rows.sort_values(["season", "week", "player_id"])

    prediction_frames: list[pd.DataFrame] = []
    seasons_run: list[int] = []

    for season in eval_years:
        history_years = [year for year in train_years if year < season]
        if not history_years:
            continue

        train_df = position_rows[position_rows["season"].isin(history_years)].copy()
        eval_df = position_rows[position_rows["season"] == season].copy()
        if train_df.empty or eval_df.empty:
            continue

        fit_and_eval = pd.concat([train_df, eval_df], ignore_index=True)
        predictions = _predict_for_eval_rows(spec, history_years, fit_and_eval)
        seasons_run.append(season)
        prediction_frames.append(predictions[predictions["season"] == season].copy())

    predictions = (
        pd.concat(prediction_frames, ignore_index=True)
        if prediction_frames
        else pd.DataFrame(columns=["season", "week", "player_id"])
    )

    return {
        "model": spec.name,
        "positions": list(spec.positions),
        "train_years": train_years,
        "eval_years": seasons_run,
        "per_stat": _build_stat_report(predictions, spec.target_stats, seasons_run),
    }


def run_all_walk_forward(
    train_years: list[int] | None = None,
    eval_years: list[int] | None = None,
    weekly: pd.DataFrame | None = None,
) -> dict[str, Any]:
    train_years = list(TRAIN_YEARS if train_years is None else train_years)
    if weekly is None:
        weekly = load_weekly(sorted(set(train_years)))

    reports = {
        spec.name: walk_forward_backtest(
            spec=spec,
            train_years=train_years,
            eval_years=eval_years,
            weekly=weekly,
        )
        for spec in MODEL_SPECS
    }
    return {
        "train_years": train_years,
        "eval_years": reports["qb"]["eval_years"] if reports else [],
        "reports": reports,
    }


def run_holdout_evaluation(
    train_years: list[int] | None = None,
    holdout_years: list[int] | None = None,
    weekly: pd.DataFrame | None = None,
) -> dict[str, Any]:
    train_years = list(TRAIN_YEARS if train_years is None else train_years)
    holdout_years = list(HOLDOUT_YEARS if holdout_years is None else holdout_years)
    needed_years = sorted(set(train_years + holdout_years))
    if weekly is None:
        weekly = load_weekly(needed_years)

    reports: dict[str, Any] = {}
    for spec in MODEL_SPECS:
        position_rows = weekly[weekly["position"].isin(spec.positions)].copy()
        position_rows = position_rows[position_rows["season"].isin(needed_years)].copy()
        fit_and_eval = position_rows[position_rows["season"].isin(needed_years)].copy()
        predictions = _predict_for_eval_rows(spec, train_years, fit_and_eval)
        predictions = predictions[predictions["season"].isin(holdout_years)].copy()
        reports[spec.name] = {
            "model": spec.name,
            "positions": list(spec.positions),
            "train_years": train_years,
            "eval_years": holdout_years,
            "per_stat": _build_stat_report(predictions, spec.target_stats, holdout_years),
        }

    return {
        "train_years": train_years,
        "eval_years": holdout_years,
        "reports": reports,
    }


def save_walk_forward_reports(report: dict[str, Any], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def render_walk_forward_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "# Walk-Forward CV Metrics",
        "",
        f"Train years: {', '.join(str(year) for year in report['train_years'])}",
        f"Eval years: {', '.join(str(year) for year in report['eval_years'])}",
        "",
    ]

    for model_name, model_report in report["reports"].items():
        lines.append(f"## {model_name.upper()}")
        lines.append("")
        for stat_name, stat_report in model_report["per_stat"].items():
            overall = stat_report["overall"]
            lines.append(
                f"- `{stat_name}`: n={int(overall['n'])}, "
                f"MAE={overall['mae']:.3f}, RMSE={overall['rmse']:.3f}, "
                f"bias={overall['bias']:.3f}"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def save_walk_forward_markdown(report: dict[str, Any], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_walk_forward_markdown(report), encoding="utf-8")


def render_revision_comparison_markdown(comparison: dict[str, Any]) -> str:
    lines: list[str] = [
        "# Model Revision Comparison",
        "",
        f"Report: `{comparison['report_name']}`",
        f"Previous label: `{comparison['previous_label']}`",
        f"Current label: `{comparison['current_label']}`",
        "",
        "Negative delta values for MAE/RMSE mean the current revision improved.",
        "",
    ]

    for model_name, model_comparison in comparison.get("models", {}).items():
        lines.append(f"## {model_name.upper()}")
        lines.append("")
        for stat_name, stat_comparison in model_comparison.items():
            previous = stat_comparison["previous"]
            current = stat_comparison["current"]
            delta = stat_comparison["delta"]
            lines.append(
                f"- `{stat_name}`: "
                f"MAE {previous['mae']:.3f} -> {current['mae']:.3f} "
                f"(delta {delta['mae']:+.3f}), "
                f"RMSE {previous['rmse']:.3f} -> {current['rmse']:.3f} "
                f"(delta {delta['rmse']:+.3f}), "
                f"|bias| delta {delta['abs_bias']:+.3f}"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def save_revision_comparison(
    comparison: dict[str, Any],
    json_path: Path,
    md_path: Path,
) -> None:
    json_path = Path(json_path)
    md_path = Path(md_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    md_path.write_text(render_revision_comparison_markdown(comparison), encoding="utf-8")


def render_holdout_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "# Holdout Metrics",
        "",
        f"Train years: {', '.join(str(year) for year in report['train_years'])}",
        f"Holdout years: {', '.join(str(year) for year in report['eval_years'])}",
        "",
    ]

    for model_name, model_report in report["reports"].items():
        lines.append(f"## {model_name.upper()}")
        lines.append("")
        for stat_name, stat_report in model_report["per_stat"].items():
            overall = stat_report["overall"]
            lines.append(
                f"- `{stat_name}`: n={int(overall['n'])}, "
                f"MAE={overall['mae']:.3f}, RMSE={overall['rmse']:.3f}, "
                f"bias={overall['bias']:.3f}"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def save_holdout_reports(report: dict[str, Any], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def save_holdout_markdown(report: dict[str, Any], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_holdout_markdown(report), encoding="utf-8")


def save_blocked_report(title: str, reason: str, json_path: Path, md_path: Path) -> None:
    payload = {
        "status": "blocked",
        "title": title,
        "reason": reason,
    }
    json_path = Path(json_path)
    md_path = Path(md_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(f"# {title}\n\nBlocked: {reason}\n", encoding="utf-8")


def main() -> None:
    walk_forward_path = Path("docs") / "walk_forward_metrics.json"
    holdout_path = Path("docs") / "holdout_metrics.json"
    previous_walk_forward = _load_existing_report(walk_forward_path)
    previous_holdout = _load_existing_report(holdout_path)

    walk_forward_report = run_all_walk_forward()
    save_walk_forward_reports(walk_forward_report, walk_forward_path)
    save_walk_forward_markdown(walk_forward_report, Path("docs") / "walk_forward_metrics.md")

    if previous_walk_forward is not None:
        comparison = compare_report_revisions(
            previous_walk_forward,
            walk_forward_report,
            previous_label="previous_saved",
            current_label="current_run",
            report_name="walk_forward",
        )
        save_revision_comparison(
            comparison,
            json_path=Path("docs") / "model_revision_comparison.json",
            md_path=Path("docs") / "model_revision_comparison.md",
        )

    try:
        holdout_report = run_holdout_evaluation()
    except Exception as exc:
        save_blocked_report(
            title="Holdout Metrics",
            reason=str(exc),
            json_path=Path("docs") / "holdout_metrics.json",
            md_path=Path("docs") / "holdout_metrics.md",
        )
    else:
        save_holdout_reports(holdout_report, holdout_path)
        save_holdout_markdown(holdout_report, Path("docs") / "holdout_metrics.md")
        if previous_holdout is not None:
            comparison = compare_report_revisions(
                previous_holdout,
                holdout_report,
                previous_label="previous_saved",
                current_label="current_run",
                report_name="holdout",
            )
            save_revision_comparison(
                comparison,
                json_path=Path("docs") / "holdout_revision_comparison.json",
                md_path=Path("docs") / "holdout_revision_comparison.md",
            )


if __name__ == "__main__":
    main()
