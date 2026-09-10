"""Post-sweep verification for the locked fantasy calibration.

  uv run python scripts/verify_fantasy_calibration.py

Prints, for DEFAULT vs the tuned artifact:
  - the 2025 backtest metrics (per position + aggregate)
  - the real 5000-sim 2026 Week-1 board top-6 per position (projected + boom%)
Fails (exit 1) if any position's rank correlation drops > 0.03, if MAE or |bias|
regress, or if the 2026-W1 max WR projection stays above 27.
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

warnings.simplefilter("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.fantasy_calibration import (  # noqa: E402
    default_calibration,
    evaluate,
    load_calibration,
    load_eval_cache,
)

ARTIFACT = Path("models/fantasy_calibration.json")


def _fmt(m: dict) -> str:
    pp = "\n".join(
        f"    {p}: mae={v['mae']:.2f} bias={v['bias']:+.2f} "
        f"boom_err={v['boom_calib_err']:.3f} bust_err={v['bust_calib_err']:.3f} "
        f"rank={v['rank_corr']:.3f} max_proj={v['max_proj']:.1f} "
        f"boom_rate pred/act={v['pred_boom_rate']:.2f}/{v['actual_boom_rate']:.2f}"
        for p, v in m["per_position"].items()
    )
    return (
        f"  objective={m['objective']:.3f}  mae={m['mae']:.2f}  |bias|={m['bias_abs']:.2f}  "
        f"boom_err={m['boom_calib_err']:.3f}  bust_err={m['bust_calib_err']:.3f}  "
        f"rank={m['rank_corr']:.3f}  realism={m['realism_penalty']:.2f}\n{pp}"
    )


def _board_2026_w1() -> dict:
    from api.settings import AppSettings
    from api.services import fantasy_slate_service as s

    s._SLATE_CACHE.clear()
    st = AppSettings(
        default_train_years=tuple(range(2015, 2024)),
        prewarm_fantasy_slate=False,
        fantasy_slate_workers=10,
    )
    out = s.build_fantasy_slate(st, season=2026, week=1, scoring_mode="full_ppr", limit=48)
    by = {}
    for pos in ("RB", "WR", "TE", "QB"):
        rows = [e for e in out.entries if e.position == pos][:6]
        by[pos] = [(e.player_name, round(e.projected_points, 1), round(e.boom_probability, 2)) for e in rows]
    return by


def main() -> int:
    cache = load_eval_cache()
    d_metrics = evaluate(default_calibration(), cache)
    tuned = load_calibration(str(ARTIFACT)) if ARTIFACT.exists() else default_calibration()
    t_metrics = evaluate(tuned, cache)

    print("=== 2025 backtest ===")
    print("DEFAULT\n" + _fmt(d_metrics))
    print("TUNED\n" + _fmt(t_metrics))

    print("\n=== 2026 Week-1 board (TUNED, real 5000-sim) ===")
    board = _board_2026_w1()
    for pos, rows in board.items():
        print(f"  {pos}: " + " | ".join(f"{n.split()[-1]} {p}/{b:.2f}" for n, p, b in rows))

    # gates
    fail = []
    for pos, tv in t_metrics["per_position"].items():
        dv = d_metrics["per_position"].get(pos, {})
        if dv and tv["rank_corr"] < dv["rank_corr"] - 0.03:
            fail.append(f"{pos} rank_corr {dv['rank_corr']:.3f} -> {tv['rank_corr']:.3f}")
    if t_metrics["mae"] > d_metrics["mae"] + 1e-6:
        fail.append(f"aggregate MAE regressed {d_metrics['mae']:.2f} -> {t_metrics['mae']:.2f}")
    if t_metrics["bias_abs"] > d_metrics["bias_abs"] + 1e-6:
        fail.append(f"aggregate |bias| regressed {d_metrics['bias_abs']:.2f} -> {t_metrics['bias_abs']:.2f}")
    wr_max = max((p for _, p, _ in board.get("WR", [])), default=0.0)
    if wr_max > 27.0:
        fail.append(f"2026-W1 top WR projection still {wr_max:.1f} (> 27)")

    print("\n" + ("FAIL:\n  " + "\n  ".join(fail) if fail else "PASS — all gates green"))
    print("\nmetrics JSON:\n" + json.dumps({"default": d_metrics, "tuned": t_metrics}, indent=2))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
