"""Phase H3: per-season Qwen 1.7B narration.

Loads a season_<YYYY>_results.csv produced by train_loop.py, fills all
deterministic slots in season_summary.j2, then sends the rendered scaffold
to Qwen 1.7B for a 2-3 sentence freeform observation (80 tokens max).

All statistical facts are pinned by the template before the LLM sees them;
Qwen fills only {{ qwen_freeform_notes }} and cannot alter the numbers.

Output is written to:
  docs/training/season_<YYYY>_summary.md
  E:/AI Brain/ClaudeBrain/02 Work and Career/NFLStatsPredictor/training/season_<YYYY>.md  (if brain path exists)

Usage:
    uv run python scripts/narrate_season.py --holdout 2019
    uv run python scripts/narrate_season.py --holdout 2019 --llm-url http://localhost:8080
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import json
import math
import textwrap

import pandas as pd
import requests
from jinja2 import Environment, FileSystemLoader

_TEMPLATE_DIR = Path(__file__).parent.parent / "llm" / "templates"
_RESULTS_DIR = Path("docs/training")
_BRAIN_BASE = Path("E:/AI Brain/ClaudeBrain/02 Work and Career/NFLStatsPredictor/training")
_LLM_DEFAULT_URL = "http://localhost:8080"
_FREEFORM_MAX_TOKENS = 80

_NAIVE_LOG_LOSS = 0.6931  # log(2) - baseline for a coin-flip


def load_results(holdout_season: int, results_dir: Path) -> pd.DataFrame:
    path = results_dir / f"season_{holdout_season}_results.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"Results CSV not found: {path}\n"
            "Run scripts/train_loop.py first."
        )
    return pd.read_csv(path)


def best_config(df: pd.DataFrame) -> pd.Series:
    """Row with lowest mean log_loss across all (position, stat) for this holdout."""
    valid = df[df["log_loss"].notna() & df["convergence_flag"].isin(["ok", "constant_fallback"])]
    if valid.empty:
        return df.iloc[0]
    config_cols = ["config_hash", "use_weather", "dist_family", "k", "l1_alpha"]
    agg = (
        valid.groupby(config_cols)["log_loss"]
        .mean()
        .reset_index()
        .rename(columns={"log_loss": "mean_log_loss"})
    )
    best_hash = agg.loc[agg["mean_log_loss"].idxmin(), "config_hash"]
    return df[df["config_hash"] == best_hash].iloc[0]


def _fmt_delta(val: float) -> str:
    if not math.isfinite(val):
        return "N/A"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.4f}"


def _ablation_delta(df: pd.DataFrame, flag: str, true_val, false_val) -> str:
    """Mean log-loss delta when flag=true_val vs flag=false_val."""
    valid = df[df["log_loss"].notna()]
    on = valid[valid[flag] == true_val]["log_loss"].mean()
    off = valid[valid[flag] == false_val]["log_loss"].mean()
    if not (math.isfinite(on) and math.isfinite(off)):
        return "N/A"
    delta = on - off
    return f"{_fmt_delta(delta)} (on={on:.4f}, off={off:.4f})"


def _dist_family_table(df: pd.DataFrame) -> str:
    valid = df[df["log_loss"].notna()]
    rows = []
    for family in ["legacy", "count_aware", "decomposed"]:
        mean_ll = valid[valid["dist_family"] == family]["log_loss"].mean()
        rows.append(f"  {family}: {mean_ll:.4f}" if math.isfinite(mean_ll) else f"  {family}: N/A")
    return "\n".join(rows)


def _feature_flags_str(row: pd.Series) -> str:
    flags = []
    if row.get("use_weather"):
        flags.append("weather")
    if row.get("use_opponent_epa"):
        flags.append("opp_epa")
    if row.get("use_rest_days"):
        flags.append("rest_days")
    if row.get("use_home_away"):
        flags.append("home_away")
    return ", ".join(flags) if flags else "base_only"


def _top3_features_table(df: pd.DataFrame, best_row: pd.Series) -> str:
    # AIC and coefficient access not available at summary level; report top stats by mean log-loss improvement
    best_hash = best_row["config_hash"]
    best_rows = df[df["config_hash"] == best_hash].copy()
    if best_rows.empty or best_rows["log_loss"].isna().all():
        return "  (coefficient data not available at summary level)"
    top = (
        best_rows.dropna(subset=["log_loss"])
        .sort_values("log_loss")
        .head(3)[["position", "stat", "log_loss"]]
    )
    lines = ["  pos    stat                 log_loss"]
    for _, r in top.iterrows():
        lines.append(f"  {r['position']:<6} {r['stat']:<20} {r['log_loss']:.4f}")
    return "\n".join(lines)


def build_template_context(df: pd.DataFrame, holdout_season: int) -> dict:
    best = best_config(df)
    best_hash = best["config_hash"]
    best_rows = df[df["config_hash"] == best_hash]
    mean_ll = best_rows["log_loss"].mean()
    mean_brier = best_rows["brier"].mean()
    mean_rel = best_rows["max_reliability_dev"].mean()

    return {
        "season": holdout_season - 1,
        "holdout_season": holdout_season,
        "best_k": int(best["k"]),
        "best_l1_alpha": float(best["l1_alpha"]),
        "best_dist_family": str(best["dist_family"]),
        "feature_flags": _feature_flags_str(best),
        "log_loss": f"{mean_ll:.4f}" if math.isfinite(mean_ll) else "N/A",
        "log_loss_delta": _fmt_delta(mean_ll - _NAIVE_LOG_LOSS),
        "brier": f"{mean_brier:.4f}" if math.isfinite(mean_brier) else "N/A",
        "max_reliability_dev": f"{mean_rel:.4f}" if math.isfinite(mean_rel) else "N/A",
        "top_3_features_table": _top3_features_table(df, best),
        "weather_delta": _ablation_delta(df, "use_weather", True, False),
        "opp_epa_delta": "N/A (H2.1 deferred)",
        "rest_days_delta": "N/A (H2.1 deferred)",
        "dist_family_table": _dist_family_table(df),
        "qwen_freeform_notes": "{{ qwen_freeform_notes }}",
    }


def render_scaffold(context: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        keep_trailing_newline=True,
    )
    template = env.get_template("season_summary.j2")
    return template.render(**context)


def fill_freeform(scaffold: str, llm_url: str) -> str:
    """Send scaffold to Qwen and splice in the freeform notes (80 tokens max)."""
    prompt = textwrap.dedent(f"""
        You are a concise NFL analytics assistant. Below is a structured training season report
        with all statistics already filled in. Write 2-3 sentences for the
        "Qualitative observations" section only. Focus on what the numbers suggest about
        model behavior. Be specific to the numbers shown. Do not repeat the numbers verbatim.

        Report:
        {scaffold}

        Write only the 2-3 sentence observation below:
    """).strip()

    try:
        resp = requests.post(
            f"{llm_url}/v1/completions",
            json={
                "prompt": prompt,
                "max_tokens": _FREEFORM_MAX_TOKENS,
                "temperature": 0.3,
                "stop": ["\n\n", "##"],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        freeform = data["choices"][0]["text"].strip()
    except Exception as exc:
        freeform = f"(LLM unavailable: {exc})"

    return scaffold.replace("{{ qwen_freeform_notes }}", freeform)


def write_outputs(content: str, holdout_season: int, results_dir: Path) -> list[Path]:
    written = []

    out_path = results_dir / f"season_{holdout_season}_summary.md"
    out_path.write_text(content, encoding="utf-8")
    written.append(out_path)

    brain_path = _BRAIN_BASE / f"season_{holdout_season}.md"
    if brain_path.parent.exists():
        brain_path.write_text(content, encoding="utf-8")
        written.append(brain_path)

    return written


def narrate(holdout_season: int, llm_url: str, results_dir: Path) -> None:
    df = load_results(holdout_season, results_dir)
    context = build_template_context(df, holdout_season)
    scaffold = render_scaffold(context)
    final = fill_freeform(scaffold, llm_url)
    paths = write_outputs(final, holdout_season, results_dir)
    for p in paths:
        print(f"  Written: {p}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase H3: per-season Qwen narration")
    parser.add_argument("--holdout", type=int, required=True, help="Holdout season (2019-2025)")
    parser.add_argument("--llm-url", default=_LLM_DEFAULT_URL, help="llama.cpp server URL")
    parser.add_argument("--results-dir", default=str(_RESULTS_DIR))
    args = parser.parse_args()

    narrate(
        holdout_season=args.holdout,
        llm_url=args.llm_url,
        results_dir=Path(args.results_dir),
    )


if __name__ == "__main__":
    main()
