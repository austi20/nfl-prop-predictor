"""Drive the paper-execution stack end to end (dry run).

Loads a ``paper_trade_picks_<label>.csv`` (produced by ``eval/replay_pipeline``)
or any NormalizedPick-shaped CSV, POSTs the picks to
``/api/execution/paper/submit`` on a TestClient-wrapped app, then writes the
resulting portfolio snapshot + order-event stream to ``docs/``.

This is the only end-to-end exercise of ExecutionService -> mapper -> risk
engine -> paper adapter -> ledger; the committed test suite only unit-tests
those pieces in isolation.

Usage:
  uv run python scripts/dry_run_execution.py --picks docs/paper_trade_picks_2025.csv --label 2025
  uv run python scripts/dry_run_execution.py --picks docs/paper_trade_picks_2025.csv --label 2025 --fake-adapter
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

_REQUIRED = [
    "player_id", "season", "week", "stat", "line", "selected_side", "selected_odds",
    "selected_book_implied_prob", "selected_fair_american", "selected_raw_prob",
    "selected_prob", "selected_edge",
]


def _row_to_pick(row: dict) -> dict:
    """Map a replay pick row (or NormalizedPick CSV row) to a NormalizedPick dict."""
    pick = {
        "player_id": str(row["player_id"]),
        "season": int(row["season"]),
        "week": int(row["week"]),
        "stat": str(row["stat"]),
        "line": float(row["line"]),
        "selected_side": str(row["selected_side"]),
        "selected_odds": int(row["selected_odds"]),
        "selected_book_implied_prob": float(row["selected_book_implied_prob"]),
        "selected_fair_american": float(row["selected_fair_american"]),
        "selected_raw_prob": float(row["selected_raw_prob"]),
        "selected_prob": float(row["selected_prob"]),
        "selected_edge": float(row["selected_edge"]),
    }
    for opt in ("book", "game_id", "recent_team", "opponent_team", "player_name", "position"):
        if opt in row and pd.notna(row[opt]):
            pick[opt] = str(row[opt])
    return pick


def run(picks_path: Path, label: str, *, limit: int, fake_adapter: bool, out_dir: Path) -> dict:
    from fastapi.testclient import TestClient

    from api.server import create_app
    from api.settings import AppSettings

    df = pd.read_csv(picks_path)
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise SystemExit(f"{picks_path} missing required columns: {missing}")
    if limit > 0:
        df = df.head(limit)
    picks = [_row_to_pick(r) for r in df.to_dict("records")]

    settings = AppSettings(
        docs_dir=out_dir, use_realistic_paper=not fake_adapter, prewarm_fantasy_slate=False
    )
    client = TestClient(create_app(settings))

    submit = client.post("/api/execution/paper/submit", json={"picks": picks})
    submit.raise_for_status()
    results = submit.json()["data"]
    portfolio = client.get("/api/execution/portfolio").json()["data"]
    events = client.get("/api/execution/events").json()["data"]

    status_counts = Counter(r.get("status", "unknown") for r in results)
    reject_reasons = Counter(
        r.get("reason", "") for r in results if r.get("status") == "risk_rejected"
    )
    summary = {
        "label": label,
        "picks_source": str(picks_path),
        "adapter": "fake" if fake_adapter else "realistic_paper",
        "picks_submitted": len(picks),
        "status_counts": dict(status_counts),
        "risk_reject_reasons": dict(reject_reasons),
        "portfolio": portfolio,
        "n_events": len(events),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"dry_run_execution_{label}.json").write_text(
        json.dumps({"summary": summary, "results": results, "events": events}, indent=2),
        encoding="utf-8",
    )

    pos = portfolio.get("positions", [])
    md = [
        f"# Execution Stack Dry Run {label}",
        "",
        f"Picks source: `{picks_path}`  ",
        f"Adapter: `{summary['adapter']}` (RealisticPaperAdapter uses an unseeded RNG; fills vary run to run)  ",
        f"Picks submitted: {len(picks)}",
        "",
        "## Submit results by status",
        "",
        "| status | count |",
        "|---|---:|",
        *[f"| {k} | {v} |" for k, v in sorted(status_counts.items())],
        "",
    ]
    if reject_reasons:
        md += ["## Risk-reject reasons", "", "| reason | count |", "|---|---:|",
               *[f"| {k} | {v} |" for k, v in reject_reasons.most_common()], ""]
    md += [
        "## Portfolio after run",
        "",
        f"- Cash balance: {portfolio.get('cash_balance', 0.0):.4f}",
        f"- Realized PnL: {portfolio.get('realized_pnl', 0.0):.4f}",
        f"- Unrealized PnL: {portfolio.get('unrealized_pnl', 0.0):.4f}",
        f"- Open positions: {len(pos)}",
        f"- Order events recorded: {len(events)}",
        "",
    ]
    if pos:
        md += ["| market_id | side | size | avg_price | unrealized_pnl |", "|---|---|---:|---:|---:|"]
        for p in pos[:25]:
            md.append(
                f"| {p.get('market_id','')} | {p.get('side','')} | {p.get('size',0):.2f} "
                f"| {p.get('avg_price',0):.4f} | {p.get('unrealized_pnl',0):.4f} |"
            )
        if len(pos) > 25:
            md.append(f"| ...{len(pos) - 25} more | | | | |")
        md.append("")
    (out_dir / f"dry_run_execution_{label}.md").write_text("\n".join(md), encoding="utf-8")

    print(f"submitted {len(picks)} picks -> {dict(status_counts)}")
    print(f"portfolio: cash={portfolio.get('cash_balance', 0.0):.2f} "
          f"positions={len(pos)} events={len(events)}")
    print(f"wrote docs/dry_run_execution_{label}.md")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="End-to-end paper execution dry run")
    parser.add_argument("--picks", required=True, help="paper_trade_picks_<label>.csv or NormalizedPick CSV")
    parser.add_argument("--label", required=True, help="output label, e.g. 2025 or 2026-w1")
    parser.add_argument("--limit", type=int, default=1000, help="max picks to submit (0 = all)")
    parser.add_argument("--fake-adapter", action="store_true", help="use FakePaperAdapter (deterministic immediate fills)")
    parser.add_argument("--out-dir", default="docs")
    args = parser.parse_args()
    run(
        Path(args.picks),
        args.label,
        limit=args.limit,
        fake_adapter=args.fake_adapter,
        out_dir=Path(args.out_dir),
    )


if __name__ == "__main__":
    main()
