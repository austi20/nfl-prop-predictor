# H2 train_loop.py — Design Spec

**Date:** 2026-04-28
**Phase:** H2 (walk-forward ablation grid)
**Status:** Approved by user 2026-04-28
**Implementer notes:** Session C, switch to Sonnet 4.6 after spec is approved.

---

## Context

Phase H2 builds the walk-forward training harness for the ablation grid defined in `plan.md` (root). H1, H1.5, H4.5, and H2.5 already shipped. The grid itself, the model classes, and the synthetic training dataset are all built. This spec resolves the remaining open design questions: walk-forward layout, results CSV schema, checkpoint format, and parallelism strategy.

This is a deterministic harness — no LLM in the loop. Qwen 1.7B narration is H3, not H2.

---

## Prerequisites (already satisfied)

- `models/{qb,rb,wr_te}.py` accept `use_weather`, `l1_alpha`, `dist_family` in `fit()` (H1, H1.5)
- `models/dist_family.py` provides count-aware, quantile, and decomposed dist families (H1.5)
- `eval/calibration_fit.py::assert_four_window_disjoint()` enforces window discipline (H4.5)
- `models/{qb,rb,wr_te}.py::_residual_stds` cached at fit time (H2.5)
- `docs/training/synthetic_props_training.csv` covers seasons 2019–2025 (regenerated 2026-04-28); 144,414 rows total

---

## 1. Walk-forward layout

**6 expanding-window steps. Not 7.**

| Step | Train seasons | Holdout season |
|---|---|---|
| 1 | 2018 | 2019 |
| 2 | 2018–2019 | 2020 |
| 3 | 2018–2020 | 2021 |
| 4 | 2018–2021 | 2022 |
| 5 | 2018–2022 | 2023 |
| 6 | 2018–2023 | 2024 |

**Plan.md inconsistency:** The current plan.md says "7 walk-forward steps" but the four-window discipline (H4.5) reserves 2025 for `final_eval`. A 7th step would test on 2025, violating the reservation. At H2 lock-in, update plan.md verification line from "4 of 7 walk-forward steps" to "4 of 6 walk-forward steps."

**Rolling vs expanding:** Expanding chosen. More training data each step, simpler, standard for time-series walk-forward CV.

---

## 2. Holdout evaluation contract

**Source of truth:** `docs/training/synthetic_props_training.csv` (loaded via `eval.training_dataset.load_synthetic_training_props()`).

**Per (config, holdout_season, position, stat):**
1. Fit position model on training years with the config flags
2. For each row in synthetic CSV matching `season == holdout_season` and the model's `target_stats`, predict StatDistribution and compute `prob_over = dist.prob_over(line)`
3. Log-loss is `prob_over` vs `outcome_over` (binary label from CSV)

**Selection metric:** log-loss. H4's Pareto ranking aggregates across 6 holdout seasons (mean + variance penalty per plan.md).

---

## 3. Ablation grid

Per plan.md H2 section. 1152 configs:
- `use_weather ∈ {True, False}`
- `use_opponent_epa ∈ {True, False}` *(opponent defensive EPA from nflverse)*
- `use_rest_days ∈ {True, False}`
- `use_home_away ∈ {True, False}`
- `dist_family ∈ {legacy, count_aware, decomposed}`
- `k ∈ {2, 4, 6, 8, 12, 16}` *(shrinkage constant)*
- `l1_alpha ∈ {0.0, 0.001, 0.01, 0.1}` *(L1 via `GLM.fit_regularized(L1_wt=1.0, refit=True)` when nonzero)*

`2^4 × 3 × 6 × 4 = 1152` configs × 6 holdout steps = 6,912 (config, step) pairs. Each pair fits 10 GLMs (4 QB stats + 3 RB stats + 3 WR/TE stats) ⇒ ~69K total GLM fits.

**Estimated wall time:** ~2 hours sequential on a single CPU core.

---

## 4. Results CSV schema

**File:** `docs/training/season_<YYYY>_results.csv`, one per holdout season.

**One row per (config, position, stat).** ~11,520 rows per season-CSV.

**Columns (22 total):**

```
# Identifiers (4)
config_hash         str    # md5 hex of frozen 7-knob config
holdout_season      int
position            str    # qb / rb / wr_te
stat                str    # passing_yards, rushing_yards, etc.

# Config flat (7)
use_weather         bool
use_opponent_epa    bool
use_rest_days       bool
use_home_away       bool
dist_family         str    # legacy / count_aware / decomposed
k                   int
l1_alpha            float

# Sample sizes (2)
n_train             int
n_holdout           int    # synthetic prop rows for (season, position, stat)

# Selection metric (1)
log_loss            float  # primary; prob_over vs outcome_over

# Sanity metrics (4)
brier               float
mae                 float  # |predicted_mean - actual_value|
rmse                float
bias                float

# GLM diagnostics (2)
aic                 float  # nullable for ConstantResult fallback
max_reliability_dev float  # max |empirical - predicted| over 10 equal-width bins on [0,1]

# Fit metadata (2)
fit_seconds         float
convergence_flag    str    # ok / constant_fallback / fit_error
```

**Implicit rules:**
- For `dist_family=decomposed` on yardage stats: `aic` is null (no single GLM); `prob_over` from Monte Carlo samples
- Reliability binning: 10 equal-width bins on `[0, 1]`
- `mae`/`rmse`/`bias` use `actual_value` from synthetic CSV (continuity with `model_backtest.py`)

---

## 5. Checkpoint format

**Row-level append.**

**Mechanism:**
- Each fit appends its row immediately on completion: `df.to_csv(path, mode='a', header=not path.exists(), index=False)`
- On startup, read existing CSV (if any), build `set[(config_hash, position, stat)]` of completed rows, skip them
- Idempotent — safe to re-run after crash/kill/partial completion

**Stale config_hash:** if existing CSV contains hashes not in the current grid, log a warning and continue. Don't auto-delete.

**Stat-level granularity:** if QB/passing_yards completed but QB/passing_tds didn't for a given config, resume at passing_tds. The dedup key is `(config_hash, position, stat)`, not `(config_hash, position)`.

**Why row-level over batch:** crash at 90% with batch-write loses 63K fits. Row-append is pandas-readable mid-run. File handle overhead negligible at <1 row/sec write rate.

---

## 6. Parallelism

**Sequential, single process. No multiprocessing in v1.**

**Why:**
- GLM fits are deterministic; sequential = parallel for any fixed seed (BLAS reordering ~1e-12, not material to log-loss)
- joblib/multiprocessing pickles the 200MB weekly frame per worker → overhead exceeds GLM fit time
- Memory bounded: one weekly frame + one fitted model at a time

**Seed discipline:** Each fit gets its own deterministic RNG:
```python
seed = hash((config_hash, holdout_season, position, stat)) & 0xFFFFFFFF
rng = np.random.default_rng(seed)
```
Used by Monte Carlo composition in `dist_family=decomposed` so reruns produce bit-identical metrics.

**Future scaling (deferred):** Per-position outer loop (3 workers) cuts wall time to ~45 min if 2h overnight ever becomes a constraint. Inner loop unchanged.

---

## 7. File structure

**New:** `scripts/train_loop.py`
- CLI: `--seasons 2019,2020,2021,2022,2023,2024` (default = all 6); `--positions qb,rb,wr_te` (default all); `--out-dir docs/training/`
- One pass: for each holdout_season → for each config → fit 3 position models → eval against synthetic CSV → append row per (config, position, stat) to season CSV
- Skips already-completed rows on resume

**New:** `tests/test_l1_path.py`
- Required by plan.md verification: fit QB across alpha grid `{0.0, 0.001, 0.01, 0.1}` on 2018–2019; assert nonzero coefficient count is monotonically non-increasing as alpha grows

**Modified:** `plan.md` — update verification line "4 of 7" → "4 of 6" walk-forward steps

---

## 8. Test plan

`tests/test_l1_path.py`:
- `test_l1_alpha_monotonically_reduces_nonzero_coefficients` — load minimal QB fixture, fit at alpha ∈ {0.0, 0.001, 0.01, 0.1}, assert nonzero count is non-increasing

Smoke tests for `train_loop.py` (in `tests/test_train_loop.py`, optional but recommended):
- `test_resume_skips_completed_rows` — write a partial CSV, run loop on a 2-config sub-grid, verify only missing rows added
- `test_config_hash_is_deterministic` — same config dict → same hash across calls
- `test_log_loss_computed_correctly` — synthetic mock data with known prob_over and outcome_over, verify log_loss against `sklearn.metrics.log_loss`

`uv run pytest tests/test_l1_path.py` and `tests/test_train_loop.py` should be green before running the full grid.

---

## 9. Verification (Definition of Done for H2)

Per plan.md H2 verification:
1. `scripts/train_loop.py` runs end-to-end, producing `docs/training/season_<YYYY>_results.csv` for all 6 holdout seasons
2. Each season CSV has ~11,520 rows (1152 configs × ~10 stats)
3. Resume from partial CSV works correctly (re-running skips completed rows)
4. `tests/test_l1_path.py` passes
5. Spot-check: best log-loss config per (position, stat) is sensible (e.g., not always `dist_family=legacy`, not always `l1_alpha=0`)
6. Off-LLM compute window: `uv run python scripts/train_loop.py` for ~2h after green tests; commit results CSVs as the H2 artifact

---

## 10. Out of scope (handled in later sub-phases)

- **Reliability PNG rendering** → H4 `synthesize_training.py`
- **Cross-season Pareto ranking** → H4
- **Qwen narration** → H3
- **Final config lock-in** → H5
- **2025 holdout** → H5 (`final_eval` window, four-window reserved)
