from __future__ import annotations

import json

import pandas as pd

from eval.model_backtest import (
    MODEL_SPECS,
    compare_report_revisions,
    render_holdout_markdown,
    render_revision_comparison_markdown,
    render_walk_forward_markdown,
    run_holdout_evaluation,
    run_all_walk_forward,
    save_blocked_report,
    save_holdout_markdown,
    save_holdout_reports,
    save_revision_comparison,
    save_walk_forward_markdown,
    save_walk_forward_reports,
    walk_forward_backtest,
)


def _make_fake_weekly() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    seasons = [2022, 2023, 2024]
    weeks = [1, 2, 3, 4]

    for season in seasons:
        for week in weeks:
            rows.append({
                "player_id": "qb1",
                "player_name": "QB One",
                "position": "QB",
                "season": season,
                "week": week,
                "recent_team": "KC",
                "opponent_team": "LAC",
                "passing_yards": 220.0 + season - 2022 + week * 8,
                "passing_tds": float(1 + (week % 2)),
                "interceptions": float(week % 2),
                "completions": 20.0 + week,
                "attempts": 30.0 + week,
                "sacks": float(week % 3),
                "air_yards_completed": 140.0 + week * 5,
                "is_home": float(week % 2),
            })
            rows.append({
                "player_id": "rb1",
                "player_name": "RB One",
                "position": "RB",
                "season": season,
                "week": week,
                "recent_team": "KC",
                "opponent_team": "LAC",
                "rushing_yards": 60.0 + season - 2022 + week * 6,
                "carries": 12.0 + week,
                "rushing_tds": float(week % 2),
                "is_home": float((week + 1) % 2),
            })
            rows.append({
                "player_id": "wr1",
                "player_name": "WR One",
                "position": "WR",
                "season": season,
                "week": week,
                "recent_team": "KC",
                "opponent_team": "LAC",
                "receptions": 4.0 + week,
                "receiving_yards": 55.0 + season - 2022 + week * 7,
                "receiving_tds": float(week % 2),
                "targets": 6.0 + week,
                "is_home": float(week % 2),
            })
            rows.append({
                "player_id": "te1",
                "player_name": "TE One",
                "position": "TE",
                "season": season,
                "week": week,
                "recent_team": "KC",
                "opponent_team": "LAC",
                "receptions": 3.0 + week,
                "receiving_yards": 40.0 + season - 2022 + week * 5,
                "receiving_tds": float((week + 1) % 2),
                "targets": 5.0 + week,
                "is_home": float((week + 1) % 2),
            })

    return pd.DataFrame(rows)


def test_walk_forward_backtest_returns_metrics():
    weekly = _make_fake_weekly()
    qb_spec = next(spec for spec in MODEL_SPECS if spec.name == "qb")

    report = walk_forward_backtest(
        spec=qb_spec,
        train_years=[2022, 2023, 2024],
        eval_years=[2023, 2024],
        weekly=weekly,
    )

    assert report["model"] == "qb"
    assert report["eval_years"] == [2023, 2024]
    assert report["per_stat"]["passing_yards"]["overall"]["n"] > 0
    assert len(report["per_stat"]["passing_yards"]["by_season"]) == 2


def test_run_all_walk_forward_and_save_reports(tmp_path):
    weekly = _make_fake_weekly()

    report = run_all_walk_forward(
        train_years=[2022, 2023, 2024],
        eval_years=[2023, 2024],
        weekly=weekly,
    )

    json_path = tmp_path / "walk_forward_metrics.json"
    md_path = tmp_path / "walk_forward_metrics.md"

    save_walk_forward_reports(report, json_path)
    save_walk_forward_markdown(report, md_path)

    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")

    assert set(loaded["reports"]) == {"qb", "rb", "wr_te"}
    assert "# Walk-Forward CV Metrics" in markdown
    assert "## QB" in markdown


def test_render_walk_forward_markdown_contains_stats():
    weekly = _make_fake_weekly()
    report = run_all_walk_forward(
        train_years=[2022, 2023, 2024],
        eval_years=[2023, 2024],
        weekly=weekly,
    )

    markdown = render_walk_forward_markdown(report)

    assert "`passing_yards`" in markdown
    assert "`rushing_yards`" in markdown
    assert "`receiving_yards`" in markdown


def test_run_holdout_and_save_reports(tmp_path):
    weekly = _make_fake_weekly()

    report = run_holdout_evaluation(
        train_years=[2022, 2023],
        holdout_years=[2024],
        weekly=weekly,
    )

    json_path = tmp_path / "holdout_metrics.json"
    md_path = tmp_path / "holdout_metrics.md"

    save_holdout_reports(report, json_path)
    save_holdout_markdown(report, md_path)

    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")

    assert set(loaded["reports"]) == {"qb", "rb", "wr_te"}
    assert loaded["reports"]["qb"]["per_stat"]["passing_yards"]["overall"]["n"] > 0
    assert "# Holdout Metrics" in markdown


def test_render_holdout_markdown_contains_stats():
    weekly = _make_fake_weekly()
    report = run_holdout_evaluation(
        train_years=[2022, 2023],
        holdout_years=[2024],
        weekly=weekly,
    )

    markdown = render_holdout_markdown(report)

    assert "`passing_yards`" in markdown
    assert "`rushing_yards`" in markdown
    assert "`receiving_yards`" in markdown


def test_save_blocked_report(tmp_path):
    json_path = tmp_path / "blocked.json"
    md_path = tmp_path / "blocked.md"

    save_blocked_report(
        title="Holdout Metrics",
        reason="HTTP Error 404: Not Found",
        json_path=json_path,
        md_path=md_path,
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")

    assert payload["status"] == "blocked"
    assert "HTTP Error 404" in payload["reason"]
    assert "Blocked:" in markdown


def test_compare_report_revisions_and_save(tmp_path):
    previous = {
        "reports": {
            "qb": {
                "per_stat": {
                    "passing_yards": {
                        "overall": {"n": 10.0, "mae": 80.0, "rmse": 100.0, "bias": 5.0}
                    }
                }
            }
        }
    }
    current = {
        "reports": {
            "qb": {
                "per_stat": {
                    "passing_yards": {
                        "overall": {"n": 10.0, "mae": 75.0, "rmse": 96.0, "bias": 3.0}
                    }
                }
            }
        }
    }

    comparison = compare_report_revisions(
        previous,
        current,
        previous_label="baseline",
        current_label="context_upgrade",
        report_name="walk_forward",
    )

    markdown = render_revision_comparison_markdown(comparison)
    json_path = tmp_path / "comparison.json"
    md_path = tmp_path / "comparison.md"
    save_revision_comparison(comparison, json_path, md_path)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["models"]["qb"]["passing_yards"]["delta"]["mae"] == -5.0
    assert "context_upgrade" in markdown
    assert "delta -5.000" in md_path.read_text(encoding="utf-8")
