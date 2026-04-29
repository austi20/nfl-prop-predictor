"""Phase H4: cross-season synthesis.

Aggregates all season_<YYYY>_results.csv files for walk-forward holdouts
(2019–2025 by default), then:

1. **Primary H5 input:** For each (position, stat), choose the `config_hash`
   that **wins on the most holdout seasons** — each season's winner is the
   valid row with **lowest holdout log_loss** for that target. Ties in vote
   count break on **lower n_holdout-weighted mean log_loss** pooled across all
   loaded seasons for that (position, stat, config).

2. **Reference:** Keeps the legacy global ranking (mean + variance penalty on
   per-season average log_loss across *all* stats) for benchmarking only.

Writes:
  docs/training/per_stat_majority_config.csv
  docs/training/cross_season_summary.md
  docs/training/cross_season_reliability.png

Then one Qwen 1.7B narration pass fills {{ rollup_notes }} (120 tokens max).

Legacy global score (reference only):
  Minimize: (mean_log_loss + variance_penalty)
  where variance_penalty = 0.5 * std_log_loss

Usage:
    uv run python scripts/synthesize_training.py
    uv run python scripts/synthesize_training.py --results-dir docs/training/
    uv run python scripts/synthesize_training.py --allow-partial  # preview only
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import math
import textwrap

import pandas as pd
import requests

_RESULTS_DIR = Path("docs/training")
_LLM_DEFAULT_URL = "http://localhost:8080"
_HOLDOUT_SEASONS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]
_ROLLUP_MAX_TOKENS = 120
_VARIANCE_PENALTY_WEIGHT = 0.5
_EXPECTED_CONFIGS = 144
_EXPECTED_STATS = 10
_EXPECTED_ROWS_PER_SEASON = _EXPECTED_CONFIGS * _EXPECTED_STATS

_VALID_FLAGS = frozenset(["ok", "constant_fallback"])
_RESULT_KEY_COLS = ["config_hash", "position", "stat"]


# ── Loading ───────────────────────────────────────────────────────────────────

def _validate_season_frame(
    df: pd.DataFrame,
    *,
    path: Path,
    expected_rows: int,
    allow_partial: bool,
) -> bool:
    missing_cols = [c for c in _RESULT_KEY_COLS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"{path.name} missing required columns: {missing_cols}")

    dupes = df[df.duplicated(_RESULT_KEY_COLS, keep=False)]
    if not dupes.empty:
        sample = dupes[_RESULT_KEY_COLS].head(3).to_dict("records")
        raise ValueError(f"{path.name} has duplicate result keys: {sample}")

    if len(df) != expected_rows:
        msg = (
            f"{path.name} is incomplete: {len(df)} rows found, "
            f"expected {expected_rows} ({_EXPECTED_CONFIGS} configs x {_EXPECTED_STATS} stats). "
            "Wait for train_loop.py to finish before final H4 synthesis."
        )
        if allow_partial:
            print(f"  Warning: {msg} Skipping this preview input.")
            return False
        raise ValueError(msg)

    config_count = df["config_hash"].nunique()
    stat_count = df[["position", "stat"]].drop_duplicates().shape[0]
    if config_count != _EXPECTED_CONFIGS or stat_count != _EXPECTED_STATS:
        raise ValueError(
            f"{path.name} has an unexpected grid shape: "
            f"{config_count} configs x {stat_count} stats; "
            f"expected {_EXPECTED_CONFIGS} x {_EXPECTED_STATS}."
        )

    return True


def load_all_seasons(
    results_dir: Path,
    *,
    allow_partial: bool = False,
    expected_rows: int = _EXPECTED_ROWS_PER_SEASON,
) -> pd.DataFrame:
    frames = []
    missing = []
    skipped = []
    for season in _HOLDOUT_SEASONS:
        path = results_dir / f"season_{season}_results.csv"
        if not path.exists():
            missing.append(season)
            continue
        df = pd.read_csv(path)
        if not _validate_season_frame(
            df,
            path=path,
            expected_rows=expected_rows,
            allow_partial=allow_partial,
        ):
            skipped.append(season)
            continue
        frames.append(df)
    if missing:
        print(
            f"  Warning: missing results for seasons {missing}; "
            "majority voting uses available seasons only."
        )
    if skipped:
        print(
            f"  Warning: skipped incomplete seasons {skipped}; "
            "preview majority voting uses complete seasons only."
        )
    if not frames:
        raise FileNotFoundError(
            f"No complete season_YYYY_results.csv found in {results_dir}. "
            "Run scripts/train_loop.py to completion first."
        )
    return pd.concat(frames, ignore_index=True)


def _valid_mask(df: pd.DataFrame) -> pd.Series:
    return df["log_loss"].notna() & df["convergence_flag"].isin(_VALID_FLAGS)


def _weighted_log_loss(df: pd.DataFrame, group_cols: list[str], out_col: str) -> pd.DataFrame:
    work = df.copy()
    if "n_holdout" in work.columns:
        weights = pd.to_numeric(work["n_holdout"], errors="coerce")
    else:
        weights = pd.Series(1.0, index=work.index)
    work["_weight"] = weights.fillna(1.0).clip(lower=1.0)
    work["_weighted_log_loss"] = pd.to_numeric(work["log_loss"], errors="coerce") * work["_weight"]

    agg = (
        work.groupby(group_cols, sort=True)
        .agg(_weighted_loss_sum=("_weighted_log_loss", "sum"), _weight_sum=("_weight", "sum"))
        .reset_index()
    )
    agg[out_col] = agg["_weighted_loss_sum"] / agg["_weight_sum"]
    return agg.drop(columns=["_weighted_loss_sum", "_weight_sum"])


# ── Per-season stat winners + majority vote ──────────────────────────────────

def per_season_stat_winners(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (holdout_season, position, stat): argmin log_loss among valid fits."""
    valid = df[_valid_mask(df)].copy()
    if valid.empty:
        return pd.DataFrame()
    idx = valid.groupby(["holdout_season", "position", "stat"], sort=True)["log_loss"].idxmin()
    return valid.loc[idx].reset_index(drop=True)


def majority_config_per_stat(df: pd.DataFrame) -> pd.DataFrame:
    """For each (position, stat), config with most yearly wins; tie-break on weighted log_loss."""
    valid = df[_valid_mask(df)].copy()
    winners = per_season_stat_winners(df)
    if winners.empty or valid.empty:
        return pd.DataFrame()

    perf = _weighted_log_loss(
        valid,
        ["position", "stat", "config_hash"],
        "mean_log_loss_pooled",
    )

    vote_groups = (
        winners.groupby(["position", "stat", "config_hash"], sort=True)
        .agg(
            vote_count=("holdout_season", "count"),
            seasons=("holdout_season", lambda s: ",".join(str(int(x)) for x in sorted(s.unique()))),
        )
        .reset_index()
    )
    vote_groups = vote_groups.merge(perf, on=["position", "stat", "config_hash"])

    vote_groups = vote_groups.sort_values(
        ["position", "stat", "vote_count", "mean_log_loss_pooled"],
        ascending=[True, True, False, True],
    )
    picks = vote_groups.groupby(["position", "stat"], sort=True).head(1).reset_index(drop=True)

    cfg_cols = [
        "config_hash",
        "dist_family",
        "k",
        "l1_alpha",
        "use_weather",
        "use_opponent_epa",
        "use_rest_days",
        "use_home_away",
    ]
    cfg_lookup = df[cfg_cols].drop_duplicates("config_hash").set_index("config_hash")
    for col in cfg_cols[1:]:
        picks[col] = picks["config_hash"].map(cfg_lookup[col])

    n_seasons = df["holdout_season"].nunique()
    picks.rename(columns={"seasons": "winning_seasons"}, inplace=True)
    picks["holdout_seasons_available"] = n_seasons
    return picks.sort_values(["position", "stat"]).reset_index(drop=True)


# ── Legacy global ranking (reference only) ───────────────────────────────────

def select_pareto_config(df: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    """Return (best_config_hash, summary_df) using mean+variance-penalized log-loss."""
    valid = df[_valid_mask(df)].copy()

    config_cols = [
        "config_hash",
        "use_weather",
        "dist_family",
        "k",
        "l1_alpha",
        "use_opponent_epa",
        "use_rest_days",
        "use_home_away",
    ]

    per_season = (
        valid.groupby(config_cols + ["holdout_season"])["log_loss"]
        .mean()
        .reset_index()
        .rename(columns={"log_loss": "season_mean_ll"})
    )

    agg = (
        per_season.groupby(config_cols)["season_mean_ll"]
        .agg(mean_ll="mean", std_ll="std")
        .reset_index()
    )
    agg["std_ll"] = agg["std_ll"].fillna(0.0)
    agg["score"] = agg["mean_ll"] + _VARIANCE_PENALTY_WEIGHT * agg["std_ll"]
    agg = agg.sort_values("score").reset_index(drop=True)

    best_hash = str(agg.iloc[0]["config_hash"])
    return best_hash, agg


# ── Pooled winners (supplementary — not H5 primary) ───────────────────────────

def _best_per_group(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    """For each group key, find the config_hash with lowest weighted log_loss."""
    valid = df[df["log_loss"].notna()].copy()
    pivot_cols = group_cols + ["config_hash"]
    agg = _weighted_log_loss(valid, pivot_cols, "mean_ll")
    idx = agg.groupby(group_cols)["mean_ll"].idxmin()
    best = agg.loc[idx].copy()
    cfg_cols = ["config_hash", "dist_family", "k", "l1_alpha", "use_weather"]
    cfg_lookup = df[cfg_cols].drop_duplicates("config_hash").set_index("config_hash")
    for col in ["dist_family", "k", "l1_alpha", "use_weather"]:
        best[col] = best["config_hash"].map(cfg_lookup[col])
    return best.reset_index(drop=True)


def dist_family_winners(df: pd.DataFrame) -> pd.DataFrame:
    """Best config per (position, stat) if you weight-pool log_loss across seasons first."""
    return _best_per_group(df, ["position", "stat"])


# ── Ablation summary ─────────────────────────────────────────────────────────

def _ablation_summary(df: pd.DataFrame) -> dict[str, str]:
    valid = df[df["log_loss"].notna()].copy()
    results: dict[str, str] = {}

    for flag in ["use_weather"]:
        on = valid[valid[flag] == True]["log_loss"].mean()
        off = valid[valid[flag] == False]["log_loss"].mean()
        if math.isfinite(on) and math.isfinite(off):
            delta = on - off
            sign = "+" if delta >= 0 else ""
            verdict = "hurts" if delta > 0.001 else ("helps" if delta < -0.001 else "neutral")
            results[flag] = f"{sign}{delta:.4f} ({verdict}; on={on:.4f}, off={off:.4f})"
        else:
            results[flag] = "N/A"

    for family in ["legacy", "count_aware", "decomposed"]:
        mean_ll = valid[valid["dist_family"] == family]["log_loss"].mean()
        results[f"dist_{family}"] = f"{mean_ll:.4f}" if math.isfinite(mean_ll) else "N/A"

    return results


# ── Reliability deviation PNG ─────────────────────────────────────────────────

def render_reliability_png(
    df: pd.DataFrame,
    majority_df: pd.DataFrame,
    out_path: Path,
) -> bool:
    """Mean max_reliability_dev across stats using each per-stat majority config, by season."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  matplotlib not available; skipping reliability PNG")
        return False

    if majority_df.empty:
        return False

    seasons = [int(s) for s in sorted(df["holdout_season"].unique())]
    means: list[float] = []
    for season in seasons:
        devs: list[float] = []
        for _, r in majority_df.iterrows():
            hit = df[
                (df["holdout_season"] == season)
                & (df["position"] == r["position"])
                & (df["stat"] == r["stat"])
                & (df["config_hash"] == r["config_hash"])
            ]
            if not hit.empty and math.isfinite(float(hit.iloc[0]["max_reliability_dev"])):
                devs.append(float(hit.iloc[0]["max_reliability_dev"]))
        means.append(sum(devs) / len(devs) if devs else float("nan"))

    fig, ax = plt.subplots(figsize=(6, 6))
    valid_means = [(s, m) for s, m in zip(seasons, means) if math.isfinite(m)]
    if valid_means:
        xs = list(range(len(valid_means)))
        ax.plot(xs, [m for _, m in valid_means], "o-", label="Mean max reliability deviation")

    for i, (season, m) in enumerate(valid_means):
        ax.annotate(
            f"{season}\nmean max_dev={m:.3f}",
            xy=(i, m),
            xytext=(5, 5),
            textcoords="offset points",
            fontsize=8,
        )

    ax.set_xticks(range(len(valid_means)) if valid_means else [])
    ax.set_xticklabels([str(s) for s, _ in valid_means] if valid_means else [])
    ax.set_ylabel("Mean max reliability deviation (across stats)")
    ax.set_xlabel("Holdout season")
    ax.set_title("Per-stat majority config - reliability deviation trend")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return True


def _df_to_markdown(df: pd.DataFrame) -> str:
    """Markdown pipe table without optional tabulate dependency."""
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
    return "\n".join(lines)


# ── Markdown rendering ────────────────────────────────────────────────────────

_MODEL_GATE_NOTE = """
## Model gates (for H5 lock-in)

**Primary:** `per_stat_majority_config.csv` — one `config_hash` per `(position, stat)` from
majority vote across walk-forward holdouts. Implement routing in model code so each stat uses
its own knobs (`k`, `l1_alpha`, `dist_family`, feature flags).

| Flag | Current default | H5 decision basis |
|------|-----------------|-------------------|
| `NFL_APP_USE_FUTURE_ROW` | `false` | Review per-stat `dist_family` in the majority table |
| `NFL_APP_USE_CALIBRATION` | unset | Enable if mean `max_reliability_dev` for locked per-stat configs is persistently high |
| `use_weather` | `false` | Take from each stat's winning row (can differ by stat) |
| `k`, `l1_alpha` | position defaults | Take **per stat** from the majority table |

The global mean-variance config in this report is **not** the production default — it is a
single-config benchmark only.
""".strip()


def render_summary_md(
    majority_df: pd.DataFrame,
    best_hash: str,
    best_row: pd.Series,
    agg: pd.DataFrame,
    ablation: dict[str, str],
    pooled_stat_winners: pd.DataFrame,
    df: pd.DataFrame,
    rollup_notes: str,
    png_written: bool,
) -> str:
    seasons_available = [int(s) for s in sorted(df["holdout_season"].unique())]
    mean_ll = float(agg.iloc[0]["mean_ll"])
    std_ll = float(agg.iloc[0]["std_ll"])
    score = float(agg.iloc[0]["score"])

    lines = [
        "# Cross-Season Training Summary (Phase H4)",
        "",
        f"**Holdout seasons loaded:** {seasons_available}",
        f"**Total distinct configs in grid:** {agg['config_hash'].nunique()}",
        "",
        "## Per-stat majority config (H5 primary)",
        "",
        "Each row is the `config_hash` that **won on the most holdout seasons** for that stat ",
        "(lowest holdout `log_loss` among valid fits per season). ",
        "Ties use lower **n_holdout-weighted pooled mean** `log_loss` across all loaded seasons for that triple.",
        "",
        "Full table: [`per_stat_majority_config.csv`](per_stat_majority_config.csv)",
        "",
    ]

    display_cols = [
        "position",
        "stat",
        "config_hash",
        "vote_count",
        "holdout_seasons_available",
        "winning_seasons",
        "mean_log_loss_pooled",
        "k",
        "l1_alpha",
        "dist_family",
        "use_weather",
    ]
    sub = majority_df[[c for c in display_cols if c in majority_df.columns]]
    lines.append(_df_to_markdown(sub))
    lines.extend(["", ""])

    lines += [
        "## Reference: global mean-variance config (single-config benchmark)",
        "",
        "Same ranking as before Phase H4 — **not** the recommended production default when using per-stat configs.",
        "",
        f"| Knob | Value |",
        f"|------|-------|",
        f"| config_hash | `{best_hash}` |",
        f"| use_weather | {bool(best_row['use_weather'])} |",
        f"| dist_family | {best_row['dist_family']} |",
        f"| k | {int(best_row['k'])} |",
        f"| l1_alpha | {float(best_row['l1_alpha'])} |",
        "",
        f"**Mean holdout log-loss:** {mean_ll:.4f}",
        f"**Std across seasons:** {std_ll:.4f}",
        f"**Selection score (mean + {_VARIANCE_PENALTY_WEIGHT}×std):** {score:.4f}",
        "",
        "## Top 10 global benchmark configs by score",
        "",
        agg.head(10).pipe(_df_to_markdown),
        "",
        "## Ablation findings",
        "",
        f"- Weather on vs off: {ablation.get('use_weather', 'N/A')}",
        f"- Dist family log-loss: legacy={ablation.get('dist_legacy', 'N/A')}, "
        f"count_aware={ablation.get('dist_count_aware', 'N/A')}, "
        f"decomposed={ablation.get('dist_decomposed', 'N/A')}",
        f"- Opponent EPA / rest days / home-away: deferred to H2.1",
        "",
        "## Pooled-across-seasons argmin per (position, stat) (secondary reference)",
        "",
        "If you first pool `log_loss` across all seasons with `n_holdout` weights and then pick a single winner, you get ",
        "(possibly different) configs — useful for comparison, not the H5 majority vote.",
        "",
        pooled_stat_winners[
            ["position", "stat", "dist_family", "k", "l1_alpha", "use_weather", "mean_ll"]
        ].pipe(_df_to_markdown),
        "",
    ]

    if png_written:
        lines += [
            "## Reliability deviation trend",
            "",
            "![Reliability deviation trend](cross_season_reliability.png)",
            "",
        ]

    lines += [
        _MODEL_GATE_NOTE,
        "",
        "## Rollup observations",
        "",
        rollup_notes,
    ]

    return "\n".join(lines) + "\n"


# ── Qwen rollup narration ─────────────────────────────────────────────────────

def fill_rollup_notes(summary_stub: str, llm_url: str) -> str:
    prompt = textwrap.dedent(f"""
        You are a concise NFL analytics assistant. Below is a cross-season training summary
        with all statistics already filled in. Write 3-4 sentences for the "Rollup observations"
        section. Focus on what held up year-over-year, which configs won the most often per stat,
        and any season-specific anomalies visible in the data. Be specific to the
        numbers. Do not repeat numbers verbatim.

        Summary:
        {summary_stub[:3000]}

        Write only the 3-4 sentence rollup below:
    """).strip()

    try:
        resp = requests.post(
            f"{llm_url}/v1/completions",
            json={
                "prompt": prompt,
                "max_tokens": _ROLLUP_MAX_TOKENS,
                "temperature": 0.3,
                "stop": ["\n\n", "##"],
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["text"].strip()
    except Exception as exc:
        return f"(LLM unavailable: {exc})"


# ── Entry point ───────────────────────────────────────────────────────────────

def synthesize(results_dir: Path, llm_url: str, *, allow_partial: bool = False) -> None:
    print("Loading all season results ...")
    df = load_all_seasons(results_dir, allow_partial=allow_partial)
    print(f"  Loaded {len(df)} rows across {df['holdout_season'].nunique()} seasons")

    print("Selecting per-stat majority configs ...")
    majority_df = majority_config_per_stat(df)
    if majority_df.empty:
        print("  Warning: no majority table produced (check valid results).")
    else:
        csv_path = results_dir / "per_stat_majority_config.csv"
        majority_df.to_csv(csv_path, index=False)
        print(f"  Written: {csv_path} ({len(majority_df)} stats)")

    print("Computing reference global ranking ...")
    best_hash, agg = select_pareto_config(df)
    best_row = agg.iloc[0]
    print(f"  Benchmark config: {best_hash}  (score={float(best_row['score']):.4f})")

    ablation = _ablation_summary(df)
    pooled_stat_winners = dist_family_winners(df)

    png_path = results_dir / "cross_season_reliability.png"
    png_written = render_reliability_png(df, majority_df, png_path)

    stub_context = render_summary_md(
        majority_df=majority_df,
        best_hash=best_hash,
        best_row=best_row,
        agg=agg,
        ablation=ablation,
        pooled_stat_winners=pooled_stat_winners,
        df=df,
        rollup_notes="{{ rollup_notes }}",
        png_written=png_written,
    )

    print("Requesting Qwen rollup narration ...")
    rollup = fill_rollup_notes(stub_context, llm_url)

    final_md = stub_context.replace("{{ rollup_notes }}", rollup)
    out_path = results_dir / "cross_season_summary.md"
    out_path.write_text(final_md, encoding="utf-8")
    print(f"  Written: {out_path}")

    if png_written:
        print(f"  Written: {png_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase H4: cross-season synthesis")
    parser.add_argument("--results-dir", default=str(_RESULTS_DIR))
    parser.add_argument("--llm-url", default=_LLM_DEFAULT_URL)
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Preview only: skip incomplete present season CSVs instead of failing.",
    )
    args = parser.parse_args()
    synthesize(Path(args.results_dir), args.llm_url, allow_partial=args.allow_partial)


if __name__ == "__main__":
    main()
